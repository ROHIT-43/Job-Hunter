#!/usr/bin/env python3
"""
fetch_jobs.py — Pull live job listings from sources that offer clean, public
APIs or RSS feeds, normalize them into one schema, and write JSON.

Jobs are kept by DEPARTMENT (engineering/technology family), not by keyword.
One run sweeps all buckets (India + global-remote + visa) at once; remote/visa
are per-job attributes you can hard-filter with --remote / --visa.

This intentionally only touches sources that permit programmatic access.
LinkedIn / Naukri / Indeed are NOT fetched here (their ToS forbid scraping) —
use scripts/search_urls.py for those, or an Apify actor (see references/path-apify.md).

Requires network access (the calling environment must have egress enabled).
Uses only the Python standard library so it runs anywhere.

Example:
  python fetch_jobs.py \
      --departments software,engineering,technology --since-days 30 \
      --adzuna-country in --adzuna-id $ADZUNA_ID --adzuna-key $ADZUNA_KEY \
      --out jobs.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import department  # noqa: E402

UA = "Mozilla/5.0 (compatible; job-hunter-skill/1.0; +https://example.com/bot)"
TIMEOUT = 25


def _get(url, headers=None, retries=2):
    """GET a URL, returning decoded text or None on failure."""
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE401
            last_err = e
            time.sleep(1.2 * (attempt + 1))
    print(f"  ! fetch failed: {url} ({last_err})", file=sys.stderr)
    return None


def _get_json(url, headers=None):
    txt = _get(url, headers=headers)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def _norm(source, native_id, title, company, location, url,
          remote=None, visa=None, tags=None, salary=None,
          description=None, posted=None):
    """Build one normalized job record."""
    return {
        "id": f"{source}:{native_id}",
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "remote": remote,
        "visa_sponsorship": visa,  # True / False / None(unknown)
        "tags": [t.lower() for t in (tags or []) if t],
        "salary": salary,
        "description": _clean(description),
        "url": url,
        "posted": posted,  # ISO date string or None
    }


def _clean(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


# --------------------------------------------------------------------------
# Source adapters. Each returns a list of normalized records (never raises).
# Adapters fetch broadly (no keyword query); the department gate filters later.
# --------------------------------------------------------------------------

def src_remoteok():
    data = _get_json("https://remoteok.com/api")
    out = []
    if not isinstance(data, list):
        return out
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue
        out.append(_norm(
            "remoteok", j.get("id"), j.get("position"), j.get("company"),
            j.get("location") or "Remote", j.get("url") or j.get("apply_url"),
            remote=True, tags=j.get("tags"),
            salary=_salary(j.get("salary_min"), j.get("salary_max")),
            description=j.get("description"), posted=j.get("date"),
        ))
    return out


def src_remotive():
    data = _get_json("https://remotive.com/api/remote-jobs?limit=100")
    out = []
    for j in (data or {}).get("jobs", []):
        out.append(_norm(
            "remotive", j.get("id"), j.get("title"), j.get("company_name"),
            j.get("candidate_required_location") or "Remote", j.get("url"),
            remote=True, tags=j.get("tags"), salary=j.get("salary") or None,
            description=j.get("description"),
            posted=j.get("publication_date"),
        ))
    return out


def src_arbeitnow():
    """Arbeitnow exposes a remote/visa flag — valuable for sponsorship hunts."""
    out = []
    for page in range(1, 4):
        data = _get_json(
            f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        rows = (data or {}).get("data", [])
        if not rows:
            break
        for j in rows:
            tags = (j.get("tags") or []) + (j.get("job_types") or [])
            visa = True if j.get("visa_sponsorship") else None
            out.append(_norm(
                "arbeitnow", j.get("slug"), j.get("title"),
                j.get("company_name"), j.get("location"), j.get("url"),
                remote=bool(j.get("remote")), visa=visa, tags=tags,
                description=j.get("description"),
                posted=_epoch(j.get("created_at")),
            ))
    return out


def src_himalayas():
    data = _get_json("https://himalayas.app/jobs/api?limit=100")
    out = []
    for j in (data or {}).get("jobs", []):
        locs = j.get("locationRestrictions") or []
        out.append(_norm(
            "himalayas", j.get("guid") or j.get("id"), j.get("title"),
            j.get("companyName"), ", ".join(locs) or "Remote",
            j.get("applicationLink") or j.get("url"),
            remote=True, tags=j.get("categories"),
            salary=_salary(j.get("minSalary"), j.get("maxSalary")),
            description=j.get("description"), posted=_epoch(j.get("pubDate")),
        ))
    return out


def src_jobicy():
    data = _get_json("https://jobicy.com/api/v2/remote-jobs?count=50")
    out = []
    for j in (data or {}).get("jobs", []):
        out.append(_norm(
            "jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"),
            j.get("jobGeo") or "Remote", j.get("url"),
            remote=True, tags=j.get("jobIndustry"),
            salary=j.get("annualSalaryMin"),
            description=j.get("jobExcerpt"), posted=j.get("pubDate"),
        ))
    return out


def src_themuse():
    out = []
    for page in range(0, 3):
        url = ("https://www.themuse.com/api/public/jobs"
               f"?category=Software%20Engineering&page={page}")
        data = _get_json(url)
        for j in (data or {}).get("results", []):
            locs = [l.get("name") for l in j.get("locations", [])]
            out.append(_norm(
                "themuse", j.get("id"), j.get("name"),
                (j.get("company") or {}).get("name"),
                ", ".join(locs), (j.get("refs") or {}).get("landing_page"),
                remote=any("remote" in (x or "").lower() for x in locs),
                tags=[c.get("name") for c in j.get("categories", [])],
                description=j.get("contents"),
                posted=j.get("publication_date"),
            ))
    return out


def src_wwr():
    """We Work Remotely RSS — programming category."""
    feed = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
    txt = _get(feed)
    out = []
    if not txt:
        return out
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "")
        company, _, role = title.partition(":")
        out.append(_norm(
            "weworkremotely", item.findtext("guid") or item.findtext("link"),
            role.strip() or title, company.strip(), "Remote",
            item.findtext("link"), remote=True,
            description=item.findtext("description"),
            posted=item.findtext("pubDate"),
        ))
    return out


def src_adzuna(country, app_id, app_key, categories):
    """Adzuna — the cleanest programmatic source for the INDIA market. Filters
    by category facet (e.g. it-jobs) rather than a keyword query.
    Get a free app_id/app_key at https://developer.adzuna.com/."""
    if not (app_id and app_key):
        print("  - adzuna skipped (no app_id/app_key)", file=sys.stderr)
        return []
    category = ("&category=" + categories[0]) if categories else ""
    out = []
    for page in range(1, 4):
        url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
               f"?app_id={app_id}&app_key={app_key}"
               f"&results_per_page=50{category}"
               f"&content-type=application/json")
        data = _get_json(url)
        rows = (data or {}).get("results", [])
        if not rows:
            break
        for j in rows:
            out.append(_norm(
                "adzuna", j.get("id"), j.get("title"),
                (j.get("company") or {}).get("display_name"),
                (j.get("location") or {}).get("display_name"),
                j.get("redirect_url"),
                salary=_salary(j.get("salary_min"), j.get("salary_max")),
                tags=[(j.get("category") or {}).get("label")],
                description=j.get("description"), posted=j.get("created"),
            ))
    return out


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _salary(lo, hi):
    if not lo and not hi:
        return None
    if lo and hi:
        return f"{int(lo):,}-{int(hi):,}"
    return f"{int(lo or hi):,}"


def _epoch(v):
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return v if isinstance(v, str) else None


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


# --------------------------------------------------------------------------
# filtering
# --------------------------------------------------------------------------

def _matches_loc(job, location):
    if not location:
        return True
    loc = location.lower()
    fields = (job["location"] or "").lower()
    # remote jobs are location-agnostic
    if job.get("remote"):
        return True
    return loc in fields or fields in loc or "worldwide" in fields


def _recent(job, since_days):
    if not since_days:
        return True
    dt = _parse_date(job.get("posted"))
    if not dt:
        return True  # keep when date unknown
    return dt >= datetime.now(timezone.utc) - timedelta(days=since_days)


def filter_jobs(jobs, departments, location, remote, visa, since_days):
    """Dedup + gate jobs by department/location/remote/visa/recency.

    Each kept job gains a sorted `departments` list of its assigned buckets.
    """
    out, seen = [], set()
    for j in jobs:
        key = (j["title"].lower(), j["company"].lower())
        if key in seen:
            continue
        kept, depts = department.matches(j, departments)
        if not kept:
            continue
        if location and not _matches_loc(j, location):
            continue
        if remote and not j.get("remote"):
            continue
        if visa and j.get("visa_sponsorship") is not True:
            continue
        if not _recent(j, since_days):
            continue
        j = dict(j)
        j["departments"] = sorted(depts)
        seen.add(key)
        out.append(j)
    return out


ALL_SOURCES = {
    "remoteok": src_remoteok,
    "remotive": src_remotive,
    "arbeitnow": src_arbeitnow,
    "himalayas": src_himalayas,
    "jobicy": src_jobicy,
    "themuse": src_themuse,
    "weworkremotely": src_wwr,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--departments",
                    default=",".join(department.default_departments()),
                    help="comma list from the taxonomy; default = "
                         "software,engineering,technology")
    ap.add_argument("--location", default="", help="e.g. India, Bengaluru, EU")
    ap.add_argument("--remote", action="store_true",
                    help="keep only remote-eligible roles")
    ap.add_argument("--visa", action="store_true",
                    help="keep only roles flagged as visa-sponsoring (where known)")
    ap.add_argument("--since-days", type=int, default=0,
                    help="drop postings older than N days (0 = no filter)")
    ap.add_argument("--sources", default="all",
                    help="comma list from: " + ",".join(ALL_SOURCES) + ",adzuna")
    ap.add_argument("--adzuna-country", default="in",
                    help="adzuna country code (in, us, gb, de, ...)")
    ap.add_argument("--adzuna-id", default="")
    ap.add_argument("--adzuna-key", default="")
    ap.add_argument("--out", default="jobs.json")
    args = ap.parse_args()

    depts = [d.strip() for d in args.departments.split(",") if d.strip()]
    want = (list(ALL_SOURCES) + ["adzuna"] if args.sources == "all"
            else [s.strip() for s in args.sources.split(",") if s.strip()])

    jobs = []
    for name in want:
        print(f"-> {name}", file=sys.stderr)
        try:
            if name == "adzuna":
                cats = department.facet_codes(depts, "adzuna")
                jobs += src_adzuna(args.adzuna_country, args.adzuna_id,
                                   args.adzuna_key, cats)
            elif name in ALL_SOURCES:
                jobs += ALL_SOURCES[name]()
            else:
                print(f"  ! unknown source: {name}", file=sys.stderr)
        except Exception as e:  # noqa: BLE401
            print(f"  ! {name} adapter error: {e}", file=sys.stderr)

    filtered = filter_jobs(jobs, depts, args.location, args.remote,
                           args.visa, args.since_days)

    with open(args.out, "w") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)
    print(f"\n{len(filtered)} jobs (from {len(jobs)} raw) -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
