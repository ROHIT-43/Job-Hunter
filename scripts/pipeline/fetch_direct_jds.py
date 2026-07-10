#!/usr/bin/env python3
"""
fetch_direct_jds.py — Per-source full-JD fetchers for direct company pipelines.

Search/list APIs return truncated snippets (~600–1200 chars). This module
fetches the individual job detail page for each source and replaces the snippet
with the full description (3–8K chars), which is what Ollama scores.

Called automatically by fetch_direct_companies.py after the initial fetch.
Can also be imported standalone for re-enrichment of existing job lists.

─── How to add a new source ─────────────────────────────────────────────────
1. Write  fetch_<name>_jd(job) -> dict
   - Input:  a job dict with at minimum {"id": "name:xxx", "url": str, "description": str}
   - Output: the same dict (or a copy) with `description` replaced by full text
   - On any fetch/parse failure: return job unchanged (never raise)

2. Register it in JD_FETCHERS at the bottom of this file.
   One line:  "stripe": fetch_stripe_jd,
─────────────────────────────────────────────────────────────────────────────

Sources that do NOT need enrichment (already have full JDs from their fetch):
  microsoft — position_details API returns full JD text
  linkedin  — voyager jobPostings API returns full JD text (browser path)
"""

import re, sys, urllib.request, concurrent.futures, os


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_html(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _http_get(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _find_project_root(start=None):
    d = os.path.abspath(start or os.getcwd())
    for _ in range(8):
        if os.path.exists(os.path.join(d, "candidate_profile.json")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(start or os.getcwd())


# ── per-source JD fetchers ────────────────────────────────────────────────────

def fetch_google_jd(job):
    """Fetch individual Google Careers page → full JD from ds:0 data block."""
    url = job.get("url", "")
    if not url:
        return job
    root = _find_project_root()
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import fetch_jobs as fj
        html = fj._get(url, headers={"Accept": "text/html"})
        if not html:
            return job
        d = fj._af_data_block(html, "ds:0")
        if not d or not isinstance(d, list) or not d[0]:
            return job
        entry = d[0]
        resp  = entry[3][1] if len(entry) > 3 and entry[3] and len(entry[3]) > 1 else ""
        quals = entry[4][1] if len(entry) > 4 and entry[4] and len(entry[4]) > 1 else ""
        full  = _strip_html(resp + " " + quals)
    except Exception:
        return job
    if len(full) > len(job.get("description") or ""):
        job = dict(job)
        job["description"] = full
    return job


def fetch_amazon_jd(job):
    """Fetch individual Amazon job page → Description + Basic/Preferred Qualifications."""
    url = job.get("url", "")
    if not url or "amazon.jobs" not in url:
        return job
    html = _http_get(url)
    if not html:
        return job
    sections = re.findall(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|</section)", html, re.S)
    parts = []
    for title, body in sections:
        clean_title = _strip_html(title)
        if clean_title not in ("Description", "Basic Qualifications", "Preferred Qualifications"):
            continue
        clean_body = _strip_html(body)
        if clean_body:
            parts.append(clean_title + "\n" + clean_body)
    full = "\n\n".join(parts)
    if len(full) > len(job.get("description") or ""):
        job = dict(job)
        job["description"] = full
    return job


def fetch_workday_jd(job):
    """Fetch full JD from a Workday job HTML page via embedded JSON-LD schema.

    All Workday job pages include a <script type="application/ld+json"> block
    with @type=JobPosting that contains the full description — no auth needed.
    """
    import json as _json, re as _re
    url = job.get("url", "")
    if not url or "myworkdayjobs.com" not in url:
        return job
    html = _http_get(url)
    if not html:
        return job
    for block in _re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, _re.S
    ):
        try:
            d = _json.loads(block.strip())
            if d.get("@type") != "JobPosting":
                continue
            desc     = _strip_html(d.get("description", ""))
            title    = d.get("title", "")
            company  = (d.get("hiringOrganization") or {}).get("name", "")
            date_p   = d.get("datePosted", "")
            loc_raw  = d.get("jobLocation") or {}
            if isinstance(loc_raw, list):
                loc_raw = loc_raw[0]
            location = (loc_raw.get("address") or {}).get("addressLocality", "")
            if len(desc) > len(job.get("description") or ""):
                job = dict(job); job["description"] = desc
            if not job.get("title") and title:
                job = dict(job); job["title"] = title
            if not job.get("company") and company:
                job = dict(job); job["company"] = company
            if not job.get("location") and location:
                job = dict(job); job["location"] = location
            if not job.get("posted") and date_p:
                job = dict(job); job["posted"] = date_p
            break
        except Exception:
            continue
    return job


def fetch_greenhouse_jd(job):
    """Fetch full JD from boards-api.greenhouse.io (public, no auth needed).

    Job ID format: "greenhouse:{company_token}:{job_id}"
    API: https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}
    """
    import json as _json
    parts = job["id"].split(":")
    if len(parts) < 3:
        return job
    token, jid = parts[1], parts[2]
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}"
    data = _http_get(url)
    if not data:
        return job
    try:
        d = _json.loads(data)
        content  = _strip_html(d.get("content", ""))
        title    = d.get("title", "")
        location = (d.get("location") or {}).get("name", "")
        updated  = d.get("updated_at", "")
        if len(content) > len(job.get("description") or ""):
            job = dict(job)
            job["description"] = content
        if not job.get("title") and title:
            job = dict(job); job["title"] = title
        if not job.get("location") and location:
            job = dict(job); job["location"] = location
        if not job.get("posted") and updated:
            job = dict(job); job["posted"] = updated
    except Exception:
        pass
    return job


# ── registry ──────────────────────────────────────────────────────────────────
# Maps source name → JD fetch function.
# Sources not listed here are skipped (assumed to already carry full JDs).

JD_FETCHERS = {
    "google":     fetch_google_jd,
    "amazon":     fetch_amazon_jd,
    "greenhouse": fetch_greenhouse_jd,
    "workday":    fetch_workday_jd,
    # "stripe": fetch_stripe_jd,   # example — add new sources here
}


# ── public API ────────────────────────────────────────────────────────────────

def enrich_jds(jobs, concurrency=8):
    """Replace search-snippet descriptions with full JD text for registered sources.

    Jobs whose source is not in JD_FETCHERS (e.g. microsoft, linkedin) are
    returned unchanged — they already carry full descriptions.
    """
    to_enrich = [j for j in jobs if j["id"].split(":")[0] in JD_FETCHERS]
    passthrough = [j for j in jobs if j["id"].split(":")[0] not in JD_FETCHERS]

    if not to_enrich:
        return jobs

    by_source = {}
    for j in to_enrich:
        by_source.setdefault(j["id"].split(":")[0], 0)
        by_source[j["id"].split(":")[0]] += 1
    summary = ", ".join(f"{n} {s}" for s, n in by_source.items())
    print(f"  enriching JDs: {summary} ({concurrency} concurrent)…", file=sys.stderr)

    def _run(job):
        src = job["id"].split(":")[0]
        return JD_FETCHERS[src](job)

    before_avg = sum(len(j.get("description") or "") for j in to_enrich) / len(to_enrich)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        enriched = list(ex.map(_run, to_enrich))
    after_avg = sum(len(j.get("description") or "") for j in enriched) / len(enriched)

    print(f"  JD avg: {int(before_avg)} → {int(after_avg)} chars after enrichment",
          file=sys.stderr)

    enriched_by_id = {j["id"]: j for j in enriched}
    return [enriched_by_id.get(j["id"], j) for j in to_enrich] + passthrough
