#!/usr/bin/env python3
"""
pre_filter.py — Rule-based pre-filter that eliminates irrelevant jobs before
LLM scoring. Zero token cost. Filters on title keywords, seniority level, and
years-of-experience patterns in the JD text.

Candidate has 3 years of experience → skip anything requiring 7+.
"""
import json
import os
import re

# ── Red-flag companies (user-maintained) ────────────────────────────────────
# Loaded once from data/pipeline/redflag_companies.json. Any company whose name
# matches a pattern (regex substring) or exact entry is dropped before fetch/score.
_REDFLAG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "pipeline", "redflag_companies.json"
)


def _load_redflags():
    try:
        with open(_REDFLAG_PATH) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return [], set()
    patterns = [re.compile(p, re.IGNORECASE) for p in cfg.get("patterns", []) if p]
    exact = {e.strip().lower() for e in cfg.get("exact", []) if e}
    return patterns, exact


_REDFLAG_PATTERNS, _REDFLAG_EXACT = _load_redflags()


def is_redflag_company(company: str) -> bool:
    name = (company or "").strip().lower()
    if not name:
        return False
    if name in _REDFLAG_EXACT:
        return True
    return any(p.search(name) for p in _REDFLAG_PATTERNS)

# ── Title-level kills ────────────────────────────────────────────────────────
BAD_TITLE_TOKENS = {
    "manager", "director", "vp", "vice president", "head of",
    "hr", "human resource", "recruiter", "talent acquisition", "sourcer",
    "scrum master", "product manager", "program manager",
    "cto", "ceo", "coo", "cpo", "chief",
    "president", "executive",
}

# ── Seniority-level kills (from LinkedIn API field) ─────────────────────────
BAD_SENIORITY = {"director", "executive", "c-suite", "c-level"}

# ── YoE regex: "7+ years", "10 years of experience", "12-15 years" → skip ───
_YOE_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:–|-|to)?\s*\d*\s*\+?\s*years?\s*(?:of\s+)?(?:experience|exp\b)",
    re.IGNORECASE,
)
MAX_YOE = 6          # skip if JD requires ≥ 7 years
MIN_EMPLOYEES = 200  # skip companies smaller than this


def is_relevant(job: dict):
    """Return (keep: bool, reason: str).

    reason is empty when keep=True, or a short explanation when keep=False.
    """
    title = (job.get("title") or "").lower()
    desc = (
        job.get("description")
        or job.get("descriptionText")
        or job.get("desc")
        or ""
    ).lower()
    seniority = (
        job.get("seniority") or job.get("seniorityLevel") or ""
    ).lower()

    # 0. Red-flag company kill (user-maintained blocklist)
    if is_redflag_company(job.get("company") or job.get("companyName")):
        return False, "red-flag company"

    # 1. Title kill
    for token in BAD_TITLE_TOKENS:
        if token in title:
            return False, f'title has "{token}"'

    # 2. Seniority kill
    for bad in BAD_SENIORITY:
        if bad in seniority:
            return False, f"seniority={seniority}"

    # 3. Company size kill — skip tiny companies (< 200 employees)
    emp = job.get("companyEmployeesCount")
    if emp is not None:
        try:
            if int(emp) < MIN_EMPLOYEES:
                return False, f"company too small ({emp} employees)"
        except (ValueError, TypeError):
            pass  # unparseable → don't filter

    # 4. YoE kill — only trigger on *minimum* YoE phrasing
    for m in _YOE_RE.finditer(desc):
        yoe = int(m.group(1))
        if yoe > MAX_YOE:
            return False, f"requires {yoe}+ years"

    return True, ""


def filter_jobs(jobs):
    """Split a list of jobs into (kept, dropped).

    Each dropped job gets a '_filter_reason' key added for logging.
    """
    kept, dropped = [], []
    for j in jobs:
        ok, reason = is_relevant(j)
        if ok:
            kept.append(j)
        else:
            j["_filter_reason"] = reason
            dropped.append(j)
    return kept, dropped
