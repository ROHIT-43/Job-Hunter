#!/usr/bin/env python3
"""
ats_scorer.py — Compute correct ATS-direction scores from LinkedIn Apify data,
and order results by ATS match first, then by how renowned the company is.

The LinkedIn actor matches ALL resume keywords (have + gap) against each JD.
This script splits matchedKeywords into:
  - have_matches: skills the candidate actually possesses
  - gap_matches: skills the JD wants that the candidate LACKS

ATS % = have_matches / (have_matches + gap_matches)

This is "how much of what this JD asks for, do you already have?" — the real
ATS/LinkedIn direction.

CANDIDATE PROFILE (the skills come from YOUR json)
--------------------------------------------------
Skills are no longer hardcoded. Point --profile at a candidate JSON (see
assets/candidate.example.json). The script derives:

  HAVE = union of  skills[]  +  every experience[].skills[]  +  every
         project[].skills[]                       (all lowercased)
  GAP  = explicit  gap_skills[]                   (skills you know you lack)

Any JD keyword that is neither HAVE nor GAP is treated as a gap (conservative —
it lowers the score when we can't confirm you have it). If no profile file is
found the built-in DEFAULT_* sets are used as a fallback.

COMPANY TIERS (ordering tiebreaker)
-----------------------------------
The LinkedIn JSON has companyName / companyId / sector but NO employee or
developer count, so prestige and "how big is the eng org" cannot be read from
the data. We approximate it with curated, in-file lists you can extend:

  Tier 1 (T1)  most renowned big tech          Google, Apple, Microsoft, ...
  Tier 2 (T2)  renowned startups / unicorns     Razorpay, Swiggy, Stripe, ...
  neutral (·)  everything we don't recognise
  red flag (!) likely <100-dev shop             staffing / consultancy / etc.

Because true dev counts are unknowable here, the red flag is a name/sector
heuristic (staffing, consultancy, recruiting, manpower, ...) plus an explicit
small-shop set. It is a hint, not a verdict — extend RED_FLAG_NAMES / patterns
as you learn more.

ORDERING
--------
Sort key (all descending):
    ats_pct  ->  tier_rank  ->  have_count  ->  recency
ATS match stays primary; tier only breaks ties between equal-ATS roles, so a
renowned company floats above a no-name (and a red-flag shop sinks below it)
within the same ATS band.

USAGE
-----
    python ats_scorer.py <job_export.json> \
        [--profile data/profile.json] [--top N] [--out-dir data/output]

Writes <out-dir>/ats_full_report.md and <out-dir>/ats_full_report.csv.
"""
import json, csv, sys, os
from datetime import date

TODAY = date(2026, 5, 30)
DEFAULT_PROFILE = os.path.join("data", "profile.json")
DEFAULT_OUT_DIR = os.path.join("data", "output")

# === DEFAULT SKILL SETS (fallback when no --profile file exists) ============
DEFAULT_HAVE_SKILLS = {
    "python", "java", "go", "rust", "typescript", "javascript", "c++",
    "react", "react native", "node.js", "kafka", "redis", "kubernetes", "docker",
    "aws", "postgresql", "mysql", "mongodb", "dynamodb", "microservices",
    "rest", "grpc", "ci/cd", "distributed systems", "sql", "haskell",
    "graphql",
}
DEFAULT_GAP_SKILLS = {
    "spring boot", "hibernate", "terraform", "azure", "gcp",
    "angular", "scala", "snowflake", "php", "ruby",
    "elasticsearch", "rabbitmq", "oracle", "maven", "django", ".net",
    "protobuf", "cassandra",
}

# Active skill sets — reassigned from the candidate profile in main().
HAVE_SKILLS = set(DEFAULT_HAVE_SKILLS)
GAP_SKILLS = set(DEFAULT_GAP_SKILLS)

# === COMPANY TIERS ==========================================================
# Curated, case-insensitive substring matches against companyName. Extend
# freely. Keep entries lowercase. Order of checks: TIER1 -> TIER2 ->
# KNOWN_LARGE -> red flag -> neutral.

TIER1_NAMES = {
    # global big tech / FAANG+ and household-name eng orgs
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
    # renowned startups / unicorns / scaleups (incl. India) — well-known,
    # strong eng brand, but not mega-cap big tech
    # India
    "razorpay", "swiggy", "zomato", "zerodha", "cred", "postman",
    "flipkart", "phonepe", "paytm", "freshworks", "groww", "meesho",
    "dream11", "browserstack", "nykaa", "unacademy", "byju", "ola",
    "navi", "slice", "jupiter", "urban company", "sharechat", "delhivery",
    "polygon", "innovaccer", "gupshup", "chargebee", "hasura", "juspay",
    "rapido", "porter", "moengage", "whatfix", "darwinbox", "zeta",
    "setu", "m2p", "khatabook", "spinny", "cars24", "licious",
    "physicswallah", "vedantu", "upstox", "smallcase",
    # global scaleups
    "stripe", "databricks", "snowflake", "gitlab", "hashicorp",
    "confluent", "elastic", "cloudflare", "figma", "notion", "canva",
    "discord", "instacart", "doordash", "robinhood", "coinbase",
    "plaid", "brex", "ramp", "vercel", "supabase", "render", "fly.io",
}

# Large, well-staffed orgs that are NOT prestige T1/T2 but are definitely
# >100 devs — IT-services giants and product firms whose name/sector would
# otherwise trip a red-flag pattern (e.g. "Tata *Consultancy*", HackerRank's
# "Staffing and Recruiting" sector). Checked BEFORE red-flagging -> neutral.
KNOWN_LARGE_NAMES = {
    # India IT-services majors
    "tata consultancy", "tcs", "infosys", "wipro", "hcl", "cognizant",
    "tech mahindra", "ltimindtree", "lti", "mindtree", "mphasis", "coforge",
    "persistent", "birlasoft", "hexaware", "zensar", "cyient", "nagarro",
    "mastek", "sonata", "happiest minds", "kpit", "l&t technology",
    # global services / consultancies (large eng orgs)
    "accenture", "capgemini", "deloitte", "dxc",
    "epam", "globallogic", "ust", "publicis sapient", "thoughtworks",
    "virtusa", "endava", "ey", "pwc", "kpmg", "genpact", "infosys bpm",
    # product/platform firms that trip generic patterns
    "hackerrank", "hackerearth", "zoho",
}

# Explicit small-shop / body-shop names to red-flag regardless of pattern.
RED_FLAG_NAMES = set()

# Substring patterns that strongly suggest a staffing / consultancy / tiny
# shop rather than a product company with a real (>100-dev) eng org.
RED_FLAG_PATTERNS = (
    "staffing", "staff solutions", "consultanc", "consultants",
    "recruit", "hiring", "manpower", "placement", "talent solutions",
    "hr services", "hr solutions", "outsourc", "resourcing",
    "it services pvt", "global services", "infotech solutions",
    "software solutions", "technologies pvt ltd", "tech solutions",
    "services pvt ltd", "ventures pvt",
)
# Sectors that lean staffing/consultancy (LinkedIn "sector" field).
RED_FLAG_SECTORS = ("staffing", "recruiting", "outsourcing")

# tier label -> numeric rank used for ordering (higher = better; red flag last)
TIER_RANK = {"T1": 3, "T2": 2, "neutral": 1, "redflag": 0}
TIER_GLYPH = {"T1": "T1", "T2": "T2", "neutral": "·", "redflag": "⚠️"}


def _hit(name, names):
    return any(n in name for n in names)


def company_tier(company_name, sector=""):
    """Return (label, rank) for a company. label in T1/T2/neutral/redflag."""
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


def load_candidate_profile(path):
    """Read a candidate profile JSON and derive (have_skills, gap_skills, prof).

    HAVE = union of  skills[]  +  experience[].skills[]  +  projects[].skills[]
    GAP  = explicit  gap_skills[]
    All skills are lowercased/stripped; a skill listed in both resolves to HAVE.
    """
    with open(path) as fh:
        prof = json.load(fh)

    def norm(items):
        return {str(s).lower().strip() for s in (items or []) if str(s).strip()}

    have = norm(prof.get("skills"))
    for exp in (prof.get("experience") or []):
        have |= norm(exp.get("skills"))
    for proj in (prof.get("projects") or []):
        have |= norm(proj.get("skills"))
    gap = norm(prof.get("gap_skills"))
    gap -= have  # a skill can't be both — HAVE wins
    return have, gap, prof


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


def flag_value(argv, name, default=None):
    """Return the value following `--name`, or default if absent."""
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return default


def main():
    argv = sys.argv
    if len(argv) < 2 or argv[1].startswith("--"):
        print("Usage: python ats_scorer.py <job_export.json> "
              "[--profile data/profile.json] [--top N] [--out-dir data/output]")
        sys.exit(1)

    job_file = argv[1]
    profile_path = flag_value(argv, "--profile", DEFAULT_PROFILE)
    out_dir = flag_value(argv, "--out-dir", DEFAULT_OUT_DIR)
    top_n_arg = flag_value(argv, "--top")

    # --- candidate profile (skills come from here) ---
    global HAVE_SKILLS, GAP_SKILLS
    if profile_path and os.path.exists(profile_path):
        HAVE_SKILLS, GAP_SKILLS, prof = load_candidate_profile(profile_path)
        who = prof.get("name") or "candidate"
        print(f"Loaded profile '{who}' from {profile_path} "
              f"({len(HAVE_SKILLS)} have / {len(GAP_SKILLS)} gap skills)")
        if not HAVE_SKILLS:
            print("WARNING: profile lists no skills — every JD keyword will "
                  "count as a gap. Add skills[]/experience[].skills to fix.")
    else:
        print(f"No profile at {profile_path} — using built-in default skill "
              f"sets. Copy assets/candidate.example.json there to customise.")

    raw = json.load(open(job_file))

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
    top_n = int(top_n_arg) if top_n_arg else len(data)

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
            "total_detected": len(have) + len(gap),
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
            "contract": d.get("contractType", ""),
            "level": d.get("experienceLevel", ""),
        })

    # Sort: ATS % desc, then company tier desc (renowned first, red-flag last),
    # then have_count desc, then recency.
    rows.sort(key=lambda r: (r["ats_pct"], r["tier_rank"], r["have_count"], -r["age_days"]),
              reverse=True)
    rows = rows[:top_n]

    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "ats_full_report.md")
    csv_path = os.path.join(out_dir, "ats_full_report.csv")

    # === MARKDOWN REPORT ===
    with open(md_path, "w") as f:
        f.write("# ATS-Direction Job Match Report\n\n")
        f.write(f"_Total jobs scored: {len(data)} | Showing top {len(rows)}_\n\n")
        f.write("_ATS % = skills you HAVE that this JD mentions ÷ ALL skills this JD mentions "
                "(including gaps like Spring Boot, Hibernate, Angular, etc.)_\n\n")
        f.write("_Tie-break order within an ATS band: **T1** big tech (Google, Apple…) > "
                "**T2** renowned startups (Razorpay, Stripe…) > **·** neutral > "
                "**⚠️** likely <100-dev shop (staffing/consultancy)._\n\n")
        f.write("| # | ATS % | Tier | ⚑ | Have | Gap | Title | Company | Location | Age | Gaps | Apply |\n")
        f.write("|--:|--:|:--:|:--:|--:|--:|---|---|---|--:|---|---|\n")
        for i, r in enumerate(rows, 1):
            title = r["title"][:40]
            company = r["company"][:18]
            loc = r["location"].split(",")[0][:15]
            gaps = ", ".join(r["gap_skills"][:4]) or "none ✅"
            age = f"{r['age_days']}d"
            url = r["url"]
            tier = TIER_GLYPH[r["tier"]]
            flag = "⚠️" if r["red_flag"] else ""
            f.write(f"| {i} | {r['ats_pct']}% | {tier} | {flag} | {r['have_count']} | {r['gap_count']} | "
                    f"{title} | {company} | {loc} | {age} | {gaps} | [apply]({url}) |\n")

        # Summary section
        f.write(f"\n\n## Summary\n\n")
        perfect = [r for r in rows if r["ats_pct"] == 100]
        high = [r for r in rows if 80 <= r["ats_pct"] < 100]
        good = [r for r in rows if 60 <= r["ats_pct"] < 80]
        f.write(f"- **100% match (all JD skills covered):** {len(perfect)} roles\n")
        f.write(f"- **80-99% match:** {len(high)} roles\n")
        f.write(f"- **60-79% match:** {len(good)} roles\n")

        # Tier breakdown
        t1 = [r for r in rows if r["tier"] == "T1"]
        t2 = [r for r in rows if r["tier"] == "T2"]
        flagged = [r for r in rows if r["red_flag"]]
        f.write(f"\n### Company tiers (across shown roles):\n\n")
        f.write(f"- **T1 big tech:** {len(t1)} roles\n")
        f.write(f"- **T2 renowned startups:** {len(t2)} roles\n")
        f.write(f"- **⚠️ red-flag (likely <100-dev / staffing / consultancy):** {len(flagged)} roles\n")
        if flagged:
            flagged_names = sorted({r["company"] for r in flagged})
            f.write(f"\n  Flagged companies: {', '.join(flagged_names[:25])}"
                    f"{' …' if len(flagged_names) > 25 else ''}\n")

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
    with open(csv_path, "w", newline="") as f:
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

    print(f"Scored {len(data)} jobs → {md_path} + {csv_path}")
    print(f"100% matches: {len(perfect)} | 80%+: {len(high)} | 60%+: {len(good)}")
    print(f"Tiers shown — T1: {len([r for r in rows if r['tier']=='T1'])} | "
          f"T2: {len([r for r in rows if r['tier']=='T2'])} | "
          f"⚠️ red-flag: {len([r for r in rows if r['red_flag']])}")
    if rows:
        print(f"Top: {rows[0]['company']} - {rows[0]['title']} ({rows[0]['ats_pct']}%, {rows[0]['tier']})")

if __name__ == "__main__":
    main()
