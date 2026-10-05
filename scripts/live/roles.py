"""roles.py — Role family + level from a job title, and staffing-agency detection.

family() returns one of FAMILIES, or None for a non-software title (accountant,
civil engineer, data-entry, …). The family + level form the salary lookup key, so
"Frontend Engineer" and "Data Engineer" at one company get separate salaries.
Rules are checked most-specific first: "Software Engineer – Android" is mobile.
"""
import re

FAMILIES = ("mobile", "ml", "data", "security", "qa", "erp", "devops",
            "frontend", "fullstack", "swe")

# Engineering disciplines that are not software, unless the title also says so.
_NOT_SOFTWARE = re.compile(
    r"\b(civil|mechanical|electrical|electronics?|chemical|structural|hvac|sales|"
    r"field|site|process|production|manufacturing|maintenance|instrumentation|mep|"
    r"piping|automobile|automotive|biomedical|mining|marine|aerospace|design|"
    r"service|application support|support|network|telecom|rf|hardware|"
    r"business development)\s+(engineer|engineering|developer|development)")

_RULES = [
    ("mobile", r"\b(android|ios|mobile|flutter|react native|kotlin multiplatform|swiftui?)\b"),
    # clear ML roles; a software title that merely mentions AI is handled below
    ("ml", r"\b(machine learning|ml engineer\w*|ml developer|mlops|ai/ml|ml/ai|"
           r"data scien\w*|deep learning|nlp|computer vision|ai engineer\w*|"
           r"ai developer|ai specialist|ai researcher|llm engineer|prompt engineer|"
           r"gen ?ai engineer|applied scientist|research scientist|artificial intelligence engineer)\b"),
    ("data", r"\b(data engineer\w*|etl|big data|databricks|spark|hadoop|snowflake|"
             r"data platform|analytics engineer|informatica|dbt)\b"),
    ("security", r"\b(security engineer|appsec|application security|devsecops|"
                 r"cyber ?security|penetration|pentest\w*|soc analyst)\b"),
    ("qa", r"\b(qa|sdet|test\w*|quality assurance|automation tester|selenium|playwright|cypress)\b"),
    ("erp", r"\b(sap|abap|salesforce|sfdc|servicenow|oracle (?:apps|ebs|fusion)|"
            r"dynamics 365|workday|pega|mulesoft|boomi)\b"),
    ("devops", r"\b(devops|sre|site reliability|cloud engineer|platform engineer|"
               r"infrastructure engineer|kubernetes|aws engineer|azure engineer|gcp engineer)\b"),
    ("frontend", r"\b(front[- ]?end|ui developer|ui engineer|react(?:\.?js)?|angular|"
                 r"vue(?:\.?js)?|web developer)\b"),
    ("fullstack", r"\b(full[- ]?stack|mern|mean stack)\b"),
    ("swe", r"\b(software|sde|swe|asde|developer|programmer|member of technical staff|"
            r"mts|back[- ]?end|application engineer|systems? engineer|java|python|golang|"
            r"\.net|dotnet|node(?:\.?js)?|php|ruby|c\+\+|scala|rust|microservices|"
            r"engineer (?:i|ii|iii|1|2|3)|associate engineer|graduate engineer)\b"),
]
_RULES = [(name, re.compile(rx)) for name, rx in _RULES]

_INTERN = re.compile(r"\b(intern|internship|trainee|apprentice\w*|auszubildende\w*)\b")
_L3 = re.compile(r"\b(iii|3|sde[\s-]?3)\b")
_L2 = re.compile(r"\b(ii|2|sde[\s-]?2)\b")

# Staffing agencies / recruiters posting for a hidden client: their "company" says
# nothing about pay, so salaries are never looked up for them.
_AGENCY = re.compile(
    r"\b(staffing|recruit\w*|placement\w*|manpower|hiring|talent (?:solutions|acquisition)|"
    r"hr (?:services|solutions|consult\w*)|consultants|outsourc\w*|confidential|"
    r"michael page|teamlease|randstad|adecco|quess|ciel hr|abc consultants|"
    r"kelly services|xpheno|careernet|hirect|naukri|apna|internshala)\b")


def _norm(title):
    return re.sub(r"\s+", " ", (title or "").lower())


# Roles that mention a tech stack but are not engineering jobs.
_NOT_ENGINEERING = re.compile(
    r"\b(trainer|faculty|tutor|teacher|mentor|lecturer|professor|instructor|product owner|"
    r"product manager|recruiter|sales|pre-?sales|business analyst|scrum master)\b")
# Pure design roles; "Web Designer and Developer" still counts as a developer job.
_DESIGN_ONLY = re.compile(r"\b(designer|ui/ux|ux)\b")
_BUILDS = re.compile(r"\b(developer|engineer|programmer|sde)\b")


def family(title):
    """Role family for a software title, or None if the title is not a software role."""
    t = _norm(title)
    if _NOT_ENGINEERING.search(t):
        return None
    if _DESIGN_ONLY.search(t) and not _BUILDS.search(t):
        return None
    if _NOT_SOFTWARE.search(t) and "software" not in t:
        return None
    for name, rx in _RULES:
        if name == "swe" and _AI_WORD.search(t) and not _CORE_SWE.search(t):
            return "ml"  # "Agentic AI developer": AI is the job, not a feature of it
        if rx.search(t):
            return name
    return None


_AI_WORD = re.compile(r"\b(ai|llm|gen ?ai|agentic)\b")
_CORE_SWE = re.compile(r"\b(software|sde|swe|backend|back[- ]end|full[- ]?stack|front[- ]?end|"
                       r"java|python|node(?:\.?js)?|golang|\.net)\b")


def level(title):
    """'intern', 'l1' (default / entry), 'l2' or 'l3' from the title."""
    t = _norm(title)
    if _INTERN.search(t):
        return "intern"
    if _L3.search(t):
        return "l3"
    if _L2.search(t):
        return "l2"
    return "l1"


_INTERNSHIP = re.compile(r"\b(intern|internship|apprentice\w*|auszubildende\w*)\b")


def is_internship(title, *fields):
    """Internship posting? Title ("SDE Intern") or LinkedIn's seniority / employment
    type ("Internship"). Graduate/engineer *trainee* roles are full-time jobs, so kept."""
    return bool(_INTERNSHIP.search(_norm(title)) or
                any(_INTERNSHIP.search(_norm(f)) for f in fields if f))


def is_agency(company):
    return bool(_AGENCY.search(_norm(company)))
