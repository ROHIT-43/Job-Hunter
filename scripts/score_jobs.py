#!/usr/bin/env python3
"""score_jobs.py — unified scorer. Loads one or more normalized job JSON files,
merges + dedups on (title, company), scores each via the master-dictionary ATS,
orders by ATS% then company tier then have-count then recency, and writes a
Markdown report + CSV.

Usage:
  python scripts/score_jobs.py data/jobs.json [data/apify_jobs.json] \
      --profile data/profile.json --top 50 --out-dir data/output
"""
import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ats  # noqa: E402

DEFAULT_OUT_DIR = os.path.join("data", "output")


def load_have_skills(profile_path):
    with open(profile_path) as f:
        prof = json.load(f)

    def norm(items):
        return [str(s).lower().strip() for s in (items or []) if str(s).strip()]

    have = set(norm(prof.get("skills")))
    for exp in (prof.get("experience") or []):
        have |= set(norm(exp.get("skills")))
    for proj in (prof.get("projects") or []):
        have |= set(norm(proj.get("skills")))
    return prof, sorted(have)


def load_jobs(paths):
    jobs = []
    for p in paths:
        with open(p) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key in ("items", "data", "results", "jobs"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                raw = [raw]
        jobs += [j for j in raw if isinstance(j, dict)]
    return jobs


def dedup(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (str(j.get("title", "")).lower(),
               str(j.get("company", "")).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def age_days(posted, today):
    try:
        y, m, d = map(int, str(posted)[:10].split("-"))
        return (today - date(y, m, d)).days
    except Exception:
        return 999


def job_key(j):
    """Stable identifier used to link a job to its LLM labels. Prefers the
    normalized `id`; falls back to title::company (matches the dedup key)."""
    return j.get("id") or f'{j.get("title", "")}::{j.get("company", "")}'


def emit_shortlist(rows, have, n, path, w_req, w_pref):
    """Write the top-n dictionary-ranked jobs for the LLM weighting step.

    The skill reads this, labels each job's JD skills required/preferred, and
    writes llm_labels.json keyed by the same `key`."""
    payload = {
        "have_skills": have,
        "weights": {"w_req": w_req, "w_pref": w_pref},
        "jobs": [{
            "key": job_key(r),
            "title": r.get("title", ""),
            "company": r.get("company", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "dict_ats": r["ats_pct"],
        } for r in rows[:n]],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def apply_yoe_gate(rows, cand_yoe):
    """Disqualify jobs whose stated minimum YoE exceeds the candidate's.

    Zeroes the score, marks yoe_ok=False, and records a reason. No-op when the
    candidate's YoE or the JD's minimum is unknown."""
    if cand_yoe is None:
        return rows
    for r in rows:
        jd_min = r.get("jd_min_yoe")
        if jd_min is not None and cand_yoe < jd_min:
            r["yoe_ok"] = False
            r["ats_pct"] = 0
            r["yoe_reason"] = f"needs {jd_min}y, have {cand_yoe}y"
    return rows


def apply_llm_labels(rows, labels, have, idx, w_req, w_pref):
    """Override ATS% with the LLM-weighted score for jobs that have labels."""
    for r in rows:
        lab = labels.get(job_key(r))
        if not lab:
            continue
        w = ats.weighted_score(lab.get("required", []),
                               lab.get("preferred", []), have, idx,
                               w_req, w_pref)
        r["ats_pct"] = w["ats_pct"]
        r["matches"] = w["matched_required"] + w["matched_preferred"]
        r["gaps"] = w["missing_required"]  # missing-required = the blockers
        r["have_count"] = len(w["matched_required"]) + len(w["matched_preferred"])
        r["gap_count"] = len(w["missing_required"])
        r["low_signal"] = False  # an LLM-labeled job is never low-signal
        r["enriched"] = True
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jobs", nargs="+", help="one or more normalized job JSON files")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--emit-shortlist", default="",
                    help="Pass 1: write the top jobs here for the LLM step")
    ap.add_argument("--shortlist-n", type=int, default=25,
                    help="how many jobs to put in the shortlist")
    ap.add_argument("--llm-labels", default="",
                    help="Pass 3: JSON of {job_key: {required, preferred}} to "
                         "re-score the labeled jobs with weighted coverage")
    ap.add_argument("--w-req", type=float, default=1.0,
                    help="weight for required JD skills (default 1.0)")
    ap.add_argument("--w-pref", type=float, default=0.3,
                    help="weight for preferred JD skills (default 0.3)")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    prof, have = load_have_skills(args.profile)
    idx = ats.build_alias_index(ats.load_dictionary())

    cand_yoe = prof.get("years_experience")

    jobs = dedup(load_jobs(args.jobs))
    rows = []
    for j in jobs:
        s = ats.score_job(j, have, idx)
        tier_label, tier_rank = ats.company_tier(
            j.get("company", ""), j.get("sector", ""))
        text = " ".join([j.get("title", ""),
                         " ".join(j.get("tags", []) or []),
                         j.get("description", "") or ""])
        jd_min_yoe = ats.extract_min_yoe(text)
        rows.append({**j, **s, "tier": tier_label, "tier_rank": tier_rank,
                     "enriched": False, "jd_min_yoe": jd_min_yoe,
                     "yoe_ok": True,
                     "age_days": age_days(j.get("posted"), today)})

    # Pass 3: re-score LLM-labeled jobs before sorting so they rank on the
    # weighted number.
    if args.llm_labels:
        with open(args.llm_labels) as f:
            labels = json.load(f)
        apply_llm_labels(rows, labels, have, idx, args.w_req, args.w_pref)

    # Strict YoE gate: a candidate below the JD's stated minimum is
    # disqualified — score zeroed and sunk below all qualifying roles, with the
    # reason kept visible. Skipped when either YoE is unknown (no constraint).
    apply_yoe_gate(rows, cand_yoe)

    # Qualifying first; then non-low-signal; then ATS% desc, tier, have, newest.
    rows.sort(key=lambda r: (1 if r["yoe_ok"] else 0,
                             0 if r["low_signal"] else 1, r["ats_pct"],
                             r["tier_rank"], r["have_count"], -r["age_days"]),
              reverse=True)
    rows = rows[:args.top]

    os.makedirs(args.out_dir, exist_ok=True)
    write_md(rows, prof, os.path.join(args.out_dir, "report.md"), len(jobs))
    write_csv(rows, os.path.join(args.out_dir, "jobs_ranked.csv"))
    if args.emit_shortlist:
        emit_shortlist(rows, have, args.shortlist_n, args.emit_shortlist,
                       args.w_req, args.w_pref)
        print(f"shortlist ({min(args.shortlist_n, len(rows))} jobs) -> "
              f"{args.emit_shortlist}")
    print(f"scored {len(jobs)} jobs -> {args.out_dir}/report.md, jobs_ranked.csv")
    if rows:
        t = rows[0]
        mark = " ✨" if t.get("enriched") else ""
        print(f"top: {t['title']} @ {t['company']} "
              f"({t['ats_pct']}%, {t['tier']}){mark}")


def write_md(rows, prof, path, total):
    L = ["# ATS-ranked job report", ""]
    L.append(f"_Profile: {prof.get('name', 'candidate')} — "
             f"{total} jobs scored, showing {len(rows)}._")
    L.append("")
    L.append("| # | ATS % | Tier | Dept | Title | Company | Location | "
             "Remote | Visa | Gaps | Age | Link |")
    L.append("|--:|--:|:--:|---|---|---|---|:-:|:-:|---|--:|---|")
    for i, r in enumerate(rows, 1):
        rem = "✓" if r.get("remote") else ""
        visa = {True: "✓", False: "✗"}.get(r.get("visa_sponsorship"), "?")
        dept = ",".join(sorted(r.get("departments", []))) or "-"
        if not r.get("yoe_ok", True):
            gaps = r.get("yoe_reason", "below min YoE")
            flag = " ⛔"
        else:
            gaps = ", ".join(r["gaps"][:4]) or "none ✅"
            flag = (" ✨" if r.get("enriched")
                    else (" ⚠️" if r["low_signal"] else ""))
        link = f"[apply]({r['url']})" if r.get("url") else ""
        L.append(f"| {i} | {r['ats_pct']}%{flag} | {r['tier']} | {dept} | "
                 f"{str(r['title'])[:42]} | {str(r['company'])[:20]} | "
                 f"{str(r.get('location',''))[:18]} | {rem} | {visa} | "
                 f"{gaps} | {r['age_days']}d | {link} |")
    L.append("\n_⛔ = disqualified: candidate below the JD's minimum "
             "years-of-experience (strict gate); score zeroed and sunk to the "
             "bottom. ⚠️ = low-signal JD (fewer than 3 detected skills). "
             "✨ = LLM-weighted (required vs preferred); Gaps shows missing "
             "**required** skills. This is an advisory keyword/skill match, not "
             "a prediction of any ATS decision._")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def write_csv(rows, path):
    cols = ["rank", "ats_pct", "yoe_ok", "jd_min_yoe", "enriched",
            "low_signal", "tier", "have_count", "gap_count", "title",
            "company", "location", "remote", "visa_sponsorship", "posted",
            "age_days", "matches", "gaps", "url"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["ats_pct"], int(bool(r.get("yoe_ok", True))),
                        r.get("jd_min_yoe") if r.get("jd_min_yoe") is not None
                        else "", int(bool(r.get("enriched"))),
                        int(r["low_signal"]), r["tier"],
                        r["have_count"], r["gap_count"], r["title"],
                        r["company"], r.get("location", ""), r.get("remote"),
                        r.get("visa_sponsorship"), r.get("posted", ""),
                        r["age_days"], "; ".join(r["matches"]),
                        "; ".join(r["gaps"]), r.get("url", "")])


if __name__ == "__main__":
    main()
