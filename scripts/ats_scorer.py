#!/usr/bin/env python3
"""
ats_scorer.py — Compute correct ATS-direction scores from LinkedIn Apify data.

The LinkedIn actor matches ALL resume keywords (have + gap) against each JD.
This script splits matchedKeywords into:
  - have_matches: skills the candidate actually possesses
  - gap_matches: skills the JD wants that the candidate LACKS

ATS % = have_matches / (have_matches + gap_matches)

This is "how much of what this JD asks for, do you already have?" — the real
ATS/LinkedIn direction.
"""
import json, csv, sys
from datetime import date

TODAY = date(2026, 5, 30)

# === CANDIDATE SKILL CLASSIFICATION ===
# Skills the candidate HAS (from master.md + corrections)
HAVE_SKILLS = {
    "python", "java", "go", "rust", "typescript", "javascript", "c++",
    "react", "react native", "node.js", "kafka", "redis", "kubernetes", "docker",
    "aws", "postgresql", "mysql", "mongodb", "dynamodb", "microservices",
    "rest", "grpc", "ci/cd", "distributed systems", "sql", "haskell",
    "graphql",
}

# Skills the candidate does NOT have (gap skills added to actor keywords)
GAP_SKILLS = {
    "spring boot", "hibernate", "terraform", "azure", "gcp",
    "angular", "scala", "snowflake", "php", "ruby",
    "elasticsearch", "rabbitmq", "oracle", "maven", "django", ".net",
    "protobuf", "cassandra",
}

def classify(matched_keywords):
    """Split matched keywords into have vs gap."""
    have, gap = [], []
    for kw in (matched_keywords or []):
        kw_lower = kw.lower().strip()
        if kw_lower in HAVE_SKILLS:
            have.append(kw)
        elif kw_lower in GAP_SKILLS:
            gap.append(kw)
        else:
            # Unknown keyword — assume JD-specific, treat as gap
            # (conservative: lowers score if we don't know it)
            gap.append(kw)
    return have, gap

def ats_score(have, gap):
    total = len(have) + len(gap)
    if total == 0:
        return 0
    return round(len(have) / total * 100)

def days_ago(published_at):
    try:
        y, m, d = map(int, str(published_at)[:10].split("-"))
        return (TODAY - date(y, m, d)).days
    except Exception:
        return 999

def main():
    if len(sys.argv) < 2:
        print("Usage: python ats_scorer.py <apify_linkedin_output.json> [--top N]")
        sys.exit(1)

    raw = json.load(open(sys.argv[1]))

    # Handle different JSON shapes: plain array, or wrapper like {"items": [...]}
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        # Try common wrapper keys
        for key in ("items", "data", "results", "jobs", "dataset"):
            if key in raw and isinstance(raw[key], list):
                data = raw[key]
                break
        else:
            # Maybe the dict itself is the only record
            data = [raw]
    else:
        print(f"ERROR: Unexpected JSON root type: {type(raw).__name__}")
        sys.exit(1)

    # Filter out non-dict items (strings, nulls, etc.)
    data = [d for d in data if isinstance(d, dict)]
    if not data:
        print("ERROR: No valid job records found in the JSON file.")
        print(f"  Root type: {type(raw).__name__}")
        if isinstance(raw, list) and raw:
            print(f"  First item type: {type(raw[0]).__name__}")
            print(f"  First item preview: {str(raw[0])[:200]}")
        sys.exit(1)

    print(f"Loaded {len(data)} job records")
    top_n = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else len(data)

    rows = []
    for d in data:
        matched = d.get("matchedKeywords") or d.get("matched_keywords") or []
        have, gap = classify(matched)
        score = ats_score(have, gap)
        age = days_ago(d.get("publishedAt") or d.get("published_at") or "")
        rows.append({
            "ats_pct": score,
            "have_count": len(have),
            "gap_count": len(gap),
            "total_detected": len(have) + len(gap),
            "have_skills": have,
            "gap_skills": gap,
            "title": d.get("jobTitle") or d.get("title") or "",
            "company": d.get("companyName") or d.get("company") or "",
            "location": d.get("location", ""),
            "url": d.get("jobUrl") or d.get("url") or "",
            "posted": (d.get("publishedAt") or d.get("published_at") or "")[:10],
            "age_days": age,
            "contract": d.get("contractType", ""),
            "level": d.get("experienceLevel", ""),
        })

    # Sort: ATS % desc, then have_count desc, then age asc (recent first)
    rows.sort(key=lambda r: (r["ats_pct"], r["have_count"], -r["age_days"]), reverse=True)
    rows = rows[:top_n]

    # === MARKDOWN REPORT ===
    with open("ats_full_report.md", "w") as f:
        f.write("# ATS-Direction Job Match Report\n\n")
        f.write(f"_Total jobs scored: {len(data)} | Showing top {len(rows)}_\n\n")
        f.write("_ATS % = skills you HAVE that this JD mentions ÷ ALL skills this JD mentions "
                "(including gaps like Spring Boot, Hibernate, Angular, etc.)_\n\n")
        f.write("| # | ATS % | Have | Gap | Title | Company | Location | Age | Gaps | Apply |\n")
        f.write("|--:|--:|--:|--:|---|---|---|--:|---|---|\n")
        for i, r in enumerate(rows, 1):
            title = r["title"][:40]
            company = r["company"][:18]
            loc = r["location"].split(",")[0][:15]
            gaps = ", ".join(r["gap_skills"][:4]) or "none ✅"
            age = f"{r['age_days']}d"
            url = r["url"]
            f.write(f"| {i} | {r['ats_pct']}% | {r['have_count']} | {r['gap_count']} | "
                    f"{title} | {company} | {loc} | {age} | {gaps} | [apply]({url}) |\n")

        # Summary section
        f.write(f"\n\n## Summary\n\n")
        perfect = [r for r in rows if r["ats_pct"] == 100]
        high = [r for r in rows if 80 <= r["ats_pct"] < 100]
        good = [r for r in rows if 60 <= r["ats_pct"] < 80]
        f.write(f"- **100% match (all JD skills covered):** {len(perfect)} roles\n")
        f.write(f"- **80-99% match:** {len(high)} roles\n")
        f.write(f"- **60-79% match:** {len(good)} roles\n")

        # Top gaps
        from collections import Counter
        all_gaps = Counter()
        for r in rows:
            for g in r["gap_skills"]:
                all_gaps[g.lower()] += 1
        if all_gaps:
            f.write(f"\n### Most common gaps across top roles:\n\n")
            for skill, count in all_gaps.most_common(10):
                f.write(f"- **{skill}**: blocks {count} roles\n")

    # === CSV ===
    with open("ats_full_report.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "ats_pct", "have_count", "gap_count", "title", "company",
                     "location", "posted", "age_days", "have_skills", "gap_skills", "url"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["ats_pct"], r["have_count"], r["gap_count"],
                         r["title"], r["company"], r["location"], r["posted"],
                         r["age_days"], "; ".join(r["have_skills"]),
                         "; ".join(r["gap_skills"]), r["url"]])

    print(f"Scored {len(data)} jobs → ats_full_report.md + ats_full_report.csv")
    print(f"100% matches: {len(perfect)} | 80%+: {len(high)} | 60%+: {len(good)}")
    if rows:
        print(f"Top: {rows[0]['company']} - {rows[0]['title']} ({rows[0]['ats_pct']}%)")

if __name__ == "__main__":
    main()