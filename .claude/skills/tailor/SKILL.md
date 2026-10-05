---
name: tailor
description: >
  Tailor a candidate's resume for a specific company/job posting. Use this skill
  when the user says "tailor my resume for X", "create resume for X", "customize
  resume for X company", or any variation of resume tailoring for a specific job.
  Trigger on phrases like "tailor for", "resume for", "customize resume",
  "make resume for", "adapt resume for".
---

# Resume Tailor

Generates company-specific `.tex` resumes by modifying only the **content** of
the base LaTeX template. Never changes formatting, margins, fonts, or template code.

## Input modes

- **Company name:** `/tailor Techdome` — looks up JD from scored data
- **Batch:** `/tailor Techdome eBay Zoca` — generates all three in one go
- **URL:** `/tailor https://linkedin.com/jobs/view/12345` — fetches JD from the link
- **Any job portal URL works:** LinkedIn, Naukri, Indeed, Instahyre, Wellfound, etc.

In batch mode, run Steps 0-1 once (shared), then loop Steps 2-5 for each company.
Use parallel Agent calls where possible to speed up batch generation.

## Step 0 — Load candidate profile

Read `data/profile.json` to get the candidate's identity:

```python
import json
with open("data/profile.json") as f:
    profile = json.load(f)
name = profile["name"]                    # e.g. "Rohit Saini"
```

Derive the filename-safe name: spaces → underscores (e.g. `Rohit_Saini`).

- **Base template**: `resumes/Base_Resume_<Name>.tex` (e.g. `Base_Resume_Rohit_Saini.tex`
  or `Base_Resume_Rohit.tex` — find whichever exists with a glob on `resumes/Base_Resume_*.tex`)
- **Output**: `resumes/<Company>_Resume_<FirstName>.tex`
- **Candidate skills**: `profile["skills"]` — these are what the candidate ACTUALLY has.
  Never add skills to the resume that aren't in this list or in the experience/projects.
- **Gap skills**: `profile["gap_skills"]` — skills the candidate does NOT have. Never
  claim these on the resume. You may list them in the Skills section ONLY if they appear
  in experience/projects (candidate actually used them).

## Step 1 — Read the base template

Read the base `.tex` file found in Step 0. This is the **source of truth** for all
formatting — preamble, packages, margins, commands, spacing. Never modify any of it.

**The base resume is ALSO the ONLY source of truth for CONTENT.** Every bullet,
metric, project detail, and responsibility in the tailored resume MUST come from the
chosen base `.tex` (backend `Base_Resume_Rohit.tex`, frontend `Frontend_Resume_Rohit.tex`,
or BOTH for full-stack). **Never pull bullets, metrics, phrasing, or experience from
`data/profile.json` or any other source** — `profile.json` is used ONLY for the
skills / gap-skills truthfulness check (Step 0), NEVER as a content source. If a
detail or metric is not present in the chosen base resume, it does not go in the
tailored resume, even if it appears in `profile.json`. (Concretely: the base resumes'
Driver Cancellation bullet has NO "30%" metric and there is NO "Led 10+ full-stack
features" bullet — do not add either.)

## Step 2 — Get the JD

Detect what the user provided and get the JD:

1. **URL detected** (input starts with `http`): Use `WebFetch` to fetch the page
   content from the URL. Extract the job title, company name, and full JD text.
   If WebFetch fails (login wall, 429), try the Chrome browser tools
   (`mcp__claude-in-chrome__navigate` + `mcp__claude-in-chrome__get_page_text`)
   if available. If that also fails, ask the user to paste the JD text directly.
   Extract the company name from the JD for the output filename.

2. **Company name detected**: Search `data/pipeline/browser_runs/*/jobs_scored.json`
   and `data/pipeline/browser_runs/*/matches.json` for the company name.

3. **Neither found**: Ask the user to provide the JD (paste text or URL).

**Multiple jobs from the same company:** If the scored data has 2+ jobs from the
same company, list them with scores and ask the user which role to tailor for.

## Step 3 — Identify JD keywords to weave in

Extract the key skills, tools, and soft skills the JD emphasizes:

- Tech stack (languages, frameworks, databases, cloud)
- Soft keywords: ORM, Database Design, Version Control, Scalability,
  Performance Optimization, Code Reviews, Troubleshooting, Debugging,
  Collaboration, Problem-Solving, CI/CD, Agile, Microservices
- Domain terms specific to the company/role

Cross-reference with `profile["skills"]` — only weave in keywords the candidate
genuinely has.

### Relevance hierarchy — prioritize in this order

1. Required qualifications and core technologies
2. Primary responsibilities of the role
3. Technologies/skills repeatedly emphasized in the JD
4. Domain-specific requirements
5. Preferred / nice-to-have qualifications
6. Generic soft skills

Emphasize categories 1–4 first. Do NOT over-optimize for low-value keywords just
because they appear in the JD.

### Selective keyword usage — coverage is NOT the goal

Do not try to include every JD keyword. Include a keyword ONLY when (a) it is
genuinely relevant to existing candidate experience, and (b) it improves the clarity
or discoverability of that experience. It is acceptable — and expected — for
important JD requirements to remain **absent** when the candidate has no
corresponding evidence. Natural relevance beats keyword coverage.

## Step 4 — Generate the tailored `.tex`

Write `resumes/<Company>_Resume_<FirstName>.tex`:

1. **Copy the EXACT preamble** from the base `.tex` — every `\usepackage`, margin,
   `\newcommand`, spacing value. Do NOT add or remove any packages.
2. **Keep the EXACT heading** — same name, phone, email, and URLs as the base template.
   Read them from the base file, do not hardcode.
3. **Tailor the Skills section** — reorder/regroup to lead with JD-relevant skills,
   but only include skills supported by `data/profile.json` or the base resume;
   never add a technology solely because it appears in the JD. Add JD keywords
   naturally and keep the same `\textbf{Category}{: items}` format. Listing a
   technology here does not by itself justify claiming professional/project
   experience with it — that requires evidence in Work Experience or Projects
   (see the Skill vs responsibility rule).
4. **Tailor Work Experience bullets** — reword existing bullets to mirror JD
   keywords. Keep the SAME NUMBER of bullets as the base template. Reorder to
   lead with JD-relevant work. Never fabricate experience. Never drop bullets.
5. **Tailor Project bullets** — reword to emphasize JD-relevant tech. Keep the
   SAME NUMBER of bullets as the base template. Keep all projects. Never drop bullets.
6. **Keep Education & Achievements** — exact same content, always include both as
   separate sections (however they appear in the base template).
7. **MUST fit 1 page — non-negotiable.** The base template fits on 1 page. When
   tailoring, weave JD keywords by REPLACING existing words, not by appending
   extra phrases. Each bullet should stay roughly the same length as the
   original. If a bullet grows longer to fit a keyword, shorten another part of
   the same bullet to compensate. After writing the full `.tex`, mentally verify
   it won't exceed 1 page — if in doubt, trim phrasing preemptively. Never
   remove/drop entire bullets or sections. Never produce a 2-page resume.
8. **Project links** — copy the exact URLs from the base template. Do not change them.

## Step 5 — Confirm

Tell the user:
- File saved at `resumes/<Company>_Resume_<FirstName>.tex`
- Summary of what was changed (skills reordered, keywords added, bullets reworded)
- **Missing skills (MANDATORY)** — list the JD-required/emphasized skills the
  candidate does NOT have (anything in `profile["gap_skills"]` or simply absent
  from the profile/base). These are the gaps that could NOT be added to the resume.
  Group them required-vs-preferred where the JD distinguishes, so the user sees
  exactly what this role wants that they're missing.
- Remind them to compile on Overleaf and optionally scan on Jobscan

## Resume tailoring rules (MANDATORY — read before generating any resume)

These rules override all other tailoring guidance. Follow every rule strictly.

### The golden rule

**Change the minimum amount necessary.** Do not rewrite bullets just to match the
JD. Preserve the original engineering accomplishments, technologies, and
implementation details. Only modify wording where it improves alignment with the
JD while remaining completely truthful and interview-defensible.

**Tailor by emphasis, not invention.** Achieve alignment by reordering bullets,
reordering technologies within Skills, emphasizing relevant implementation/project
details, shortening irrelevant details, and using JD terminology that naturally
fits — never by creating new experience to close a gap.

**Preserve strong bullets.** If a bullet already matches the JD well, carries strong
technical detail, contains a real metric, and reads naturally, leave it
substantially unchanged. Do not rewrite a strong bullet merely to insert another
keyword.

### Content rules

1. **Never invent experience.** Do not add technologies, tools, cloud providers,
   or responsibilities not present in the base resume. Only emphasize what exists.

2. **Preserve technical accuracy.** Do not replace implementation details with
   buzzwords. Prefer `Haskell REST APIs using PostgreSQL, Redis and ClickHouse`
   over `Backend service`. Prefer `Docker`, `Kubernetes`, `Redis`, `ClickHouse`,
   `PostgreSQL`, `React Native` over `cloud platform`, `backend infrastructure`,
   `analytics solution`.

3. **ATS optimization must never reduce technical depth.** Keep technologies,
   databases, frameworks, architectures, and implementation details. Only modify
   wording to naturally include JD keywords.

4. **Keep implementation details.** Prefer `Distributed locking using Redis` over
   `Built scalable backend infrastructure`.

5. **Do not replace technologies with abstractions.** Never swap specific tech
   names for generic phrases like "scalable platform" or "enterprise solution".

### Language rules

6. **Avoid AI buzzwords.** Limit use of: architected, engineered, leveraged,
   cutting-edge, scalable, robust, innovative, world-class, cloud-native,
   best-in-class. Use only when genuinely appropriate.

7. **Avoid repetition.** Don't repeat words like scalable, cloud-native, platform,
   engineered, architected more than once or twice in the entire resume.

8. **Keep strong nouns.** Prefer REST APIs, Distributed Systems, Docker Containers,
   Kubernetes, PostgreSQL, Redis, JWT Authentication, WebSockets over generic
   phrases.

9. **Make it sound human-written.** Read every bullet aloud. If it sounds like
   marketing copy, rewrite it. If it sounds like something an engineer would
   naturally say, keep it.

### Structure rules

10. **Every bullet: Action → Technical implementation → Impact.**
    Example: `Developed REST APIs in Haskell using PostgreSQL and Redis to
    aggregate driver analytics across 20+ dimensions, reducing dashboard
    latency by 60%.`
    **NEVER invent an impact.** If the base resume has no measurable or explicitly
    stated outcome, keep the factual implementation detail rather than manufacturing
    a result.

11. **Metrics are immutable source facts.** Preserve every metric exactly
    (60%, 80%, 99.9%, 2M+, 150,000+); only grammatical/formatting changes are
    allowed. Never create, infer, estimate, combine unrelated metrics, change a
    metric's magnitude, or turn a qualitative outcome into a quantitative one.

12. **Keep bullets concise.** Aim for 18–28 words. Maximum 35 words.

### Integrity rules

13. **Do not exaggerate responsibilities or seniority.** Do not rename projects to
    match the JD. Describe them accurately using terminology that aligns naturally.
    ❌ Trust & Safety Moderation Platform → ✅ Policy-based Driver Cancellation
    and Penalty System.
    Never alter the apparent seniority or scope of the work: do not introduce
    leadership, ownership, mentoring, architecture, management, cross-team, or
    strategic responsibility unless the base resume supports it. Tailor relevance,
    not seniority.

14. **Maintain interview defensibility.** Every sentence must be something the
    candidate can confidently explain in a technical interview. If a recruiter
    asks "How did you do this?", there must be a real answer.

15. **Don't downgrade strong bullets.** If the original contains Haskell, Redis,
    Docker, ClickHouse, Kubernetes, Kafka — don't replace them with generic
    phrases.

16. **Use JD keywords naturally.** Only include keywords that genuinely relate to
    existing experience. Never force them into unrelated projects.

17. **Prioritize technical signal over ATS.** If choosing between "sounds better
    for ATS" vs "demonstrates stronger engineering ability" — prefer the stronger
    engineering version.

18. **Respect the original project domain.** Never change what a project actually
    does. Driver Cancellation System stays Driver Cancellation System. For each
    project, emphasize the implementation details most relevant to the JD in this
    priority — (1) JD-relevant technologies, (2) JD-relevant engineering concepts,
    (3) measurable impact, (4) complexity/depth — while keeping it factual and
    recognizable.

### Evidence & semantic integrity

19. **Evidence preservation.** A rewritten bullet MAY reorder information, shorten
    wording, change sentence structure, swap in equivalent JD terminology, or
    emphasize an existing technology/responsibility. A rewritten bullet must NOT
    introduce a new responsibility, strengthen the level of ownership, introduce a
    new outcome, introduce a new implementation detail, or imply experience that was
    only mentioned in the JD.

20. **Semantic equivalence test.** Every rewritten bullet must stay semantically
    equivalent to the original. Ask: "If a recruiter compared the original and
    tailored versions, would they agree both describe the same work?" If no, keep
    the original wording. JD terminology may improve clarity but must not change the
    underlying claim.

21. **Skill vs responsibility distinction.** A technology in the Skills section does
    not mean the candidate performed every responsibility associated with it. Do not
    convert a skill into an accomplishment, or add a JD responsibility to Work
    Experience, unless Work Experience or Projects provide supporting evidence.

22. **JD terminology mapping.** When the JD uses a standard industry term that
    accurately describes existing work, prefer it where natural (e.g. "HTTP
    endpoints" → "REST APIs" when the work is genuinely REST-based). Do not use JD
    terminology when it changes the technical meaning of the original experience.

23. **Preserve candidate identity.** The tailored resume must still accurately
    describe the candidate with the JD removed. It should never read as if
    transformed into a different candidate profile for a particular company, and it
    must remain technically credible and informative even without the JD.

24. **Do not infer adjacent skills.** Experience with one technology, framework,
    database, or concept does not prove experience with a related one — REST APIs
    ≠ GraphQL, PostgreSQL ≠ MySQL production, React ≠ every React-ecosystem tool,
    Docker ≠ Kubernetes production. Only claim the specific skill or responsibility
    the candidate's existing evidence supports.

### Keyword discipline

25. **No keyword dilution across sections.** Use Skills for discoverability and
    Experience/Projects to demonstrate skills through evidence. Do not repeat the
    same JD keyword unnecessarily across Skills, multiple Experience bullets, and
    Projects. A technology should appear where it is most relevant, not everywhere.

26. **Do not force keywords or rewrite purely for insertion.** Introduce a keyword
    into a bullet only when the underlying work already relates to that concept. A
    few strong, naturally placed keywords beat repetitive keyword-heavy writing.

## Final tailoring validation

Before finalizing (and before the 1-page compile check), compare the tailored resume
against the base. Verify:

- Every factual claim and every metric existed in the base resume or an explicitly
  authorized profile source (`data/profile.json`).
- No technology, responsibility, outcome, or metric was introduced without evidence.
- No seniority, ownership, or scope level was increased.
- No project domain was changed; projects remain recognizable.
- Strong technical details were preserved; JD-relevant information was made more
  prominent; irrelevant detail was not expanded.
- Wording remains natural and human-written, and the resume stays technically
  credible without the JD.

If any newly introduced or materially changed claim cannot be supported, revert it to
wording directly supported by the base resume. The final resume must contain **zero
unsupported claims.**

## Core principle

The objective of tailoring is NOT to make the candidate appear to have every skill in
the JD. It is to present the candidate's **existing** experience in the most relevant,
clear, technically strong, and truthful way for that specific role. Tailor by changing
emphasis, ordering, terminology, and concise wording — never the underlying facts.

## What NOT to do

- Do NOT generate PDFs — user compiles on Overleaf
- Do NOT change LaTeX template code (packages, margins, commands, spacing)
- Do NOT fabricate experience or skills the candidate doesn't have
- Do NOT remove any sections that exist in the base template
- Do NOT hardcode candidate details — always read from profile.json and the base .tex
