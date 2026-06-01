"""Unified local ATS scorer + company-tier tiebreaker.

ATS% = |JD-required skills the candidate HAS| / |JD-required skills|, where
JD-required skills are master-dictionary terms found in the JD text. This is
source-agnostic: it needs only the JD text, which every source provides.
"""
import json
import re

from lib import paths

_DICT = None


def load_dictionary(path=None):
    """Load (and cache) the canonical->aliases skill dictionary."""
    global _DICT
    if path is None and _DICT is not None:
        return _DICT
    with open(path or paths.asset("skills_dictionary.json")) as f:
        data = json.load(f)
    if path is None:
        _DICT = data
    return data


def build_alias_index(dictionary):
    """Map every surface form (canonical + aliases) -> canonical skill."""
    idx = {}
    for canonical, aliases in dictionary.items():
        idx[canonical.lower()] = canonical.lower()
        for a in aliases:
            idx[a.lower()] = canonical.lower()
    return idx


def _present(term, hay):
    # Whole-token match. The term itself may contain . + # / (node.js, c#,
    # ci/cd); the boundaries only forbid an alphanumeric continuation, so a
    # trailing "." (sentence end, e.g. "GCP.") still counts. Bare "node" still
    # canonicalizes to "node.js", so allowing it here is harmless.
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
                     hay) is not None


def extract_jd_skills(text, alias_index):
    """Return the set of canonical skills mentioned in `text`."""
    hay = (text or "").lower()
    found = set()
    # Longest surface forms first so "spring boot" wins over "spring".
    for term in sorted(alias_index, key=len, reverse=True):
        if _present(term, hay):
            found.add(alias_index[term])
    return found


# Matches a leading experience floor: "5+ years", "5 years", "3-5 years"
# (lower bound), "3 to 5 yrs". Group 1 is the floor for that mention.
_YOE_RE = re.compile(
    r'(\d+)\s*(?:\+|\s*(?:-|to|–|—)\s*\d+\s*\+?)?\s*(?:years?|yrs?)\b')


def extract_min_yoe(text):
    """Best-effort minimum years-of-experience the JD demands, or None.

    Deterministic regex over the JD text. For a range ("3-5 years") it takes
    the lower bound; across several mentions ("8+ years ... 2+ years Kafka")
    it returns the highest floor — the headline seniority bar a candidate must
    clear. Absurd values (>50) and no-match both yield None (no constraint).
    """
    hay = (text or "").lower()
    floors = [int(m.group(1)) for m in _YOE_RE.finditer(hay)]
    floors = [f for f in floors if 0 < f <= 50]
    return max(floors) if floors else None


LOW_SIGNAL_MIN = 3  # JD must mention >= this many skills to be high-signal


def score_job(job, have_skills, alias_index):
    """Score one normalized job against the candidate's HAVE skills.

    Returns a dict with ats_pct, matches/gaps lists, counts, low_signal.
    """
    text = " ".join([
        job.get("title", ""),
        " ".join(job.get("tags", []) or []),
        job.get("description", "") or "",
    ])
    jd = extract_jd_skills(text, alias_index)
    have = {alias_index.get(s.lower(), s.lower()) for s in (have_skills or [])}
    matches = jd & have
    gaps = jd - have
    pct = round(len(matches) / len(jd) * 100) if jd else 0
    return {
        "ats_pct": pct,
        "matches": sorted(matches),
        "gaps": sorted(gaps),
        "jd_count": len(jd),
        "have_count": len(matches),
        "gap_count": len(gaps),
        "low_signal": len(jd) < LOW_SIGNAL_MIN,
    }


def weighted_score(required, preferred, have_skills, alias_index,
                   w_req=1.0, w_pref=0.3):
    """ATS score from LLM-labeled required/preferred JD skills.

    The LLM supplies which JD skills are required vs preferred; the match
    against the candidate's HAVE skills and all arithmetic stay here, so the
    number is deterministic and auditable given the labels. Required skills
    carry weight w_req, preferred carry w_pref:

        ats_pct = (w_req·|req∩have| + w_pref·|pref∩have|)
                / (w_req·|req|      + w_pref·|pref|)

    A skill listed as both required and preferred counts only as required.
    """
    def canon(items):
        return {alias_index.get(str(s).lower().strip(), str(s).lower().strip())
                for s in (items or []) if str(s).strip()}

    req = canon(required)
    pref = canon(preferred) - req
    have = canon(have_skills)
    m_req = req & have
    m_pref = pref & have
    total = w_req * len(req) + w_pref * len(pref)
    got = w_req * len(m_req) + w_pref * len(m_pref)
    pct = round(got / total * 100) if total else 0
    return {
        "ats_pct": pct,
        "matched_required": sorted(m_req),
        "missing_required": sorted(req - have),
        "matched_preferred": sorted(m_pref),
        "required_count": len(req),
        "preferred_count": len(pref),
        "weighted": True,
    }


# === COMPANY TIERS (moved verbatim from the retired ats_scorer.py) ==========
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
    "bcg", "palantir", "snowflake", "stripe", "databricks", "figma",
    "notion", "canva", "cloudflare", "confluent", "elastic", "hashicorp",
    "gitlab", "instacart", "doordash", "robinhood", "coinbase", "plaid",
    "brex", "ramp", "vercel", "supabase", "render", "fly.io",
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
    "physicswallah", "vedantu", "upstox", "smallcase", "groww", 
    "curefit", "lenskart", "cult.fit", "pharmeasy", "juspay",
    "myntra", "ajio", "limeroad", "nykaa", "firstcry", "bigbasket",
    "ajio", "paytm", "blinkit", "dunzo", "directi", "grofers", "zepto",
    "bpcl", "ioc", "indian oil", "ntpc", "powergrid", "adani", "reliance",
    "ola", "ola electric", "tata motors", "mahindra", "ashok leyland",
    "volkswagen"
    # global scaleups
    "stripe", "databricks", "snowflake", "gitlab", "hashicorp",
    "confluent", "elastic", "cloudflare", "figma", "notion", "canva",
    "discord", "instacart", "doordash", "robinhood", "coinbase",
    "plaid", "brex", "ramp", "vercel", "supabase", "render", 
    "fly.io", "6sense", "couchbase", "algolia", "commerceIQ", 
    "monday.com", "asana", "smartsheet", "snyk", "okta", 
    "auth0", "new relic", "datadog", "splunk", "segment", "mixpanel", "heap",
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
