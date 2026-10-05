# The static ATS scoring algorithm

This document explains, end to end, how the job-hunter skill turns a pile of raw
job listings into a ranked, scored shortlist — the **deterministic** part of the
pipeline that runs with no LLM and no network (once jobs are fetched). It is the
faithful model of the legacy / boolean ATS layer (exact-match + term-frequency)
that still underlies most recruiter sourcing.

> There is also an **optional** LLM pass that re-weights a shortlist by
> required-vs-preferred skills. That is layered *on top* of this static
> algorithm and is described at the end; everything before it is fully
> deterministic and unit-tested.

---

## The pieces

| File | Responsibility |
|---|---|
| `assets/departments.json` | the department taxonomy (which roles count, per-source facets) |
| `assets/skills_dictionary.json` | the master skill vocabulary (canonical term → aliases) |
| `scripts/lib/department.py` | classify a job into departments; gate by selection |
| `scripts/lib/ats.py` | extract JD skills, score a job, classify company tier |
| `scripts/score_jobs.py` | the CLI: load → dedup → score → sort → report |
| `data/profile.json` | the candidate's skills (the "HAVE" set) |

The data lives in JSON assets so the taxonomy and vocabulary can be tuned without
touching code.

---

## Stage 0 — fetch (upstream, not part of scoring)

`fetch_jobs.py` pulls listings from public APIs/RSS and `apify_scrape.py`
optionally pulls LinkedIn/Naukri. Both normalize every listing to one schema:

```json
{
  "id", "source", "title", "company", "location",
  "remote", "visa_sponsorship", "tags", "salary",
  "description", "url", "posted"
}
```

Jobs are kept by **department**, not keyword (see `department.classify`), so the
scorer receives a broad set of engineering/technology roles. Scoring takes over
from there.

---

## Stage 1 — load, merge, dedup

`score_jobs.py` accepts any number of normalized job files (e.g. the keyless
`jobs.json` plus an Apify export) and:

1. **Loads** each file, tolerating either a bare list or a `{items|data|results|jobs: [...]}` wrapper (`load_jobs`).
2. **Dedups** on the lowercased `(title, company)` pair, keeping the first
   occurrence (`dedup`). This collapses the same role seen on two sources.

---

## Stage 2 — build the candidate's HAVE set

`load_have_skills(profile.json)` reads the candidate profile and unions every
skill it can find, lowercased:

```
HAVE = skills[]  ∪  every experience[].skills[]  ∪  every projects[].skills[]
```

This is the set of things the candidate can evidence. It is built once and
reused for every job.

---

## Stage 3 — detect the skills each JD asks for

This is the core of the keyword model and lives in `lib/ats.py`.

### 3a. The dictionary and alias index

`skills_dictionary.json` maps a **canonical** skill to its **aliases** (surface
forms that mean the same thing):

```json
{ "kubernetes": ["k8s"], "go": ["golang"], "node.js": ["node", "nodejs"] }
```

`build_alias_index` flattens this into a lookup where *every* surface form points
at its canonical name:

```
"k8s" → "kubernetes",  "kubernetes" → "kubernetes",  "golang" → "go", ...
```

Aliases exist because real ATS keyword layers do **not** expand acronyms
(documented: "AWS" ≠ "Amazon Web Services" unless both appear). The alias index
is how we model that correctly — both forms resolve to one canonical skill.

### 3b. Extracting JD skills

`extract_jd_skills(text, alias_index)` scans the job text — `title + tags +
description` — and returns the set of **canonical** skills present:

- It tests each surface form with a whole-token regex so `java` does **not** fire
  inside `javascript`, and a trailing period (`"GCP."`) still counts.
- Longest surface forms are tested first, so `"spring boot"` wins over `"spring"`.
- Every hit is canonicalized through the alias index, so `k8s` and `kubernetes`
  collapse to the single skill `kubernetes`.

The result is `JD = { canonical skills this posting mentions }`.

---

## Stage 4 — score one job

`score_job(job, have, alias_index)` compares the two sets:

```
matches = JD ∩ HAVE          # skills the JD wants that you have
gaps    = JD − HAVE          # skills the JD wants that you lack

ATS% = |matches| / |JD|      ( 0 if the JD mentions no known skill )
```

So the score answers: **"of the skills this JD asks for, how many can I
evidence?"**

### The low-signal guard

If a JD mentions fewer than `LOW_SIGNAL_MIN` (= 3) known skills, the job is
flagged `low_signal`. This stops a thin posting that happens to mention one skill
you have from scoring a misleading 100% and topping the list. Low-signal jobs are
still listed, but sorted below every high-signal job.

`score_job` returns: `ats_pct, matches, gaps, jd_count, have_count, gap_count,
low_signal`.

---

## Stage 4b — the strict years-of-experience gate

The one **hard** filter. `extract_min_yoe(text)` parses the JD's stated minimum
experience with a deterministic regex:

- `"5+ years"` → 5, `"3 years"` → 3
- `"3-5 years"` / `"3 to 5 yrs"` → 3 (the lower bound)
- `"at least 4 years"` / `"minimum of 2 years"` → 4 / 2
- several mentions (`"8+ years ... 2+ years Kafka"`) → 8 (the highest floor)
- nothing parseable, or an absurd value (>50) → `None`

`apply_yoe_gate` then compares it to the candidate's `years_experience`:

```
if cand_yoe is not None and jd_min is not None and cand_yoe < jd_min:
    disqualify  →  ats_pct = 0, yoe_ok = False, reason = "needs Ny, have My"
```

A disqualified job is **not dropped** — it is kept, zeroed, marked ⛔ with the
reason, and sunk below every qualifying role (see the sort key). The gate is a
no-op when either side's YoE is unknown, so nothing is filtered silently. This is
the only hard gate; ATS%, tier, and recency are all soft ranking.

## Stage 5 — company tier (a tiebreaker only)

`company_tier(name, sector)` assigns each job a prestige band by matching the
company name/sector against curated lists in `lib/ats.py`:

| Label | Rank | Meaning |
|---|--:|---|
| `T1` | 3 | most renowned big tech (Google, Apple, Microsoft, …) |
| `T2` | 2 | renowned startups / unicorns (Razorpay, Stripe, …) |
| `neutral` (`·`) | 1 | unrecognised, incl. large IT-services firms (TCS, Infosys) |
| `redflag` (`⚠️`) | 0 | likely <100-dev shop — staffing / consultancy / recruiting |

Order of checks: `TIER1 → TIER2 → KNOWN_LARGE (forced neutral) → red-flag
patterns/sectors → neutral`. The tier **never changes the ATS%**; it only breaks
ties between equally-scored roles. True dev-count is unknowable from the data, so
the red flag is an honest *hint*, not a verdict.

---

## Stage 6 — sort

Every job becomes a row carrying its score, tier, and `age_days` (computed from
`posted`). Rows sort by this key, all descending:

```
1. qualifying first    (YoE-disqualified jobs sink to the very bottom)
2. high-signal first   (low_signal jobs sink below qualifying high-signal)
3. ATS%                 (primary score signal)
4. company tier rank    (T1 > T2 > neutral > red-flag)
5. matched-skill count  (more concrete matches first)
6. recency              (newer postings first)
```

The YoE gate is the most significant dimension; among qualifying jobs, ATS match
is primary and tier, match-count, and recency only separate ties.

---

## Stage 7 — report

The top `--top` rows are written two ways:

- **`report.md`** — a ranked table (ATS%, tier, department, gaps, age, apply
  link) plus a footer legend. `⚠️` marks low-signal rows.
- **`jobs_ranked.csv`** — the same data, spreadsheet-friendly for tracking
  applications.

Both carry the disclaimer that this is an **advisory keyword/skill match, not a
prediction of any ATS accept/reject decision** — because real ATS ranking is
recruiter-augmenting and heterogeneous, never a universal auto-reject.

---

## End-to-end at a glance

```
fetch_jobs / apify_scrape         → normalized jobs (by department)
        │
score_jobs.py
  load_jobs ─ dedup               → unique postings
  load_have_skills(profile)       → HAVE set (your skills)
  build_alias_index(dictionary)   → surface-form → canonical
  for each job:
      extract_jd_skills(text)     → JD set
      score_job(JD, HAVE)         → ATS% + matches/gaps + low_signal
      company_tier(name)          → T1/T2/neutral/redflag
  sort: signal ▸ ATS% ▸ tier ▸ matches ▸ recency
  write report.md + jobs_ranked.csv
```

Worked example (your profile vs a backend role whose JD mentions
python, kafka, postgresql, aws, terraform):

```
JD      = {python, kafka, postgresql, aws, terraform}   (5 skills)
HAVE    ⊇ {python, kafka, postgresql, aws}              (terraform is a gap)
matches = 4,  gaps = {terraform}
ATS%    = 4 / 5 = 80%
```

---

## The optional LLM layer (not static)

The static algorithm weights every JD skill equally. An optional second pass
(SKILL.md step 7) reads each shortlisted JD and labels its skills **required** vs
**preferred**; `weighted_score` then re-scores:

```
weighted ATS% = (w_req·|required ∩ HAVE| + w_pref·|preferred ∩ HAVE|)
              / (w_req·|required|        + w_pref·|preferred|)
```

with defaults `w_req = 1.0`, `w_pref = 0.3`. Crucially, the LLM only supplies the
*labels*; the matching against HAVE and all arithmetic stay in `weighted_score`,
so the number remains deterministic and auditable given the labels. Re-scored
jobs are marked `✨`, and their Gaps column shows missing **required** skills —
the real blockers. Unlabeled jobs keep their static dictionary score.

See `references/scoring.md` for tuning.
