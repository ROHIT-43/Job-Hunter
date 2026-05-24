#!/usr/bin/env python3
"""
ats_scorer.py — Compute correct ATS-direction scores from LinkedIn Apify data,
and order results by ATS match first, then by how renowned the company is.

The LinkedIn actor matches ALL resume keywords (have + gap) against each JD.
This script splits matchedKeywords into:
  - have_matches: skills the candidate actually possesses
  - gap_matches: skills the JD wants that the candidate LACKS

ATS % = have_matches / (have_matches + gap_matches)

COMPANY TIERS (ordering tiebreaker)
-----------------------------------
The LinkedIn JSON has companyName / companyId / sector but NO employee or
developer count, so prestige and "how big is the eng org" cannot be read from
the data. We approximate it with curated, in-file lists you can extend:

  Tier 1 (T1)  most renowned big tech          Google, Apple, Microsoft, ...
  Tier 2 (T2)  renowned startups / unicorns     Razorpay, Swiggy, Stripe, ...
  neutral (·)  everything we don't recognise
  red flag (!) likely <100-dev shop             staffing / consultancy / etc.

Sort key (all descending): ats_pct -> tier_rank -> have_count -> recency.
ATS match stays primary; tier only breaks ties between equal-ATS roles.
"""
import json, csv, sys
from datetime import date

TODAY = date(2026, 5, 30)

# === CANDIDATE SKILL CLASSIFICATION ===
HAVE_SKILLS = {
    "python", "java", "go", "rust", "typescript", "javascript", "c++",
    "react", "react native", "node.js", "kafka", "redis", "kubernetes", "docker",
    "aws", "postgresql", "mysql", "mongodb", "dynamodb", "microservices",
    "rest", "grpc", "ci/cd", "distributed systems", "sql", "haskell",
    "graphql",
}
GAP_SKILLS = {
    "spring boot", "hibernate", "terraform", "azure", "gcp",
    "angular", "scala", "snowflake", "php", "ruby",
    "elasticsearch", "rabbitmq", "oracle", "maven", "django", ".net",
    "protobuf", "cassandra",
}

# === COMPANY TIERS ==========================================================
TIER1_NAMES = {
    "google", "alphabet", "apple", "microsoft", "amazon", "aws",
    "meta", "facebook", "instagram", "netflix", "nvidia", "adobe",
    "salesforce", "oracle", "ibm", "intel", "cisco", "sap", "qualcomm",
    "vmware", "dell", "hp ", "hewlett", "uber", "airbnb", "paypal",
    "linkedin", "ebay", "twitter", "x corp", "tesla", "bloomberg",
    "goldman sachs", "morgan stanley", "jpmorgan", "j.p. morgan",
    "walmart global tech", "walmart labs", "atlassian", "servicenow",
    "workday", "intuit", "broadcom", "samsung", "sony",
    "spotify", "twilio", "datadog", "mongodb inc", "red hat", "github",
}
TIER2_NAMES = {
    "razorpay", "swiggy", "zomato", "zerodha", "cred", "postman",
    "flipkart", "phonepe", "paytm", "freshworks", "groww", "meesho",
    "dream11", "browserstack", "nykaa", "unacademy", "byju", "ola",
    "navi", "slice", "jupiter", "urban company", "sharechat", "delhivery",
    "polygon", "innovaccer", "gupshup", "chargebee", "hasura", "juspay",
    "rapido", "porter", "moengage", "whatfix", "darwinbox", "zeta",
    "setu", "m2p", "khatabook", "spinny", "cars24", "licious",
    "physicswallah", "vedantu", "upstox", "smallcase",
    "stripe", "databricks", "snowflake", "gitlab", "hashicorp",
    "confluent", "elastic", "cloudflare", "figma", "notion", "canva",
    "discord", "instacart", "doordash", "robinhood", "coinbase",
    "plaid", "brex", "ramp", "vercel", "supabase", "render", "fly.io",
}
# Large orgs that are NOT prestige T1/T2 but are definitely >100 devs — keep
# them out of the red-flag bucket even though name/sector trips a pattern.
KNOWN_LARGE_NAMES = {
    "tata consultancy", "tcs", "infosys", "wipro", "hcl", "cognizant",
    "tech mahindra", "ltimindtree", "lti", "mindtree", "mphasis", "coforge",
    "persistent", "birlasoft", "hexaware", "zensar", "cyient", "nagarro",
    "mastek", "sonata", "happiest minds", "kpit", "l&t technology",
    "accenture", "capgemini", "deloitte", "dxc",
    "epam", "globallogic", "ust", "publicis sapient", "thoughtworks",
    "virtusa", "endava", "ey", "pwc", "kpmg", "genpact", "infosys bpm",
    "hackerrank", "hackerearth", "zoho",
}
RED_FLAG_NAMES = set()
RED_FLAG_PATTERNS = (
    "staffing", "staff solutions", "consultanc", "consultants",
    "recruit", "hiring", "manpower", "placement", "talent solutions",
    "hr services", "hr solutions", "outsourc", "resourcing",
    "it services pvt", "global services", "infotech solutions",
    "software solutions", "technologies pvt ltd", "tech solutions",
    "services pvt ltd", "ventures pvt",
)
RED_FLAG_SECTORS = ("staffing", "recruiting", "outsourcing")

TIER_RANK = {"T1": 3, "T2": 2, "neutral": 1, "redflag": 0}
TIER_GLYPH = {"T1": "T1", "T2": "T2", "neutral": "·", "redflag": "⚠️"}


def _hit(name, names):
    return any(n in name for n in names)


def company_tier(company_name, sector=""):
    name = (company_name or "").lower().strip()
    sect = (sector or "").lower()
    if not name:
        return "neutral", TIER_RANK["neutral"]
    if _hit(name, TIER1_NAMES):
        return "T1", TIER_RANK["T1"]
    if _hit(name, TIER2_NAMES):
        return "T2", TIER_RANK["T2"]
    if _hit(name, KNOWN_LARGE_NAMES):
        return "neutral", TIER_RANK["neutral"]
    if (name in RED_FLAG_NAMES
            or _hit(name, RED_FLAG_PATTERNS)
            or _hit(sect, RED_FLAG_SECTORS)):
        return "redflag", TIER_RANK["redflag"]
    return "neutral", TIER_RANK["neutral"]


def classify(matched_keywords):
    have, gap = [], []
    for kw in (matched_keywords or []):
        kw_lower = kw.lower().strip()
        if kw_lower in HAVE_SKILLS:
            have.append(kw)
        elif kw_lower in GAP_SKILLS:
            gap.append(kw)
        else:
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
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        for key in ("items", "data", "results", "jobs", "dataset"):
            if key in raw and isinstance(raw[key], list):
                data = raw[key]
                break
        else:
            data = [raw]
    else:
        print(f"ERROR: Unexpected JSON root type: {type(raw).__name__}")
        sys.exit(1)

    data = [d for d in data if isinstance(d, dict)]
    if not data:
        print("ERROR: No valid job records found in the JSON file.")
        sys.exit(1)

    print(f"Loaded {len(data)} job records")
    top_n = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else len(data)

    rows = []
    for d in data:
        matched = d.get("matchedKeywords") or d.get("matched_keywords") or []
        have, gap = classify(matched)
        score = ats_score(have, gap)
        age = days_ago(d.get("publishedAt") or d.get("published_at") or "")
        company = d.get("companyName") or d.get("company") or ""
        sector = d.get("sector", "")
        tier_label, tier_rank = company_tier(company, sector)
        rows.append({
            "ats_pct": score,
            "have_count": len(have),
            "gap_count": len(gap),
            "have_skills": have,
            "gap_skills": gap,
            "title": d.get("jobTitle") or d.get("title") or "",
            "company": company,
            "sector": sector,
            "tier": tier_label,
            "tier_rank": tier_rank,
            "red_flag": tier_label == "redflag",
            "location": d.get("location", ""),
            "url": d.get("jobUrl") or d.get("url") or "",
            "posted": (d.get("publishedAt") or d.get("published_at") or "")[:10],
            "age_days": age,
        })

    rows.sort(key=lambda r: (r["ats_pct"], r["tier_rank"], r["have_count"], -r["age_days"]),
              reverse=True)
    rows = rows[:top_n]

    with open("ats_full_report.md", "w") as f:
        f.write("# ATS-Direction Job Match Report\n\n")
        f.write(f"_Total jobs scored: {len(data)} | Showing top {len(rows)}_\n\n")
        f.write("| # | ATS % | Tier | ⚑ | Have | Gap | Title | Company | Location | Age | Gaps | Apply |\n")
        f.write("|--:|--:|:--:|:--:|--:|--:|---|---|---|--:|---|---|\n")
        for i, r in enumerate(rows, 1):
            gaps = ", ".join(r["gap_skills"][:4]) or "none ✅"
            tier = TIER_GLYPH[r["tier"]]
            flag = "⚠️" if r["red_flag"] else ""
            f.write(f"| {i} | {r['ats_pct']}% | {tier} | {flag} | {r['have_count']} | {r['gap_count']} | "
                    f"{r['title'][:40]} | {r['company'][:18]} | {r['location'].split(',')[0][:15]} | "
                    f"{r['age_days']}d | {gaps} | [apply]({r['url']}) |\n")

    with open("ats_full_report.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "ats_pct", "tier", "red_flag", "have_count", "gap_count",
                     "title", "company", "sector", "location", "posted", "age_days",
                     "have_skills", "gap_skills", "url"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["ats_pct"], r["tier"], int(r["red_flag"]),
                         r["have_count"], r["gap_count"],
                         r["title"], r["company"], r["sector"], r["location"], r["posted"],
                         r["age_days"], "; ".join(r["have_skills"]),
                         "; ".join(r["gap_skills"]), r["url"]])

    print(f"Scored {len(data)} jobs → ats_full_report.md + ats_full_report.csv")
    if rows:
        print(f"Top: {rows[0]['company']} - {rows[0]['title']} ({rows[0]['ats_pct']}%, {rows[0]['tier']})")


if __name__ == "__main__":
    main()
