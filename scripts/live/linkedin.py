"""linkedin.py — LinkedIn public (guest, no login) job search + job detail client.

Endpoints (HTML fragments, no auth):
  search: /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&location=&f_TPR=&f_E=&f_JT=&start=
          10 cards per page; an empty page means the end of results.
  detail: /jobs-guest/jobs/api/jobPosting/<id>
Throttling (429 / 999 / 5xx) is retried with backoff; a run of consecutive blocks
raises Blocked so the caller can stop early and keep what it has.
"""
import html
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://www.linkedin.com/jobs-guest/jobs/api"
_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]
_RETRY_STATUS = {429, 999, 500, 502, 503, 504}
_BACKOFF = (5, 15, 45)


class Blocked(Exception):
    """LinkedIn kept refusing requests — stop scraping for this run."""


class Client:
    def __init__(self, delay=1.2, max_blocked=8, timeout=20):
        self.delay = delay
        self.max_blocked = max_blocked
        self.timeout = timeout
        self.blocked_streak = 0
        self.requests = 0
        self.blocked_total = 0
        self.stopped = False

    def get(self, url):
        """Response body, or None on a non-retryable miss (404 etc.)."""
        if self.stopped:
            raise Blocked("client stopped after repeated blocks")
        for attempt in range(len(_BACKOFF) + 1):
            time.sleep(self.delay * random.uniform(0.7, 1.3))
            self.requests += 1
            req = urllib.request.Request(url, headers={
                "User-Agent": random.choice(_UAS),
                "Accept-Language": "en-US,en;q=0.9",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self.blocked_streak = 0
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code not in _RETRY_STATUS:
                    return None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            self.blocked_total += 1
            self.blocked_streak += 1
            if self.blocked_streak >= self.max_blocked:
                self.stopped = True
                raise Blocked(f"{self.blocked_streak} blocked responses in a row")
            if attempt < len(_BACKOFF):
                time.sleep(_BACKOFF[attempt])
        return None


# ── parsing ──────────────────────────────────────────────────────────────────

def _text(fragment):
    s = re.sub(r"<br\s*/?>|</(?:p|li|div|h\d)>", "\n", fragment or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


def _first(pattern, s, flags=re.S):
    m = re.search(pattern, s, flags)
    return _text(m.group(1)) if m else ""


_REL = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago")
_UNIT = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
         "month": 2592000}


def posted_at(relative, now=None):
    """'2 hours ago' -> ISO timestamp (UTC), or None if unparseable."""
    m = _REL.search((relative or "").lower())
    if not m:
        return None
    now = now or datetime.now(timezone.utc)
    secs = int(m.group(1)) * _UNIT[m.group(2)]
    return (now - timedelta(seconds=secs)).replace(microsecond=0).isoformat()


def parse_search(page, now=None):
    """Job cards on one search page: [{id, title, company, location, posted_at, ...}]."""
    jobs = []
    for card in re.split(r'(?=<div[^>]+data-entity-urn="urn:li:jobPosting:)', page or "")[1:]:
        m = re.match(r'<div[^>]+data-entity-urn="urn:li:jobPosting:(\d+)"', card)
        if not m:
            continue
        logo = re.search(r'data-delayed-url="(https://media\.licdn\.com/[^"]+)"', card)
        slug = re.search(r'linkedin\.com/company/([^/?"#]+)', card)
        rel = _first(r"<time[^>]*>(.*?)</time>", card)
        jobs.append({
            "id": m.group(1),
            "title": _first(r'<h3 class="base-search-card__title">(.*?)</h3>', card),
            "company": _first(r'<h4 class="base-search-card__subtitle">(.*?)</h4>', card),
            "company_slug": urllib.parse.unquote(slug.group(1)).lower() if slug else "",
            "location": _first(r'class="job-search-card__location">(.*?)</span>', card),
            "salary_text": _first(r'class="job-search-card__salary-info[^"]*">(.*?)</span>', card),
            "posted_at": posted_at(rel, now),
            "logo": html.unescape(logo.group(1)) if logo else "",
        })
    return jobs


def parse_detail(page):
    """Description + criteria from a job detail page ({} when the page is empty)."""
    if not page or "description__text" not in page:
        return {}
    desc = _first(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', page)
    criteria = {
        _text(k).lower(): _text(v)
        for k, v in re.findall(
            r'description__job-criteria-subheader">(.*?)</h3>\s*<span[^>]*>(.*?)</span>',
            page, re.S)
    }
    applicants = _first(r'class="num-applicants__caption[^"]*"[^>]*>(.*?)<', page)
    return {
        "description": desc,
        "seniority": criteria.get("seniority level", ""),
        "employment_type": criteria.get("employment type", ""),
        "industries": criteria.get("industries", ""),
        "applicants": applicants,
        "salary_text": _first(r'class="[^"]*compensation__salary[^"]*"[^>]*>(.*?)<', page),
    }


# ── API ──────────────────────────────────────────────────────────────────────

def search_url(keyword, location, window_sec, levels="", job_types="", start=0):
    q = {"keywords": keyword, "location": location, "f_TPR": f"r{window_sec}",
         "sortBy": "DD", "start": start}
    if levels:
        q["f_E"] = levels
    if job_types:
        q["f_JT"] = job_types
    return f"{BASE}/seeMoreJobPostings/search?{urllib.parse.urlencode(q)}"


def search(client, keyword, location, window_sec, levels="", job_types="",
           max_pages=100, now=None, stop_at=None):
    """All cards for one keyword×location. Returns (jobs, pages_fetched, hit_cap).

    hit_cap is True when max_pages ran out (results were probably cut off) or
    stop_at (a time.monotonic() deadline) was reached.
    """
    out, seen = [], set()
    for page_no in range(max_pages):
        if stop_at and time.monotonic() >= stop_at:
            return out, page_no, True
        body = client.get(search_url(keyword, location, window_sec, levels,
                                     job_types, start=page_no * 10))
        fresh = [c for c in parse_search(body, now) if c["id"] not in seen]
        if not fresh:
            return out, page_no + 1, False
        seen.update(c["id"] for c in fresh)
        out += fresh
    return out, max_pages, True


def job_detail(client, job_id):
    return parse_detail(client.get(f"{BASE}/jobPosting/{job_id}"))


def job_url(job_id):
    return f"https://www.linkedin.com/jobs/view/{job_id}/"
