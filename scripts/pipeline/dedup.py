#!/usr/bin/env python3
"""
dedup.py — Persistent seen-jobs store backed by data/pipeline/seen_jobs.json.

Tracks every job ID we've ever fetched so each 4-hour pipeline run only
processes genuinely new postings. Also records apply status per job.
"""
import json
import os

STORE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "pipeline", "seen_jobs.json"
)


def _load(path: str = STORE_PATH) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save(store: dict, path: str = STORE_PATH) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(store, f, indent=2)


def job_id(job: dict) -> str:
    """Stable ID — prefer LinkedIn job ID extracted from URL, else title::company."""
    url = job.get("url") or job.get("link") or ""
    # LinkedIn URLs contain the numeric job ID: /jobs/view/4417768801
    import re
    # LinkedIn URLs: /jobs/view/title-slug-4418715226 OR /jobs/view/4418715226
    m = re.search(r"[/-](\d{9,})(?:[?&]|$)", url)
    if m:
        return f"li:{m.group(1)}"
    return f'{job.get("title","").lower()}::{job.get("company","").lower()}'


def filter_new(jobs, path: str = STORE_PATH):
    """Return only jobs not yet in the store. Does NOT save — call mark_seen after."""
    store = _load(path)
    return [j for j in jobs if job_id(j) not in store]


def mark_seen(jobs, status: str = "fetched", path: str = STORE_PATH) -> None:
    """Add jobs to the store with the given status."""
    store = _load(path)
    for j in jobs:
        jid = job_id(j)
        if jid not in store:
            store[jid] = {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "status": status,
                "url": j.get("url") or j.get("link") or "",
                "first_seen": j.get("posted") or "",
            }
        else:
            store[jid]["status"] = status
    _save(store, path)


def update_status(job_id_str: str, status: str, path: str = STORE_PATH) -> None:
    """Update status for a single job (e.g., 'applied', 'skipped', 'tailored')."""
    store = _load(path)
    if job_id_str in store:
        store[job_id_str]["status"] = status
        _save(store, path)


def stats(path: str = STORE_PATH) -> dict:
    store = _load(path)
    from collections import Counter
    counts = Counter(v["status"] for v in store.values())
    return {"total": len(store), **dict(counts)}
