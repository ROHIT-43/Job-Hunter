#!/usr/bin/env python3
"""
Pre-fetch filter — runs AFTER scrape, BEFORE JD fetch.

  python3 scripts/pipeline/filter_jobs.py [--run-dir PATH]

Default run-dir is the current working directory. Typical usage:

  cd data/pipeline/browser_runs/2026-06-30_1200_2h_v1/
  python3 /path/to/scripts/pipeline/filter_jobs.py

Or from the repo root:

  python3 scripts/pipeline/filter_jobs.py \\
      --run-dir data/pipeline/browser_runs/2026-06-30_1200_2h_v1/

Reads:
  <run-dir>/to_score.json           raw scrape output
  candidate_profile.json            (searched upward from run-dir)
  <profile.seen_jobs_file>
  <profile.avoid_companies_file>
  data/pipeline/redflag_companies.json

Writes:
  <run-dir>/to_fetch.json           filtered list → inject as window.__TO_SCORE

Filters applied in funnel order:
  1. seen_jobs dedup        — IDs already processed in any prior run
  2. companies_avoid        — exact name red-flags (simple txt list)
  3. redflag_companies      — regex + exact red-flags (structured JSON)
  4. role_skip_patterns     — SRE/intern/support/embedded/network/security
  5. seniority pre-cap      — Lead/Principal/Staff/Architect/Manager/Head/Chief
                               cap + tier1_bonus < 70 → can NEVER enter queue.
                               NOTE: Senior/Sr is NOT filtered — scores on merit.
  6. walk-in / spam titles  — walk-in, urgent-joiner, bulk-hire, day-drive
  7. specific-title dedup   — collapse exact-dup non-generic titles across companies
                               (staffing bot spam); generic titles ("Software Engineer"
                               etc.) are never collapsed regardless of repeat count.

Suggested additional filters (see code comments for how to add):
  A. Location pre-filter  — keep only preferred cities; `location` is in scrape data.
                            Add preferred_locations list to candidate_profile.json.
  B. staffCount gate      — skip micro-startups (<50 employees). staffCount is only
                            available after JD fetch; consider a post-fetch gate in
                            build_queue.py instead.
  C. Applicant count gate — skip >500 applicants (too stale/competitive). Same issue:
                            applies count only comes from JD fetch.
"""

import argparse
import json
import os
import re
import sys


# Titles so generic that many real companies post them legitimately.
# These are NEVER collapsed in filter #7 even if the exact title repeats.
_GENERIC_TITLE_RE = re.compile(
    r"^(senior\s+|sr\.?\s+|junior\s+|jr\.?\s+)?"
    r"(software\s+engineer(ing)?|backend\s+engineer|"
    r"full[\s-]stack\s+(developer|engineer)|"
    r"software\s+developer|frontend\s+(developer|engineer)|"
    r"devops\s+engineer|cloud\s+engineer|"
    r"data\s+engineer|platform\s+engineer|"
    r"sde[\s-]?[12iii]*|swe|mts|"
    r"react\s+(developer|engineer)|"
    r"java\s+(developer|engineer)|"
    r"python\s+(developer|engineer)|"
    r"node\.?js?\s+(developer|engineer)|"
    r"engineer|developer)$",
    re.I,
)

_WALKIN_RE = re.compile(
    r"\b(walk[\s-]?in|urgent\s+require|immediate\s+joiner|"
    r"day[\s-]drive|bulk\s+hire|mass[\s-]hire|off[\s-]?campus\s+drive)\b",
    re.I,
)



def _parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=None, help="Run directory containing to_score.json (default: cwd)")
    return p.parse_args()


def _find_project_root(start_dir):
    cur = os.path.abspath(start_dir)
    for _ in range(10):
        if os.path.exists(os.path.join(cur, "candidate_profile.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _report(n, label, before, after):
    dropped = before - len(after)
    flag    = "  ←" if dropped > 10 else ""
    print(f"  [{n}] {label:<44} {before:>4} → {len(after):>4}  (-{dropped}){flag}", file=sys.stderr)


def main():
    args    = _parse_args()
    run_dir = os.path.abspath(args.run_dir or os.getcwd())

    in_path  = os.path.join(run_dir, "to_score.json")
    out_path = os.path.join(run_dir, "to_fetch.json")

    if not os.path.exists(in_path):
        print(f"ERROR: {in_path} not found. Run the browser scraper first.", file=sys.stderr)
        sys.exit(1)

    root = _find_project_root(run_dir)
    if not root:
        print("ERROR: candidate_profile.json not found (searched up from run-dir).", file=sys.stderr)
        print("  Copy assets/candidate_profile.example.json to the repo root and fill in your details.", file=sys.stderr)
        sys.exit(1)

    profile      = json.load(open(os.path.join(root, "candidate_profile.json")))
    seen_path    = os.path.join(root, profile.get("seen_jobs_file",      "data/pipeline/seen_jobs.json"))
    avoid_path   = os.path.join(root, profile.get("avoid_companies_file","data/pipeline/companies_avoid.txt"))
    redflag_path = os.path.join(root, "data/pipeline/redflag_companies.json")

    jobs  = json.load(open(in_path))
    total = len(jobs)
    print(f"Raw scrape:  {total} jobs  ({in_path})", file=sys.stderr)

    # ── 1. seen_jobs dedup ────────────────────────────────────────────────────
    seen_ids = set()
    if os.path.exists(seen_path):
        for k in json.load(open(seen_path)):
            m = re.match(r"^li:(.+)$", k)
            seen_ids.add(m.group(1) if m else k)  # li:xxx → strip prefix; google:xxx → keep as-is
    before = len(jobs)
    jobs   = [j for j in jobs if j["id"] not in seen_ids]
    _report(1, "seen_jobs dedup", before, jobs)

    # ── 2. companies_avoid (exact name) ──────────────────────────────────────
    avoid_exact = set()
    if os.path.exists(avoid_path):
        with open(avoid_path) as f:
            avoid_exact = {l.strip().lower() for l in f if l.strip()}
    before = len(jobs)
    jobs   = [j for j in jobs if j.get("company", "").lower() not in avoid_exact]
    _report(2, "companies_avoid (exact)", before, jobs)

    # ── 3. redflag_companies (patterns + exact) ───────────────────────────────
    rf_pat   = re.compile(r"(?!)")
    rf_exact = set()
    if os.path.exists(redflag_path):
        rf = json.load(open(redflag_path))
        pats = rf.get("patterns", [])
        if pats:
            rf_pat = re.compile("|".join(pats), re.I)
        rf_exact = {e.lower() for e in rf.get("exact", [])}
    before = len(jobs)
    jobs   = [
        j for j in jobs
        if j.get("company", "").lower() not in rf_exact
        and not rf_pat.search(j.get("company", ""))
    ]
    _report(3, "redflag_companies (pattern+exact)", before, jobs)

    # ── 4. role_skip_patterns ─────────────────────────────────────────────────
    role_pats = profile.get("role_skip_patterns", [])
    ROLE_SKIP = re.compile("|".join(role_pats), re.I) if role_pats else re.compile(r"(?!)")
    before = len(jobs)
    jobs   = [j for j in jobs if not ROLE_SKIP.search(j.get("title", ""))]
    _report(4, "role_skip_patterns", before, jobs)

    # ── 5. seniority pre-cap ─────────────────────────────────────────────────
    # Only pre-filter when seniority_cap + tier1_bonus < 70 (queue gate).
    # Senior/Sr is NOT in the cap pattern and is never filtered here.
    cap   = profile.get("seniority_cap", 55)
    bonus = profile.get("tier1_bonus", 8)
    if cap + bonus < 70:
        cap_str = profile.get(
            "seniority_cap_pattern",
            r"\b(lead|principal|staff|architect|director|manager|head|chief)\b",
        )
        SENIORITY_CAP = re.compile(cap_str, re.I)
        before = len(jobs)
        jobs   = [j for j in jobs if not SENIORITY_CAP.search(j.get("title", ""))]
        _report(5, f"seniority pre-cap (cap={cap}+bonus={bonus}<70)", before, jobs)
    else:
        print(f"  [5] seniority pre-cap: SKIPPED (cap+bonus={cap+bonus}≥70)", file=sys.stderr)

    # ── 6. walk-in / spam title keywords ─────────────────────────────────────
    before = len(jobs)
    jobs   = [j for j in jobs if not _WALKIN_RE.search(j.get("title", ""))]
    _report(6, "walk-in / spam title keywords", before, jobs)

    # ── 7. specific-title dedup (staffing bot spam collapse) ──────────────────
    before      = len(jobs)
    seen_titles = set()
    filtered    = []
    for j in jobs:
        t = (j.get("title") or "").strip().lower()
        if _GENERIC_TITLE_RE.match(t):
            filtered.append(j)
        elif t not in seen_titles:
            seen_titles.add(t)
            filtered.append(j)
    jobs = filtered
    _report(7, "specific-title dedup (spam collapse)", before, jobs)

    # ── Summary ───────────────────────────────────────────────────────────────
    saved = total - len(jobs)
    pct   = saved * 100 // total if total else 0
    print(
        f"\nFunnel: {total} → {len(jobs)}  ({saved} filtered, {pct}% less JD fetch + Ollama work)",
        file=sys.stderr,
    )

    with open(out_path, "w") as f:
        json.dump(jobs, f)
    print(f"Written → {out_path}", file=sys.stderr)
    print(
        "\nNext: inject to_fetch.json as window.__TO_SCORE in the LinkedIn tab,\n"
        "      then paste scripts/browser/fetch_jds_browser.js to fetch full JDs.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
