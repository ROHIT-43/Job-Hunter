# Canonical scoring rubric (send verbatim to every scoring subagent)

This is the single source of truth for LLM job scoring. Every scoring subagent
MUST receive this whole file. Do not paraphrase it inline. The candidate skillset
below is derived from `data/profile.json` — if that changes, update this file.

## Candidate

Arnab Dutta — **3 years** SWE at Juspay/Nammayatri (Bengaluru).

- **Backend:** Haskell, Rust, PureScript (Servant, Axum). This is the real backend stack.
- **Frontend:** React, TypeScript, JavaScript, HTML5/CSS3, Material UI.
- **Java:** Arnab's *production* Java is Android/mobile-native; he hasn't shipped
  Java *backend* in production. For SCORING this is not a negative — he knows Java
  and his backend fundamentals transfer, so Java-backend roles score normally on
  overlap. For the RESUME, don't claim prior Java-backend production work.
- **Python is CI automation ONLY — never web backend.**
- **Data/infra:** Apache Kafka, Redis (+cluster), PostgreSQL, MySQL, MongoDB, DynamoDB.
- **Cloud/DevOps:** AWS (EKS, S3, SQS, CloudWatch), Kubernetes, Docker, CI/CD,
  GitHub Actions, Jenkins, Prometheus, Grafana, Istio.
- **AI/LLM:** MCP servers, agentic workflows, Claude Code, LLM integration.
- **Domains:** fintech/payments, high-scale backend, microservices, event-driven, DSL design.

## Score (integer 0–100)

Start from the ATS base, then apply penalties and caps. **Clamp the final score to
the 0–100 range. A score above 100 or below 0 is invalid.**

**Base — ATS coverage (the anchor):**

    ATS% = (skills the JD asks for that the candidate HAS) / (all skills the JD asks for) × 100

Weight the components: Required skills 40% · Experience fit 25% · Preferred 20% ·
Domain/presentation 15%.

**Hard penalties (subtract from the base):**

- .NET / C# / Angular as a core requirement → −35
- SAP / Salesforce / ServiceNow / Odoo / SiteCore / ZOHO / Dynamics → −40
- Python as the **web backend** → −30

> **Java backend is NOT penalised.** Java is the default backend at most big tech
> companies (Google, Amazon, Amex, Walmart, …), Arnab knows the language (Android),
> and his Haskell/Rust backend fundamentals transfer directly. Score a Java-backend
> role on its genuine overlap (Kafka, microservices, AWS/K8s, PostgreSQL,
> event-driven, system design, etc.) like any other backend role — do not dock it
> for using Java. (Resume honesty is separate: don't *claim* prior Java-backend
> production experience on the tailored resume; that guard is about the resume, not
> the score.)

**Caps (the score may not exceed the cap):**

- Walk-in / mass-hiring drive → cap 40
- QA / test-only / SDET → cap 50
- Explicit **5+ yrs** required → cap 60
- **7+ yrs** required → cap 45
- Lead / Manager / Principal / Staff / Architect title → cap 55
  (**`Senior`/`Sr` is NOT in this cap** — a Senior SWE is a normal target level and
  scores on overlap like any other role; e.g. Senior Razorpay → 82 above. Only
  Lead/Principal/Staff/Architect/management are capped. Years are handled by
  `min_yoe`, never by docking "Senior".)
- Pure data-engineering / ETL → cap 60
- Embedded / firmware-only → cap 55

**Rewards (push the base up, within caps):** Haskell/Rust/functional, React/TS
frontend, fintech/payments, high-scale backend, microservices, Kafka/event-driven,
AWS/K8s, MCP/agentic AI.

## Years-of-experience (set `min_yoe`, do not gate the score)

Extract the JD's stated **minimum** YoE into `min_yoe` (integer): "3-5 yrs"→3,
"4-6 yrs"→4, "5+"→5, "six years"→6, none stated → null. If the JD contradicts
itself, the **higher** stated minimum wins (e.g. a "5+ years" header beats a
"3-5 years" body → 5). The backbone uses `min_yoe` to exclude >3-yr roles from the
queue; you only need to report it accurately. **Do not change the score for YoE** —
the caps above already handle 5+/7+.

## Output contract (return exactly this)

- `id` (string)
- `score` (integer, **0–100**)
- `min_yoe` (integer or null)
- `matched_skills` (array of strings the candidate genuinely has that the JD wants)
- `gap_skills` (array of JD skills the candidate lacks)
- `jd_summary` (≤30 words)
- `reason` (≤25 words)
- `fetched` (boolean — false if the JD could not be read; then score 0)

Rules: `matched_skills` must be skills from the candidate list above — do not
invent. If `matched_skills` is empty, the score MUST be low (≤25): you cannot
score a role highly while listing it as all-gaps. Apply the formula; do not emit a
free-form number.

## Worked examples (calibration)

- **"Senior Backend Engineer — Go, Kafka, event-driven, fintech, 4-6 yrs"** →
  strong overlap (Go-adjacent backend, Kafka, event-driven, fintech), no penalty;
  `score 84`, `min_yoe 4`, matched=[Kafka, event-driven, distributed, fintech].
- **"Senior Software Development Engineer @ Razorpay (payments, high-scale)"** →
  fintech/payments + high-scale + microservices, "Senior" no explicit number;
  `score 82`, `min_yoe null`.
- **"Senior C Engineer — 4+ yrs systems/embedded C"** → candidate does not write C;
  matched=[], embedded → `score 8`, `min_yoe 4`. **NOT 100.**
- **"Azure Integration Engineer — Logic Apps, Service Bus, 4-5 yrs"** → no overlap
  with candidate stack; matched=[]; `score 12`, `min_yoe 4`. **NOT 100.**
- **"Java Backend Engineer @ Amazon — Java, microservices, AWS, Kafka, 3-5 yrs"** →
  Java is NOT penalised; strong overlap (microservices, AWS, Kafka, distributed) +
  T1 company; `score 78`, `min_yoe 3`, matched=[microservices, AWS, Kafka, distributed systems].
- **"Senior Java Software Engineer — Java/J2EE, Oracle PL/SQL, WebLogic, 8-12 yrs"** →
  no Java penalty, but 7+ cap 45 and thin modern-stack overlap (legacy J2EE/Oracle);
  `score ~42`, `min_yoe 8`.
- **"DevOps Engineer — K8s, AWS, CI/CD, 3+ yrs"** → solid cloud/devops overlap;
  `score 77`, `min_yoe 3`.
