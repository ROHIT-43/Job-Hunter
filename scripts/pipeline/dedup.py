#!/usr/bin/env python3
"""
dedup.py — Stable job IDs + persistent seen-jobs history (data/pipeline/seen_jobs.json).

The store is history only: no pipeline filters on it any more (2026-08-31 user
preference). Values may be a status dict or a bare marker (build_queue writes 1).
"""
import json
import os
import re

STORE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "pipeline", "seen_jobs.json"
)

# LinkedIn URLs: /jobs/view/title-slug-4418715226 OR /jobs/view/4418715226
_LI_ID_RE = re.compile(r"[/-](\d{9,})(?:[/?&]|$)")


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
    m = _LI_ID_RE.search(url)
    if m:
        return f"li:{m.group(1)}"
    return f'{job.get("title","").lower()}::{job.get("company","").lower()}'


def mark_seen(jobs, status: str = "fetched", path: str = STORE_PATH) -> None:
    """Record jobs in the history store with the given status."""
    store = _load(path)
    for j in jobs:
        jid = job_id(j)
        entry = store.get(jid)
        if isinstance(entry, dict):
            entry["status"] = status
        else:
            store[jid] = {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "status": status,
                "url": j.get("url") or j.get("link") or "",
                "first_seen": j.get("posted") or "",
            }
    _save(store, path)
