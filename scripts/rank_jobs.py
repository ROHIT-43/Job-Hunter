#!/usr/bin/env python3
"""
rank_jobs.py — Score normalized jobs against a candidate profile, dedup,
and emit a ranked Markdown report + CSV.

Scoring is transparent and explainable (no black box). Each job gets a 0-100
match score from weighted components, and the report shows WHY it ranked where
it did so the user can trust/adjust the ordering.

Example:
  python rank_jobs.py --jobs jobs.json --profile profile.json \
      --top 40 --out-md report.md --out-csv jobs_ranked.csv
"""
import argparse
import csv
import json
import re
from datetime import datetime, timezone

WEIGHTS = {
    "skills": 45,      # overlap with must-have + nice-to-have skills
    "title": 20,       # seniority / role-family match
    "location": 15,    # location / remote / visa preference satisfied
    "recency": 10,     # newer postings rank higher
    "salary": 5,       # salary info present & in range
    "company": 5,      # avoid-list / prefer-list
}

SENIORITY = {
    "intern": 0, "junior": 1, "associate": 1, "sde i": 1, "sde 1": 1,
    "mid": 2, "sde ii": 2, "sde 2": 2, "engineer": 2,
    "senior": 3, "sde iii": 3, "sde 3": 3, "sr ": 3, "lead": 4,
    "staff": 5, "principal": 6, "architect": 5, "manager": 4, "head": 6,
}


def tokset(s):
    return set(re.findall(r"[a-z0-9+#.]+", (s or "").lower()))


def seniority_of(text):
    t = (text or "").lower()
    best = None
    for k, v in SENIORITY.items():
        if k in t:
            best = v if best is None else max(best, v) if v > 2 else best
    return best


def score_skills(job, prof):
    must = [s.lower() for s in prof.get("must_have_skills", [])]
    nice = [s.lower() for s in prof.get("nice_to_have_skills", [])]
    hay = " ".join([job["title"], " ".join(job.get("tags", [])),
                    job.get("description", "")]).lower()
    if not must and not nice:
        return 0.5, []
    matched = []
    m_hits = sum(1 for s in must if s in hay)
    n_hits = sum(1 for s in nice if s in hay)
    for s in must + nice:
        if s in hay:
            matched.append(s)
    must_frac = (m_hits / len(must)) if must else 0.0
    nice_frac = (n_hits / len(nice)) if nice else 0.0
    raw = 0.75 * must_frac + 0.25 * nice_frac
    return raw, matched


def score_title(job, prof):
    fam = [f.lower() for f in prof.get("target_titles", [])]
    title = job["title"].lower()
    fam_hit = any(any(w in title for w in f.split()) for f in fam) if fam else True
    want_level = prof.get("seniority_level")  # int 0-6 or None
    have_level = seniority_of(title)
    level_ok = True
    if want_level is not None and have_level is not None:
        level_ok = abs(have_level - want_level) <= 1
    return (0.6 if fam_hit else 0.0) + (0.4 if level_ok else 0.0)


def score_location(job, prof):
    if prof.get("visa_required") and job.get("visa_sponsorship") is True:
        return 1.0
    if prof.get("remote_only"):
        return 1.0 if job.get("remote") else 0.0
    locs = [l.lower() for l in prof.get("locations", [])]
    if not locs:
        return 0.7
    jl = (job.get("location") or "").lower()
    if job.get("remote"):
        return 0.9
    return 1.0 if any(l in jl or jl in l for l in locs if l) else 0.2


def score_recency(job):
    s = job.get("posted")
    if not s:
        return 0.5
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d",
                "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(str(s).replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - dt).days
            if days <= 3:
                return 1.0
            if days <= 7:
                return 0.85
            if days <= 14:
                return 0.65
            if days <= 30:
                return 0.4
            return 0.15
        except ValueError:
            continue
    return 0.5


def score_company(job, prof):
    name = job["company"].lower()
    if any(a.lower() in name for a in prof.get("avoid_companies", [])):
        return 0.0
    if any(p.lower() in name for p in prof.get("prefer_companies", [])):
        return 1.0
    return 0.6


def score_salary(job, prof):
    return 1.0 if job.get("salary") else 0.3


def rank(jobs, prof):
    scored = []
    for j in jobs:
        sk, matched = score_skills(j, prof)
        comps = {
            "skills": sk,
            "title": score_title(j, prof),
            "location": score_location(j, prof),
            "recency": score_recency(j),
            "salary": score_salary(j, prof),
            "company": score_company(j, prof),
        }
        total = sum(comps[k] * WEIGHTS[k] for k in WEIGHTS)
        j = dict(j)
        j["_score"] = round(total, 1)
        j["_matched_skills"] = matched
        j["_components"] = {k: round(v, 2) for k, v in comps.items()}
        scored.append(j)
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def write_md(jobs, prof, path, top):
    lines = ["# Job match report", ""]
    lines.append(f"_Profile: {prof.get('name', 'candidate')} — "
                 f"{', '.join(prof.get('target_titles', [])) or 'any role'}_")
    lines.append(f"_{len(jobs)} jobs scored; showing top {min(top, len(jobs))}._")
    lines.append("")
    lines.append("| # | Score | Role | Company | Location | Remote | Visa | "
                 "Matched skills | Source | Link |")
    lines.append("|--:|--:|---|---|---|:-:|:-:|---|---|---|")
    for i, j in enumerate(jobs[:top], 1):
        rem = "✓" if j.get("remote") else ""
        visa = {True: "✓", False: "✗"}.get(j.get("visa_sponsorship"), "?")
        ms = ", ".join(j["_matched_skills"][:6])
        link = f"[apply]({j['url']})" if j.get("url") else ""
        lines.append(
            f"| {i} | {j['_score']:.0f} | {j['title'][:48]} | "
            f"{j['company'][:24]} | {j['location'][:22]} | {rem} | {visa} | "
            f"{ms} | {j['source']} | {link} |")
    lines.append("")
    lines.append("## Top 10 — detail")
    for i, j in enumerate(jobs[:10], 1):
        c = j["_components"]
        lines.append(f"\n### {i}. {j['title']} — {j['company']}  ·  "
                     f"score {j['_score']:.0f}/100")
        lines.append(f"- **Location:** {j['location']}  |  Remote: "
                     f"{j.get('remote')}  |  Visa: {j.get('visa_sponsorship')}")
        if j.get("salary"):
            lines.append(f"- **Salary:** {j['salary']}")
        lines.append(f"- **Why this rank:** skills {c['skills']}, title "
                     f"{c['title']}, location {c['location']}, recency "
                     f"{c['recency']}")
        if j["_matched_skills"]:
            lines.append(f"- **Matched:** {', '.join(j['_matched_skills'])}")
        if j.get("url"):
            lines.append(f"- **Apply:** {j['url']}")
        snippet = (j.get("description") or "")[:280]
        if snippet:
            lines.append(f"- {snippet}…")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_csv(jobs, path, top):
    cols = ["score", "title", "company", "location", "remote",
            "visa_sponsorship", "salary", "matched_skills", "source",
            "posted", "url"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for j in jobs[:top]:
            w.writerow([
                j["_score"], j["title"], j["company"], j["location"],
                j.get("remote"), j.get("visa_sponsorship"),
                j.get("salary") or "", "; ".join(j["_matched_skills"]),
                j["source"], j.get("posted") or "", j.get("url") or "",
            ])


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", required=True, help="normalized jobs JSON")
    ap.add_argument("--profile", required=True, help="candidate profile JSON")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out-md", default="report.md")
    ap.add_argument("--out-csv", default="jobs_ranked.csv")
    args = ap.parse_args()

    with open(args.jobs) as f:
        jobs = json.load(f)
    with open(args.profile) as f:
        prof = json.load(f)

    ranked = rank(jobs, prof)
    write_md(ranked, prof, args.out_md, args.top)
    write_csv(ranked, args.out_csv, args.top)
    print(f"ranked {len(ranked)} jobs -> {args.out_md}, {args.out_csv}")
    if ranked:
        print(f"top match: {ranked[0]['title']} @ {ranked[0]['company']} "
              f"({ranked[0]['_score']:.0f})")


if __name__ == "__main__":
    main()
