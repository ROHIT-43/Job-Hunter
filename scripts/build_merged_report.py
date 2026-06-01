#!/usr/bin/env python3
"""build_merged_report.py — score the jobId-deduped merged job list (keyword +
department pulls) and emit a single ranked report. Leaves ats_full_report.md
untouched; writes merged_report.md / .csv.

Company size precedence: real companyEmployeesCount (from the dept pull) wins;
otherwise the LLM/agent estimate in company_sizes.json.

Rank (highest priority first): ATS% → T1/T2 tier (tiebreaker) → company size.
Sinks: <500-employee companies drop near the bottom; roles above the
candidate's years-of-experience (⛔) drop to the very bottom.

Usage:
  python scripts/build_merged_report.py data/linkedin_merged.json \
      --profile data/profile.json --sizes data/company_sizes.json \
      --out-dir data/output
"""
import argparse, csv, json, os, re, sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ats  # noqa: E402


def load_have(p):
    prof = json.load(open(p))
    norm = lambda xs: [str(s).lower().strip() for s in (xs or []) if str(s).strip()]
    have = set(norm(prof.get("skills")))
    for e in prof.get("experience") or []:
        have |= set(norm(e.get("skills")))
    for pr in prof.get("projects") or []:
        have |= set(norm(pr.get("skills")))
    return prof, sorted(have)


def age_days(posted, today):
    try:
        y, m, d = map(int, str(posted)[:10].split("-"))
        return (today - date(y, m, d)).days
    except Exception:
        return 999


def resolve_size(job, sizes):
    """(emp_display, ge500, staffing, source) — real headcount beats estimate."""
    ec = job.get("employees_real")
    if isinstance(ec, int):
        return str(ec), (ec > 500), False, "real"
    s = sizes.get(job.get("company", ""), {})
    if s:
        return s.get("emp", "?"), s.get("ge500", None), bool(s.get("staffing")), "est"
    return "?", None, False, "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--sizes", required=True)
    ap.add_argument("--out-dir", default="data/output")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    prof, have = load_have(args.profile)
    idx = ats.build_alias_index(ats.load_dictionary())
    sizes = json.load(open(args.sizes))
    try:
        llm = json.load(open("data/llm_scores.json"))   # jobid -> {score, verdict}
    except Exception:
        llm = {}
    cand_yoe = prof.get("years_experience")
    jobs = [j for j in json.load(open(args.jobs)) if isinstance(j, dict)]

    rows = []
    for j in jobs:
        s = ats.score_job(j, have, idx)
        tier_label, tier_rank = ats.company_tier(j.get("company", ""), j.get("sector", ""))
        emp, ge500, staffing, src = resolve_size(j, sizes)
        text = " ".join([j.get("title", ""), " ".join(j.get("tags", []) or []),
                         j.get("description", "") or ""])
        jd_min = ats.extract_min_yoe(text)
        yoe_ok = not (jd_min is not None and cand_yoe is not None and cand_yoe < jd_min)
        lj = llm.get(str(j.get("id", "")))
        rows.append({**j, **s, "llm": (lj["score"] if lj else None),
                     "llm_v": (lj["verdict"] if lj else ""),
                     "tier": tier_label, "tier_rank": tier_rank,
                     "emp": emp, "ge500": ge500, "staffing": staffing, "size_src": src,
                     "jd_min_yoe": jd_min, "yoe_ok": yoe_ok,
                     "yoe_reason": (f"needs {jd_min}y, have {cand_yoe}y" if not yoe_ok else ""),
                     "age_days": age_days(j.get("posted"), today)})

    def size_num(r):
        nums = [int(x) for x in re.findall(r"\d+", str(r["emp"]).replace(",", ""))]
        return max(nums) if nums else 0

    rows.sort(key=lambda r: (1 if r["llm"] is not None else 0,  # LLM-reviewed roles first...
                             r["llm"] or 0,                      # ...ordered by LLM-weighted score
                             1 if r["yoe_ok"] else 0,           # then under-qualified → sink
                             0 if r["ge500"] is False else 1,   # <500 employees → next-to-last
                             r["ats_pct"],                      # static ATS
                             r["tier_rank"],                    # T1/T2 tiebreaker
                             size_num(r),                       # company size
                             -r["age_days"]),                   # recency
              reverse=True)

    os.makedirs(args.out_dir, exist_ok=True)
    n_ge = sum(1 for r in rows if r["ge500"] is True)
    n_sm = sum(1 for r in rows if r["ge500"] is False)
    n_un = sum(1 for r in rows if r["ge500"] is None)
    n_real = sum(1 for r in rows if r["size_src"] == "real")
    n_t1 = sum(1 for r in rows if r["tier"] == "T1")
    n_t2 = sum(1 for r in rows if r["tier"] == "T2")

    L = ["# ATS-ranked LinkedIn report — MERGED (keyword + department pulls)", "",
         f"_Profile: {prof.get('name','candidate')} · source: LinkedIn (past month) · "
         f"**{len(rows)} unique openings** (deduped by jobId)._  ",
         "_Ordered by: **LLM-weighted match** (recruiter pass — reviewed roles first, "
         "highest first), then **static ATS% → T1/T2 → company size**. "
         "Sinks: **<500-employee** companies and **roles above your years-of-experience "
         "(⛔)** drop lower._  ",
         "_**LLM** column = honest recruiter-weighted score (only for roles reviewed so far); "
         "**ATS %** = static dictionary keyword-coverage (inflated). Trust LLM where present._  ",
         f"_Tiers: {n_t1} T1 · {n_t2} T2. Size: {n_ge} at >500 ({n_real} from real "
         f"LinkedIn headcount, rest estimated) · {n_sm} at ≤500 · {n_un} unknown._", "",
         "| # | LLM | ATS % | ≥500 | Emp | Tier | Title | Company | Location | Gaps | Age | Link |",
         "|--:|--:|--:|:--:|---|:--:|---|---|---|---|--:|---|"]
    for i, r in enumerate(rows, 1):
        mark = {True: "✅", False: "✗", None: "?"}[r["ge500"]]
        if r["staffing"]:
            mark += "🧑‍💼"
        if not r["yoe_ok"]:
            gaps = r["yoe_reason"] + " ⛔"
        else:
            gaps = ", ".join(r["gaps"][:4]) or "none ✅"
            if r["low_signal"]:
                gaps += " ⚠️"
        link = f"[apply]({r['url']})" if r.get("url") else ""
        llmcell = f"**{r['llm']}** {r['llm_v'][:1].upper()}" if r["llm"] is not None else "–"
        L.append(f"| {i} | {llmcell} | {r['ats_pct']}% | {mark} | {r['emp']} | {r['tier']} | "
                 f"{str(r['title'])[:44]} | {str(r['company'])[:24]} | "
                 f"{str(r.get('location',''))[:20]} | {gaps} | {r['age_days']}d | {link} |")
    L.append("\n_✅ >500 employees · ✗ ≤500 · ? unknown · 🧑‍💼 staffing/recruiting "
             "intermediary · ⚠️ low-signal JD (<3 skills) · ⛔ below the JD's stated "
             "minimum years-of-experience. ATS% is an advisory keyword/skill match, "
             "not a prediction of any ATS decision._")
    open(os.path.join(args.out_dir, "merged_report.md"), "w").write("\n".join(L) + "\n")

    cols = ["rank", "llm_weighted", "llm_verdict", "jobid", "ats_pct", "ge500",
            "employees", "size_source", "staffing", "tier", "have_count", "gap_count",
            "yoe_ok", "jd_min_yoe", "title", "company", "location", "posted",
            "age_days", "source", "matches", "gaps", "url"]
    with open(os.path.join(args.out_dir, "merged_report.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["llm"] if r["llm"] is not None else "", r["llm_v"],
                        r.get("id", ""), r["ats_pct"],
                        {True: "yes", False: "no", None: "unknown"}[r["ge500"]],
                        r["emp"], r["size_src"], int(bool(r["staffing"])), r["tier"],
                        r["have_count"], r["gap_count"], int(bool(r["yoe_ok"])),
                        r["jd_min_yoe"] if r["jd_min_yoe"] is not None else "",
                        r["title"], r["company"], r.get("location", ""),
                        r.get("posted", ""), r["age_days"], r.get("source", ""),
                        "; ".join(r["matches"]), "; ".join(r["gaps"]), r.get("url", "")])

    print(f"wrote {len(rows)} ranked openings -> {args.out_dir}/merged_report.md, .csv")
    print(f"  T1={n_t1} T2={n_t2} | >500={n_ge} (real={n_real}) <=500={n_sm} unknown={n_un}")


if __name__ == "__main__":
    main()
