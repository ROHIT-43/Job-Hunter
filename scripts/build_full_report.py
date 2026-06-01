#!/usr/bin/env python3
"""build_full_report.py — score every LinkedIn opening, join company-size
verdicts, and emit ONE consolidated report (all openings, ATS-ranked) with a
company-size column and the >500-employee gate applied.

Sort: jobs at companies with >500 employees first (the user's gate), then by
ATS% desc, then company tier, then have-count, then recency. Jobs at <=500 or
unknown-size companies are kept but sunk below the qualifying set and marked.

Usage:
  python scripts/build_full_report.py data/linkedin_normalized.json \
      --profile data/profile.json --sizes data/company_sizes.json \
      --out-dir data/output
"""
import argparse, csv, json, os, re, sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ats  # noqa: E402


def load_have(profile_path):
    prof = json.load(open(profile_path))
    norm = lambda items: [str(s).lower().strip() for s in (items or []) if str(s).strip()]
    have = set(norm(prof.get("skills")))
    for e in prof.get("experience") or []:
        have |= set(norm(e.get("skills")))
    for p in prof.get("projects") or []:
        have |= set(norm(p.get("skills")))
    return prof, sorted(have)


def age_days(posted, today):
    try:
        y, m, d = map(int, str(posted)[:10].split("-"))
        return (today - date(y, m, d)).days
    except Exception:
        return 999


def dedup(jobs):
    seen, out = set(), []
    for j in jobs:
        k = (str(j.get("title", "")).lower(), str(j.get("company", "")).lower())
        if k in seen:
            continue
        seen.add(k); out.append(j)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--sizes", required=True)
    ap.add_argument("--out-dir", default="data/output")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    prof, have = load_have(args.profile)
    idx = ats.build_alias_index(ats.load_dictionary())
    sizes = json.load(open(args.sizes))
    cand_yoe = prof.get("years_experience")

    jobs = []
    for p in args.jobs:
        jobs += [j for j in json.load(open(p)) if isinstance(j, dict)]
    jobs = dedup(jobs)

    rows = []
    for j in jobs:
        s = ats.score_job(j, have, idx)
        tier_label, tier_rank = ats.company_tier(j.get("company", ""), j.get("sector", ""))
        sz = sizes.get(j.get("company", ""), {})
        ge500 = sz.get("ge500", None)
        text = " ".join([j.get("title", ""), " ".join(j.get("tags", []) or []),
                         j.get("description", "") or ""])
        jd_min = ats.extract_min_yoe(text)
        yoe_ok = not (jd_min is not None and cand_yoe is not None and cand_yoe < jd_min)
        rows.append({**j, **s, "tier": tier_label, "tier_rank": tier_rank,
                     "emp": sz.get("emp", "?"), "ge500": ge500,
                     "staffing": sz.get("staffing", False),
                     "jd_min_yoe": jd_min, "yoe_ok": yoe_ok,
                     "yoe_reason": (f"needs {jd_min}y, have {cand_yoe}y"
                                    if not yoe_ok else ""),
                     "age_days": age_days(j.get("posted"), today)})

    # Sort (highest priority first): ATS% match, then T1/T2 tier as tiebreaker,
    # then company size (larger first). Companies with <500 employees are sunk
    # to the very bottom regardless of their ATS%. Unknown-size companies stay
    # in the main group (they are not known to be small).
    def size_num(r):
        nums = [int(x) for x in re.findall(r"\d+", str(r["emp"]).replace(",", ""))]
        return max(nums) if nums else 0

    rows.sort(key=lambda r: (1 if r["yoe_ok"] else 0,          # under-qualified → final sink
                             0 if r["ge500"] is False else 1,  # <500 employees → next-to-last
                             r["ats_pct"],                      # ATS match (primary)
                             r["tier_rank"],                    # T1/T2 tiebreaker
                             size_num(r),                       # company size
                             -r["age_days"]),                   # recency
              reverse=True)

    os.makedirs(args.out_dir, exist_ok=True)
    n_ge500 = sum(1 for r in rows if r["ge500"] is True)
    n_small = sum(1 for r in rows if r["ge500"] is False)
    n_unk = sum(1 for r in rows if r["ge500"] is None)

    # ---- Markdown: full ranked report ----
    L = ["# ATS-ranked LinkedIn report — full list", "",
         f"_Profile: {prof.get('name','candidate')} · source: LinkedIn (past month) · "
         f"{len(rows)} unique openings._  ",
         "_Ranked by: **ATS% match → T1/T2 tier (tiebreaker) → company size**. "
         f"Sinks: companies with **<500 employees** ({n_small}) drop near the bottom, "
         "and **roles above your years-of-experience (⛔)** drop to the very bottom. "
         f"{n_ge500} openings are at >500 employees, {n_unk} unknown size._", "",
         "| # | ATS % | ≥500 | Emp | Tier | Title | Company | Location | Gaps | Age | Link |",
         "|--:|--:|:--:|---|:--:|---|---|---|---|--:|---|"]
    for i, r in enumerate(rows, 1):
        size_mark = {True: "✅", False: "✗", None: "?"}[r["ge500"]]
        if r["staffing"]:
            size_mark += "🧑‍💼"
        if not r["yoe_ok"]:
            gaps = r["yoe_reason"] + " ⛔"
        else:
            gaps = ", ".join(r["gaps"][:4]) or "none ✅"
            if r["low_signal"]:
                gaps += " ⚠️"
        link = f"[apply]({r['url']})" if r.get("url") else ""
        L.append(f"| {i} | {r['ats_pct']}% | {size_mark} | {r['emp']} | {r['tier']} | "
                 f"{str(r['title'])[:44]} | {str(r['company'])[:24]} | "
                 f"{str(r.get('location',''))[:20]} | {gaps} | {r['age_days']}d | {link} |")
    L.append("\n_✅ >500 employees · ✗ ≤500 · ? unknown size · 🧑‍💼 staffing/recruiting "
             "intermediary (the employer differs) · ⚠️ low-signal JD (<3 skills detected) "
             "· ⛔ below the JD's stated minimum years-of-experience. ATS% is an advisory "
             "keyword/skill match, not a prediction of any ATS decision._")
    open(os.path.join(args.out_dir, "ats_full_report.md"), "w").write("\n".join(L) + "\n")

    # ---- CSV ----
    cols = ["rank", "ats_pct", "ge500", "employees", "staffing", "tier",
            "have_count", "gap_count", "yoe_ok", "jd_min_yoe", "title",
            "company", "location", "posted", "age_days", "matches", "gaps", "url"]
    with open(os.path.join(args.out_dir, "ats_full_report.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["ats_pct"],
                        {True: "yes", False: "no", None: "unknown"}[r["ge500"]],
                        r["emp"], int(bool(r["staffing"])), r["tier"],
                        r["have_count"], r["gap_count"], int(bool(r["yoe_ok"])),
                        r["jd_min_yoe"] if r["jd_min_yoe"] is not None else "",
                        r["title"], r["company"], r.get("location", ""),
                        r.get("posted", ""), r["age_days"],
                        "; ".join(r["matches"]), "; ".join(r["gaps"]),
                        r.get("url", "")])

    print(f"wrote {len(rows)} ranked openings -> {args.out_dir}/ats_full_report.md, .csv")
    print(f"  >500 employees: {n_ge500} | <=500: {n_small} | unknown: {n_unk}")


if __name__ == "__main__":
    main()
