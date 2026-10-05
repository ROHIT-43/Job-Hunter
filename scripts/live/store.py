"""store.py — The published job list (site/data/jobs.json): load, merge, dedup, expire.

Two duplicate checks:
  1. LinkedIn job ID.
  2. normalized title + company + city — catches a reposted job under a new ID.
`skipped` remembers IDs already judged too senior (by posting time) so their
detail page is not fetched again on the next overlapping run.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone


def empty_state():
    return {"generated_at": None, "last_scrape_at": None, "jobs": [], "skipped": {}}


def load(path=None, url=None, timeout=20):
    """Previous state from a local file, else the published site, else empty."""
    if path and os.path.exists(path):
        with open(path) as f:
            return _normalize(json.load(f))
    if url:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return _normalize(json.loads(r.read()))
        except Exception:  # noqa: BLE001 — first run / site down: start fresh
            pass
    return empty_state()


def _normalize(state):
    base = empty_state()
    base.update(state if isinstance(state, dict) else {})
    return base


def save(state, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def repost_key(job):
    city = (job.get("location") or "").split(",")[0]
    return f"{_norm(job.get('title'))}|{_norm(job.get('company'))}|{_norm(city)}"


def _ts(iso):
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def known(state):
    """(ids, repost_keys) already in the state — new cards matching either are skipped."""
    ids = {j["id"] for j in state["jobs"]} | set(state["skipped"])
    keys = {repost_key(j) for j in state["jobs"]}
    return ids, keys


def add(state, job, index=None):
    """Insert a job unless its ID or repost key is already present. Returns True if added.

    Pass index=known(state) when adding many jobs; it is updated in place.
    """
    ids, keys = index if index is not None else known(state)
    key = repost_key(job)
    if job["id"] in ids or key in keys:
        return False
    state["jobs"].append(job)
    ids.add(job["id"])
    keys.add(key)
    return True


def expire(state, max_age_hours=24, now=None):
    """Drop jobs (and skipped IDs) posted more than max_age_hours ago. Returns count dropped."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    before = len(state["jobs"])
    state["jobs"] = [j for j in state["jobs"]
                     if (_ts(j.get("posted_at") or j.get("first_seen_at")) or now) >= cutoff]
    state["skipped"] = {k: v for k, v in state["skipped"].items()
                        if (_ts(v) or now) >= cutoff}
    state["jobs"].sort(key=lambda j: j.get("posted_at") or "", reverse=True)
    return before - len(state["jobs"])
