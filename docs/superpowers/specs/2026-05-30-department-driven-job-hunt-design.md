# Department-driven job hunt + unified ATS — design

_Date: 2026-05-30_

## Problem

Today the pipeline searches each source by **keyword** (`--keywords haskell,rust,backend`).
Keyword search at fetch time is too narrow — it only returns JDs that literally
contain those terms and silently drops good engineering roles. Separately, the
"ATS test" only works on LinkedIn-via-Apify output (it reads the actor's
`matchedKeywords` field); every other source scores ~0% because that field is
absent. The repo also carries **two** scorers (`ats_scorer.py`,
`rank_jobs.py`) with different logic.

## Goal

Replace keyword-driven fetch with **department-driven** fetch, and score every
job through **one unified local ATS scorer**, so a single run sweeps all three of
the user's buckets (India + global-remote + visa-sponsored) in a timeframe
(default 30 days) and produces one ATS-ranked report.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Fetch model | **Department only** — no search keywords at fetch |
| ATS scoring | **One unified local scorer** — works on every source |
| Department detection | **Department taxonomy (multi-bucket)**, mapped per-source |
| Run scope | **One run = all three buckets, merged & deduped** |
| Code shape | **Approach A** — shared `lib/` modules, keep existing CLI entry points |
| ATS extraction | **Master-dictionary** — comprehensive tech-skill vocabulary |
| Old scorers | **Absorb into `lib/ats.py`, delete the files, keep backups** |

## Input contract

There is **no `--keywords` flag and no `--buckets` flag**. A run always fetches
all three buckets and merges. The only inputs are the timeframe, the department
selection, and (optionally) the paid/keyed sources.

Fetch (keyless + optional Apify/Adzuna), all buckets:
```
python scripts/fetch_jobs.py \
  --since-days 30 \                 # timeframe; default 30
  --departments software,data,devops,security,qa \  # default = all eng-family
  --adzuna-id <id> --adzuna-key <key> \  # optional, unlocks India API
  --out data/jobs.json
```
Optional paid LinkedIn/Naukri pull (consented, capped), merged before scoring:
```
python scripts/apify_scrape.py --actor <actor> \
  --departments software,data --location India --rows 50 \
  --out data/apify_jobs.json
```
Unified scoring (replaces ats_scorer.py + rank_jobs.py):
```
python scripts/score_jobs.py data/jobs.json [data/apify_jobs.json] \
  --profile data/profile.json --top 50 --out-dir data/output
```

## Architecture & data flow (Approach A — shared libs, existing entry points)

```
fetch_jobs.py / apify_scrape.py  (entry points — keep)
  └─ resolve all 3 buckets -> source set (+ remote/visa flags)
  └─ fetch each source: NO keywords, since_days,
        dept taxonomy -> native facet where the source supports it
  └─ lib.department.classify(...)  — uniform gate on every source
  └─ bucket filters  (recency, remote, visa)
  └─ merge + dedup on (title, company)  -> jobs.json

score_jobs.py  (new single scorer entry point)
  └─ lib.ats.score_job(job, have_skills)  -> ats_pct, have, gap, tier, low_signal
  └─ sort: ats_pct ▸ tier_rank ▸ have_count ▸ recency
  └─ write report.md + jobs.csv  (+ search_links.md for browse-only sites)
```

### New files
- `scripts/lib/department.py` — the department **taxonomy**, per-source native
  facet codes, and `classify(title, tags) -> set[department]` /
  `matches(job, selected_departments) -> bool`.
- `scripts/lib/ats.py` — master skill-dictionary loader,
  `extract_jd_skills(text)`, `score_job(job, have_skills)`, and the company-tier
  logic moved verbatim from `ats_scorer.py`.
- `scripts/score_jobs.py` — the single scoring CLI that replaces both old
  scorers, backed by `lib/ats.py`.
- `assets/skills_dictionary.json` — comprehensive curated tech-skill vocabulary
  (languages, frameworks, datastores, cloud, infra, data/ML, concepts) with
  light alias handling.
- `assets/departments.json` — the taxonomy: each department's title/tag matchers
  and its per-source native facet codes (kept in data so it's tunable).

### Reused / refactored (kept as entry points)
- `scripts/fetch_jobs.py` — `--keywords` removed; gains `--departments`; fetches
  all buckets; imports `lib.department`. Its `src_*` adapters and date/normalize
  helpers stay.
- `scripts/apify_scrape.py` — builds LinkedIn/Naukri input from the department
  facet instead of keywords; `run_actor()` unchanged.
- `scripts/search_urls.py` — unchanged; still emits browse links for ToS-blocked
  sites.

### Removed (with backup)
- `scripts/ats_scorer.py` and `scripts/rank_jobs.py` are deleted from the main
  path after their logic moves into `lib/ats.py`. A copy of each is kept under
  `scripts/_legacy/` (git-tracked) so nothing is lost. `SKILL.md` and
  `README.md` are updated to point at the new flow.

## Department taxonomy (the multi-bucket model)

A named taxonomy the user selects among via `--departments` (default = all
engineering-family buckets):

| Department | Example titles/tags | Native facets |
|---|---|---|
| `software` | software/backend/frontend/full-stack engineer, SDE, SWE, developer | LinkedIn `f_F=eng`, Adzuna `it-jobs`, Naukri eng functional-area |
| `data` | data engineer/scientist, ML/AI engineer, analytics | LinkedIn `f_F=eng,anls`, Naukri data area |
| `devops` | devops, SRE, platform, infrastructure, cloud engineer | LinkedIn `f_F=eng,it` |
| `security` | security engineer, appsec, infosec | LinkedIn `f_F=eng,it` |
| `qa` | QA, SDET, test automation | LinkedIn `f_F=qa` |

For each department, `assets/departments.json` holds (a) **title/tag matchers**
(allowlist + a small denylist to drop near-misses like "sales engineer",
"solutions engineer" pre-sales) and (b) **native facet codes** per source.

- **At fetch:** sources with a native facet (LinkedIn, Naukri, Adzuna) are
  queried with the union of facet codes for the selected departments — cuts
  volume and Apify cost.
- **Everywhere (uniform gate):** `lib.department.classify(title, tags)` assigns
  each fetched job zero-or-more departments from its matchers; a job is kept iff
  it intersects the selected departments. This catches facet-less boards
  (RemoteOK, Remotive, Himalayas, Jobicy, WeWorkRemotely, The Muse, Arbeitnow)
  and corrects mis-faceted rows. The assigned department(s) are stored on the
  job for display.

## Unified local ATS scorer (master-dictionary)

- `assets/skills_dictionary.json` is the master vocabulary, aiming for
  comprehensive coverage, with alias handling (`node`/`node.js`,
  `k8s`/`kubernetes`, `gcp`/`google cloud`).
- Resume **HAVE** = candidate profile skills (`skills[]` +
  `experience[].skills[]` + `projects[].skills[]`), lowercased.
- Per job:
  - `JD_required = { dictionary terms found in JD text (title + tags + description) }`
  - `matches = JD_required ∩ HAVE`
  - `gaps    = JD_required − HAVE`
  - `ATS%    = |matches| / |JD_required|`  (0 if `JD_required` empty)
- **Low-signal guard:** if `|JD_required| < 3`, flag the job `low_signal` so a
  "100% off one matched skill" role can't spuriously top the ranking. Such jobs
  are still listed but sorted/marked accordingly.
- The `matchedKeywords`-from-actor path is **dropped**; extraction depends only
  on JD text, which Adzuna, the remote boards, and the LinkedIn actor all
  provide.

### Company tiers (tiebreaker, preserved)
The T1/T2/known-large/red-flag classification from `ats_scorer.py` moves into
`lib/ats.py` with identical behavior and remains a sort tiebreaker only.

## Bucket -> source map (all three always run)

- **india** → Adzuna (`country=in`, dept facet) + (with Apify) LinkedIn + Naukri;
  plus `search_urls.py` browse links.
- **remote** → RemoteOK, Remotive, Himalayas, Jobicy, WeWorkRemotely, The Muse —
  fetched broad, department-gated locally, `remote` hard-filtered.
- **visa** → Arbeitnow (visa flag, hard-filtered) + remote sources where visa
  status is unknown (treated neutral, not dropped). Curated sponsor lists stay a
  skill-level `web_search` step, not part of the script.

A run fetches all three, merges, and dedups on `(title.lower(), company.lower())`.

## Output

- `report.md` — ATS-ranked table + top-N detail (assigned department, gaps, tier,
  low-signal flag, apply links).
- `jobs.csv` — same data, spreadsheet-friendly for application tracking.
- `search_links.md` — pre-filtered browse links for ToS-blocked sites.

All written to `--out-dir` (default `data/output`).

## Error handling & edge cases

- A failing source adapter returns `[]` and logs to stderr; the run continues.
- Empty/short JD description → few/zero `JD_required` → `low_signal`.
- No profile / empty skills → every JD skill is a gap → near-0 scores; warn.
- Network egress required; failures reported clearly.
- Apify is pay-per-result → only on explicit opt-in with a row cap, per
  `references/apify.md`.

## Testing

- `lib/department.py`: unit tests for `classify`/`matches` over a fixture of
  allow/deny titles per department (incl. sales/manager near-misses).
- `lib/ats.py`: unit tests for `extract_jd_skills` (dictionary + aliases),
  `score_job` math (incl. empty/low-signal), and tier classification.
- `score_jobs.py`: end-to-end test over a small recorded jobs fixture (no
  network) asserting dept filtering, dedup, ranking order, report/CSV output.

## Out of scope

- A single `hunt.py` orchestrator (Approach C) — keeping discrete entry points.
- Departments beyond the eng-family taxonomy (structure allows adding them).
- Any change to ToS posture — browse links + consented Apify only.
- Resume tailoring — still handed to `resume-builder` after shortlisting.
