#!/usr/bin/env python3
"""
fetch_direct_companies.py — Pull jobs from company career sites (Google,
Amazon, Microsoft, …), apply the same dedup + redflag + role-skip filters as
the LinkedIn browser pipeline, and write ollama_input.json ready for
run_ollama_local.py.  Unlike the LinkedIn path, JD text is already present
after the fetch — no separate browser JD-fetch step is needed.

Usage:
  python3 scripts/pipeline/fetch_direct_companies.py \\
      --run-dir data/pipeline/browser_runs/<RUNDIR>/ \\
      [--sources google,amazon,microsoft] \\
      [--since-days 7] \\
      [--max-pages 10] \\
      [--ms-jobs ~/Downloads/ms_jobs.json]

Output: <run-dir>/ollama_input.json  (68 jobs keyed by "source:id")
        <run-dir>/to_score.json      (audit + seen_jobs dedup input)

─── How to add a new source ─────────────────────────────────────────────────
1. Write  _fetch_<name>(args, max_pages) -> list[dict]
   Every returned dict MUST have these keys (extras are fine):
     id          "source:raw_id"  e.g. "stripe:12345"
     source      "stripe"
     title       str
     company     str
     location    str
     description str  (full JD text — this goes to Ollama)
     url         str  (direct apply link)
     posted      str | None  (ISO-8601 or None — used for --since-days)

2. Add source-specific CLI args to _parse_args() if needed.

3. Register it in the SOURCES dispatch table at the bottom of this file.
   One line:  "stripe": lambda args, mp: _fetch_stripe(args, mp),
─────────────────────────────────────────────────────────────────────────────
"""

import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone

# ── locate project root and import shared helpers ────────────────────────────
def _find_project_root(start):
    d = os.path.abspath(start)
    for _ in range(8):
        if os.path.exists(os.path.join(d, "candidate_profile.json")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(start)

def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", default=None)
    p.add_argument("--sources", default="google,amazon",
                   help="comma list of registered sources (default: google,amazon). "
                        "Available: google, amazon, microsoft, greenhouse, workday. "
                        "Add --gh-jobs for greenhouse, --ms-jobs for microsoft, "
                        "--wd-jobs for workday.")
    p.add_argument("--ms-jobs", default=None,
                   help="path to ms_jobs.json from scrape_microsoft_careers.js")
    p.add_argument("--gh-jobs", default=None,
                   help="path to greenhouse_jobs.json from scrape_greenhouse_browser.js")
    p.add_argument("--wd-jobs", default=None,
                   help="path to workday_jobs.json from scrape_workday_google.js")
    p.add_argument("--google-query", default='"Software Engineer"')
    p.add_argument("--google-location", default="India")
    p.add_argument("--amazon-country", default="IND")
    p.add_argument("--amazon-categories", default="software-development",
                   help="comma list of Amazon job categories")
    p.add_argument("--max-pages", type=int, default=5)
    p.add_argument("--since-days", type=int, default=0,
                   help="drop postings older than N days (0 = no filter)")
    return p.parse_args()

def _load_profile(run_dir):
    root = _find_project_root(run_dir)
    path = os.path.join(root, "candidate_profile.json")
    with open(path) as f:
        p = json.load(f)
    p["_root"] = root
    return p

# ── fetch adapters ────────────────────────────────────────────────────────────

def _fetch_google(query, location, max_pages):
    """Import and call src_google_careers from scripts/fetch_jobs.py."""
    root = _find_project_root(os.getcwd())
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import fetch_jobs as fj
    jobs = fj.src_google_careers(query=query, location=location, max_pages=max_pages)
    print(f"  google: fetched {len(jobs)} jobs", file=sys.stderr)
    return jobs

def _fetch_amazon(country, categories, max_pages):
    root = _find_project_root(os.getcwd())
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import fetch_jobs as fj
    cats = [c.strip() for c in categories.split(",")]
    jobs = fj.src_amazon_jobs(categories=cats, country=country, max_pages=max_pages)
    print(f"  amazon: fetched {len(jobs)} jobs", file=sys.stderr)
    return jobs

def _fetch_greenhouse(gh_jobs_path):
    """Load greenhouse_jobs.json downloaded from scrape_greenhouse_browser.js.

    Full JD text is NOT present here — it's fetched later by fetch_direct_jds
    via the public boards-api.greenhouse.io endpoint (no auth needed).
    """
    if not gh_jobs_path or not os.path.exists(gh_jobs_path):
        print(f"  greenhouse: skipped (no gh_jobs.json provided)", file=sys.stderr)
        return []
    with open(gh_jobs_path) as f:
        raw = json.load(f)
    jobs = []
    for j in raw:
        token = (j.get("company_token") or "").strip()
        jid   = str(j.get("job_id") or "").strip()
        if not token or not jid:
            continue
        jobs.append({
            "id":          f"greenhouse:{token}:{jid}",
            "source":      "greenhouse",
            "title":       (j.get("title") or "").strip(),
            "company":     (j.get("company") or "").strip(),
            "location":    (j.get("location") or "").strip(),
            "description": "",   # filled by fetch_direct_jds.fetch_greenhouse_jd
            "url":         j.get("url") or f"https://my.greenhouse.io/{token}/jobs/{jid}",
            "posted":      None,
            "remote":      None,
            "visa_sponsorship": None,
            "tags":        [],
            "salary":      None,
        })
    print(f"  greenhouse: loaded {len(jobs)} jobs from {gh_jobs_path}", file=sys.stderr)
    return jobs


def _fetch_microsoft(ms_jobs_path):
    """Load ms_jobs.json downloaded from scrape_microsoft_careers.js."""
    if not ms_jobs_path or not os.path.exists(ms_jobs_path):
        print(f"  microsoft: skipped (no ms_jobs.json provided)", file=sys.stderr)
        return []
    with open(ms_jobs_path) as f:
        raw = json.load(f)
    # ms_jobs.json schema: [{id, title, company, location, url, description, posted, ...}]
    # normalise to match fetch_jobs._norm output
    jobs = []
    for j in raw:
        jid = j.get("id", "")
        jobs.append({
            "id":          f"microsoft:{jid}",
            "source":      "microsoft",
            "title":       (j.get("title") or "").strip(),
            "company":     (j.get("company") or "Microsoft").strip(),
            "location":    (j.get("location") or "").strip(),
            "description": (j.get("description") or "").strip(),
            "url":         j.get("url") or f"https://jobs.careers.microsoft.com/global/en/job/{jid}",
            "posted":      j.get("posted"),
            "remote":      None,
            "visa_sponsorship": None,
            "tags":        [],
            "salary":      None,
        })
    print(f"  microsoft: loaded {len(jobs)} jobs from {ms_jobs_path}", file=sys.stderr)
    return jobs

# ── date filter (mirrors fetch_jobs._recent) ─────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d",
                "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(s.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _since_filter(jobs, since_days):
    if not since_days:
        return jobs
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    kept = []
    dropped = 0
    for j in jobs:
        dt = _parse_date(j.get("posted"))
        if dt is None or dt >= cutoff:
            kept.append(j)
        else:
            dropped += 1
    if dropped:
        print(f"  since_days={since_days}: dropped {dropped} jobs older than {cutoff.date()}", file=sys.stderr)
    return kept


def _fetch_workday(wd_jobs_path):
    """Load workday_jobs.json downloaded from scrape_workday_google.js.

    Full JD text is NOT present here — it's fetched later by fetch_direct_jds
    via the JSON-LD schema embedded in each Workday job HTML page (no auth needed).
    """
    if not wd_jobs_path or not os.path.exists(wd_jobs_path):
        print(f"  workday: skipped (no wd_jobs.json provided)", file=sys.stderr)
        return []
    with open(wd_jobs_path) as f:
        raw = json.load(f)
    jobs = []
    for j in raw:
        url = (j.get("url") or "").strip()
        if not url or "myworkdayjobs.com" not in url:
            continue
        # Parse URL: https://tenant.wd{N}.myworkdayjobs.com/[lang/]career_site/job/loc/Title_ID
        m = re.match(
            r'https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com'
            r'/(?:[a-z]{2}-[A-Z]{2}/)?'  # optional lang like en-US/
            r'([^/]+)'                    # career_site
            r'/job/[^/]+/'                # /job/{location}/
            r'[^?#]*_([^?#/_]+)',         # Title_{job_id}
            url
        )
        if not m:
            continue
        tenant, wd, career_site, job_id = m.groups()
        jobs.append({
            "id":          f"workday:{tenant}:{wd}:{career_site}:{job_id}",
            "source":      "workday",
            "title":       (j.get("title") or "").strip(),
            "company":     (j.get("company") or "").strip(),
            "location":    (j.get("location") or "").strip(),
            "description": "",   # filled by fetch_direct_jds.fetch_workday_jd
            "url":         url,
            "posted":      None,
            "remote":      None,
            "visa_sponsorship": None,
            "tags":        [],
            "salary":      None,
        })
    print(f"  workday: loaded {len(jobs)} jobs from {wd_jobs_path}", file=sys.stderr)
    return jobs


# ── source registry ──────────────────────────────────────────────────────────
# Maps source name → fetch lambda(args, max_pages) → list[dict].
# Add new sources here after writing _fetch_<name> above.

def _build_dispatch(args, max_pages):
    return {
        "google":     lambda: _fetch_google(args.google_query, args.google_location, max_pages),
        "amazon":     lambda: _fetch_amazon(args.amazon_country, args.amazon_categories, max_pages),
        "microsoft":  lambda: _fetch_microsoft(args.ms_jobs),
        "greenhouse": lambda: _fetch_greenhouse(args.gh_jobs),
        "workday":    lambda: _fetch_workday(args.wd_jobs),
        # "stripe":   lambda: _fetch_stripe(args, max_pages),  # example
    }


# ── filter logic (mirrors filter_jobs.py) ────────────────────────────────────

def _apply_filters(jobs, profile, run_dir):
    root      = profile["_root"]
    seen_path = os.path.join(root, profile.get("seen_jobs_file", "data/pipeline/seen_jobs.json"))
    avoid_path = os.path.join(root, profile.get("avoid_companies_file", "data/pipeline/companies_avoid.txt"))
    rf_path   = os.path.join(root, "data/pipeline/redflag_companies.json")

    def _report(step, label, before, after):
        diff = len(before) - len(after)
        marker = " ←" if diff else ""
        print(f"  [{step}] {label:<40} {len(before):>4} → {len(after):>4}  (-{diff}){marker}", file=sys.stderr)

    # 1. seen_jobs dedup
    seen_ids = set()
    if os.path.exists(seen_path):
        seen = json.load(open(seen_path))
        for k in seen:
            m = re.match(r"^li:(.+)$", k)
            seen_ids.add(m.group(1) if m else k)  # handle both li: and raw keys
    before = jobs
    jobs = [j for j in jobs if j["id"] not in seen_ids]
    _report(1, "seen_jobs dedup", before, jobs)

    # 2. companies_avoid
    avoid = set()
    if os.path.exists(avoid_path):
        avoid = {l.strip().lower() for l in open(avoid_path) if l.strip() and not l.startswith("#")}
    before = jobs
    jobs = [j for j in jobs if j["company"].lower() not in avoid]
    _report(2, "companies_avoid", before, jobs)

    # 3. redflag_companies
    rf_pats, rf_exact = [], set()
    if os.path.exists(rf_path):
        rf = json.load(open(rf_path))
        rf_pats  = [re.compile(p, re.I) for p in rf.get("patterns", [])]
        rf_exact = {e.lower() for e in rf.get("exact", [])}
    before = jobs
    jobs = [j for j in jobs
            if j["company"].lower() not in rf_exact
            and not any(p.search(j["company"]) for p in rf_pats)]
    _report(3, "redflag_companies", before, jobs)

    # 4. role_skip_patterns
    role_pats = [re.compile(p, re.I) for p in profile.get("role_skip_patterns", [])]
    ROLE_SKIP = re.compile("|".join(profile.get("role_skip_patterns", [])), re.I) if profile.get("role_skip_patterns") else None
    before = jobs
    jobs = [j for j in jobs if not (ROLE_SKIP and ROLE_SKIP.search(j["title"]))]
    _report(4, "role_skip_patterns", before, jobs)

    # 5. seniority pre-cap titles (Lead/Principal/Staff/Architect/Manager)
    cap_pat_str = profile.get("seniority_cap_pattern", r"\b(lead|principal|staff engineer|architect|engineering manager|head of|chief)\b")
    cap_pat = re.compile(cap_pat_str, re.I)
    cap     = profile.get("seniority_cap", 55)
    bonus   = profile.get("tier1_bonus", 8)
    before  = jobs
    jobs    = [j for j in jobs if not cap_pat.search(j["title"]) or (cap + bonus) >= 70]
    _report(5, "seniority pre-cap", before, jobs)

    return jobs

# ── build ollama_input.json ───────────────────────────────────────────────────

def _build_ollama_input(filtered_jobs, all_jobs_by_id):
    """Convert filtered job list to ollama_input.json format."""
    out = {}
    for j in filtered_jobs:
        jid  = j["id"]
        orig = all_jobs_by_id.get(jid, j)
        out[jid] = {
            "jd":         (orig.get("description") or "").strip(),
            "title":      orig.get("title", ""),
            "company":    orig.get("company", ""),
            "staffCount": None,   # not available from public APIs
            "listedAt":   orig.get("posted"),
            "applies":    None,
            "url":        orig.get("url", ""),
            "source":     orig.get("source", ""),
        }
    return out

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    args    = _parse_args()
    run_dir = os.path.abspath(args.run_dir or os.getcwd())
    os.makedirs(run_dir, exist_ok=True)

    profile = _load_profile(run_dir)
    sources = [s.strip().lower() for s in args.sources.split(",")]

    dispatch = _build_dispatch(args, args.max_pages)
    unknown  = [s for s in sources if s not in dispatch]
    if unknown:
        print(f"WARNING: unknown sources ignored: {', '.join(unknown)}", file=sys.stderr)
        print(f"  Available: {', '.join(dispatch)}", file=sys.stderr)
    sources = [s for s in sources if s in dispatch]
    print(f"Fetching from: {', '.join(sources)}", file=sys.stderr)

    # ── fetch ────────────────────────────────────────────────────────────────
    all_jobs = []
    for src in sources:
        all_jobs += dispatch[src]()

    # dedup by ID within this fetch
    seen = {}
    for j in all_jobs:
        if j["id"] not in seen:
            seen[j["id"]] = j
    all_jobs = list(seen.values())
    print(f"Raw fetch: {len(all_jobs)} unique jobs across all sources", file=sys.stderr)

    # date filter
    if args.since_days:
        all_jobs = _since_filter(all_jobs, args.since_days)

    # JD enrichment — replace search snippets with full descriptions
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from fetch_direct_jds import enrich_jds
    all_jobs = enrich_jds(all_jobs)

    all_jobs_by_id = {j["id"]: j for j in all_jobs}

    # ── save to_score.json (audit + seen_jobs tracking) ──────────────────────
    to_score = [
        {"id": j["id"], "title": j["title"], "company": j["company"],
         "location": j["location"], "listedAt": j.get("posted"),
         "keyword": j.get("source", "")}
        for j in all_jobs
    ]
    to_score_path = os.path.join(run_dir, "to_score.json")
    with open(to_score_path, "w") as f:
        json.dump(to_score, f, indent=2)

    # ── filter ───────────────────────────────────────────────────────────────
    print(f"\nFiltering {len(all_jobs)} jobs:", file=sys.stderr)
    filtered = _apply_filters(all_jobs, profile, run_dir)
    print(f"\nFunnel: {len(all_jobs)} → {len(filtered)}  ({len(all_jobs)-len(filtered)} filtered, "
          f"{int((len(all_jobs)-len(filtered))/max(len(all_jobs),1)*100)}% saved)", file=sys.stderr)

    # ── write ollama_input.json ───────────────────────────────────────────────
    ollama_input = _build_ollama_input(filtered, all_jobs_by_id)
    out_path = os.path.join(run_dir, "ollama_input.json")
    with open(out_path, "w") as f:
        json.dump(ollama_input, f, indent=2)
    print(f"\nWritten → {out_path}  ({len(ollama_input)} jobs ready for Ollama)", file=sys.stderr)

    print(f"\nNext:", file=sys.stderr)
    print(f"  python3 scripts/pipeline/run_ollama_local.py --run-dir {run_dir}", file=sys.stderr)
    print(f"  python3 scripts/pipeline/build_queue.py      --run-dir {run_dir}", file=sys.stderr)

if __name__ == "__main__":
    main()
