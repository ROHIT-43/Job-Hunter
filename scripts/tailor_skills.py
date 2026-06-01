#!/usr/bin/env python3
"""tailor_skills.py — deterministic, zero-LLM per-JD tailoring.

For each batch300/*/jd.txt:
  - rebuild resume.tex from the TRUE master (data/resume/resume-builder.tex) so the
    dense, well-scoring master bullets are restored (undoes the over-tailored pass),
  - lead the Technical Skills section with a "Most Relevant" line of the JD's OWN
    skill keywords, filtered to skills Arnab genuinely has (verbatim keyword match =
    better real-ATS weightage),
  - set the Juspay subtitle by JD family,
  - swap the leadership bullet (B5) for B8 (payments) or B7 (infra) ONLY when the JD
    clearly fits — never inject PureScript-React or Python-CI bullets (they lower scores).

Nothing Arnab lacks is ever emitted. Run: python scripts/tailor_skills.py
"""
import os, re, glob, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "data/resume/resume-builder.tex")
GLOB = os.path.join(ROOT, "data/output/batch300/*/jd.txt")

# canonical label -> regex of JD aliases. ONLY skills Arnab genuinely has.
SKILLS = {
    "React": r"react(?:\.?js)?\b", "TypeScript": r"type ?script\b", "JavaScript": r"java ?script\b|\bes6\b",
    "HTML5": r"\bhtml ?5?\b", "CSS3": r"\bcss ?3?\b", "Responsive design": r"responsive",
    "Redux/Context": r"\bredux\b|context api", "React hooks": r"hooks?\b", "Material UI": r"material[- ]?ui|\bmui\b",
    "Haskell": r"haskell", "Rust": r"\brust\b", "PureScript": r"pure ?script",
    "Python": r"python", "C++": r"c\+\+|cpp\b", "SQL": r"\bsql\b", "Bash": r"\bbash\b|shell script",
    "Microservices": r"micro ?services?", "RESTful APIs": r"rest(?:ful)?\b|\bapis?\b",
    "Event-driven architecture": r"event[- ]driven", "Distributed systems": r"distributed (?:systems?|computing)",
    "gRPC": r"grpc", "GraphQL": r"graphql", "System design": r"system design",
    "Apache Kafka": r"kafka", "Redis": r"redis", "Stream processing": r"stream(?:ing| processing)",
    "AWS": r"\baws\b|amazon web services", "Kubernetes": r"kubernetes|\bk8s\b", "Docker": r"docker|container",
    "Istio / service mesh": r"istio|service mesh", "CI/CD": r"ci/?cd|continuous (?:integration|delivery|deployment)",
    "GitHub Actions": r"github actions", "Prometheus": r"prometheus", "Grafana": r"grafana",
    "Observability": r"observability|monitoring|tracing", "Microservice networking": r"load balanc|api gateway|reverse prox",
    "PostgreSQL": r"postgre", "MySQL": r"mysql", "MongoDB": r"mongo", "DynamoDB": r"dynamo",
    "LLM integration": r"\bllm\b|large language model|generative ai|gen ?ai", "Agentic workflows": r"agentic|\bagent\b",
    "MCP servers": r"\bmcp\b|model context protocol", "AI-assisted dev": r"ai[- ]?(?:assisted|powered|first)|copilot|claude",
    "Vitest": r"vitest", "Playwright": r"playwright", "Unit/integration testing": r"unit test|integration test|test automation",
    "Agile/Scrum": r"agile|scrum", "Code reviews": r"code review", "Git": r"\bgit\b|version control",
}

# group structure preserved from master; matched skills lead.
GROUPS = [
    ("Languages", ["Haskell","Rust","PureScript","TypeScript","JavaScript","Python","C++","SQL"]),
    ("Frontend", ["React","TypeScript","JavaScript","HTML5","CSS3","Responsive design","Redux/Context","React hooks","Material UI"]),
    ("Backend \\& APIs", ["Microservices","RESTful APIs","Event-driven architecture","Distributed systems","System design","gRPC","GraphQL"]),
    ("Event-Driven \\& Data", ["Apache Kafka","Redis","Stream processing"]),
    ("Cloud \\& DevOps", ["AWS","Kubernetes","Docker","Istio / service mesh","CI/CD","GitHub Actions","Prometheus","Grafana","Observability","Microservice networking"]),
    ("AI / LLM", ["LLM integration","Agentic workflows","MCP servers","AI-assisted dev"]),
    ("Testing \\& Process", ["Vitest","Playwright","Unit/integration testing","Agile/Scrum","Code reviews","Git"]),
    ("Databases", ["PostgreSQL","MySQL","MongoDB","DynamoDB"]),
]
# always-true baseline so a sparse JD still yields a full skills section
BASE = {"Languages":["Haskell","Rust","TypeScript","JavaScript","Python","C++","SQL"],
        "Backend \\& APIs":["Microservices","RESTful APIs","Event-driven architecture","Distributed systems"],
        "Event-Driven \\& Data":["Apache Kafka","Redis"],
        "Cloud \\& DevOps":["AWS","Kubernetes","Docker","CI/CD","GitHub Actions"],
        "Databases":["PostgreSQL","MySQL","MongoDB"]}

B8 = (r"\item At \textbf{Juspay} (payments infrastructure), helped re-architect the \textbf{marketplace} "
      r"relational data model --- removed a redundant association table by sourcing the relationship from "
      r"origin tables, simplifying the schema and cutting \textbf{data duplication}.")
B7 = (r"\item Configured an \textbf{Istio VirtualService} on the service-mesh gateway to securely route "
      r"\textbf{API} traffic to an internal, non-public service behind a single gateway IP --- hardening "
      r"\textbf{security} without exposing the backend.")

def matched(jd):
    low = jd.lower()
    return {c for c, pat in SKILLS.items() if re.search(pat, low)}

def subtitle(jd):
    low = jd.lower()
    fe = bool(re.search(r"front[- ]?end|react|\bui\b|web developer", low))
    be = bool(re.search(r"back[- ]?end|microservice|distributed|api|server", low))
    if fe and not be: return "Software Developer, Frontend"
    if fe and be:     return "Software Developer, Full Stack"
    return "Software Developer, Backend"

def family_bonus(jd):
    low = jd.lower()
    if re.search(r"payment|fintech|financial|transaction|banking|ledger|settlement", low): return "payments"
    if re.search(r"istio|service mesh|platform engineer|infrastructure|networking|devops|sre|observability", low): return "infra"
    return None

def skills_block(jd):
    hit = matched(jd)
    lines = []
    # 1) verbatim "Most Relevant" lead line — JD's own keywords Arnab has
    lead = [c for c in dict.fromkeys(sum([g[1] for g in GROUPS], [])) if c in hit]
    if len(lead) >= 3:
        lines.append("    \\singleItem{Most Relevant: }{%s}" % ", ".join(lead[:10]))
    # 2) standard groups, matched-first then baseline; skip empty groups
    for label, members in GROUPS:
        chosen = [m for m in members if m in hit] + [m for m in BASE.get(label, []) if m not in hit]
        # de-dup preserve order
        seen, vals = set(), []
        for m in chosen:
            if m not in seen: seen.add(m); vals.append(m)
        if vals:
            lines.append("    \\singleItem{%s: }{%s}" % (label, ", ".join(vals)))
    return "\\begin{flushleft}\n" + "\n    \\\\\n".join(lines) + "\n\\end{flushleft}"

def build(master, jd):
    doc = master
    # subtitle
    doc = doc.replace("{Software Developer, Backend}{Kolkata, India}",
                      "{%s}{Kolkata, India}" % subtitle(jd), 1)
    # bonus bullet: replace the leadership bullet (starts "Led a \textbf{cross-functional}")
    bonus = family_bonus(jd)
    if bonus:
        repl = B8 if bonus == "payments" else B7
        doc = re.sub(r"\\item Led a \\textbf\{cross-functional\}.*?product goals\}\.",
                     repl, doc, count=1, flags=re.S)
    # skills section
    doc = re.sub(r"\\begin\{flushleft\}.*?\\end\{flushleft\}", lambda _: skills_block(jd),
                 doc, count=1, flags=re.S)
    return doc

def main():
    master = open(MASTER).read()
    stats = {"payments": 0, "infra": 0, "none": 0}
    n = 0
    for jdp in sorted(glob.glob(GLOB)):
        folder = os.path.dirname(jdp)
        jd = open(jdp).read()
        out = build(master, jd)
        open(os.path.join(folder, "resume.tex"), "w").write(out)
        stats[family_bonus(jd) or "none"] += 1
        n += 1
    print(f"rebuilt {n} resume.tex (deterministic, 0 tokens)")
    print(f"  bonus bullet: payments(B8)={stats['payments']}  infra(B7)={stats['infra']}  none={stats['none']}")

if __name__ == "__main__":
    main()
