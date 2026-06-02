---
name: job-hunter
description: >
  Find, aggregate, and rank software / tech job openings across the Indian
  market (Naukri, LinkedIn, Instahyre, Hirist, foundit) and international roles
  that are remote or visa-sponsored (RemoteOK, Remotive, Arbeitnow, Himalayas,
  Wellfound, Adzuna, company career pages). Use this skill whenever the user
  wants to look for jobs, search openings, "find me roles", hunt for a new
  position, track listings for their stack, find remote work, find visa-sponsored
  jobs abroad, or build a ranked shortlist of opportunities. Trigger on phrases
  like "find me a job", "any backend roles open", "search Naukri/LinkedIn for",
  "remote Rust jobs", "who's sponsoring visas", or "help me job hunt" — even if
  no specific site is named. Pairs with the resume-builder skill to tailor a
  resume per shortlisted role.
---

# Job Hunter

Aggregate live job listings from many sources, rank them against the user's
profile, and produce a ranked shortlist with apply links. Then optionally hand
the top matches to `resume-builder` for per-JD tailoring.

## Ground rules (read first)

- **Respect site terms.** LinkedIn, Naukri, Indeed, Wellfound and similar sites
  forbid automated scraping and actively block bots. This skill never builds a
  stealth scraper or bypasses bot protection. For those sites it generates
  **pre-filtered search URLs** the user opens themselves, or uses an **Apify
  actor** (see `references/apify.md`) with the user's consent. Live data is
  pulled only from sources that offer clean public APIs/RSS.
- **Network is required** for fetching. The scripts use only the Python standard
  library but need egress enabled in the running environment. If a fetch fails
  with a network error, tell the user their environment needs network access on.
- This is **information, not advice.** Present matches and let the user decide;
  don't make career/financial guarantees.

## Workflow

### 1. Build the candidate profile

The profile drives both search and ranking. Build it from what you already know:
- If the user has a resume (the `resume-builder` skill knows their stack), derive
  `must_have_skills`, `target_titles`, and `seniority_level` from it instead of
  asking them to retype everything.
- Otherwise collect: target role(s), key skills, seniority, locations, and the
  three switches — `remote_only`, `visa_required`, preferred/avoid companies.

Write it to `data/profile.json` using `assets/candidate.example.json` as the
template — `score_jobs.py` derives your HAVE skills from its `skills[]`,
`experience[].skills[]`, and `projects[].skills[]`. Confirm the filled profile
with the user in one line before searching.

### 2. Decide the search mix

Map the user's intent to sources (full catalog in `references/sources.md`):

- **India, any setup** → Adzuna (`--adzuna-country in`, needs free key) for live
  data + `search_urls.py` for Naukri/LinkedIn/Instahyre/Hirist/foundit.
- **Remote (anywhere)** → RemoteOK, Remotive, Himalayas, Jobicy, We Work
  Remotely (all keyless) + `search_urls.py --remote`.
- **Visa-sponsored international** → Arbeitnow (has a visa flag) + a `web_search`
  for current curated sponsor lists + `search_urls.py` with target countries.
- **A specific company** → `web_search` / `web_fetch` on its careers page.
- **Wants results pulled in (not just links) for LinkedIn/Naukri** → offer the
  Apify route (`references/apify.md`), confirm credit use first.

### 3. Fetch live listings (Tier 1)

```bash
python scripts/fetch_jobs.py \
    --departments software,engineering,technology --since-days 30 \
    --adzuna-country in --adzuna-id "$ADZUNA_ID" --adzuna-key "$ADZUNA_KEY" \
    --out jobs.json
```

Jobs are kept by **department**, not keyword. Default departments are
`software,engineering,technology`; add `data`/`devops`/`security`/`qa` to widen.
One run sweeps India + remote + visa together. Add `--remote` and/or `--visa`
to hard-filter. Omit Adzuna flags to skip it.
If the user has no Adzuna key, run without it and note that adding one (free,
2 min at developer.adzuna.com) unlocks the strongest India source.

### 4. Generate browse links (Tier 2)

```bash
python scripts/search_urls.py \
    --keywords "backend engineer haskell rust" \
    --location "Bengaluru" --remote --since-days 7 \
    --category general,tech --out search_links.md
```

ToS-safe deep links, grouped by `--category` (general, tech, remote, freshers,
bluecollar, freelance, or `all`). `general` covers Naukri, LinkedIn, Indeed,
Foundit, Shine, TimesJobs, Glassdoor, Google Jobs, NCS; `tech` covers CutShort,
Instahyre, Wellfound, Hirist, Hirect. Default is `general,tech` — match the
category to the user's level (don't surface blue-collar/fresher links to a
senior engineer unless asked). Full catalog in `references/sources.md`.

### 5. (Optional) Pull LinkedIn/Naukri via Apify

Only with user consent (pay-per-result). Apify has strong actors for **LinkedIn,
Naukri, Indeed, Glassdoor** and a multi-source aggregator, but **none** for most
niche Indian sites (CutShort, Instahyre, Hirist, Apna, Shine, etc.) — those stay
on `search_urls.py`. Verify availability with `search-actors` each run; never
assume an actor exists or automate a login. Follow `references/apify.md`, then
merge the actor's rows into `jobs.json` in the normalized schema before ranking.

### 6. Rank and report

```bash
python scripts/score_jobs.py jobs.json data/apify_jobs.json \
    --profile profile.json --top 50 --out-dir data/output
```

One unified scorer (`score_jobs.py`, backed by `scripts/lib/ats.py`) merges all
input files, dedups, and gives each job an ATS match score (see
`references/scoring.md`): `ATS% = JD skills you have ÷ all JD skills`, ordered by
ATS% then company tier then recency. Pass any number of normalized job files
(e.g. the keyless `jobs.json` plus an Apify `data/apify_jobs.json`).

### 7. (Optional) LLM-weight the shortlist (required vs preferred)

The flat dictionary score treats every JD skill equally. For a sharper top-of-
list, run a second pass where **you (the model) read each shortlisted JD** and
label its skills *required* vs *preferred*; the scorer then re-weights coverage
(required skills count far more) and the missing-**required** skills become the
real "blockers" column. This models the JD's own structure and catches skills
the dictionary doesn't know — closing the gap to the semantic ATS layer
(Workday/Workable/LinkedIn). It stays an **advisory** score, never a prediction
that any ATS will accept/reject.

1. **Pass 1 — emit the shortlist** (also writes the normal report):
   ```bash
   python scripts/score_jobs.py jobs.json data/apify_jobs.json \
       --profile data/profile.json --top 50 --out-dir data/output \
       --emit-shortlist data/shortlist.json --shortlist-n 25
   ```
   `data/shortlist.json` holds `have_skills`, the `weights`, and the top-25 jobs
   (each with `key`, `title`, `company`, `description`, `url`).

2. **Label each job — this is your job, not a script.** Read every job's
   `description` in `data/shortlist.json` and classify the concrete skills/tools
   it mentions. Use the JD's own framing: "must have / required / X+ years" →
   `required`; "nice to have / preferred / bonus / plus" → `preferred`. Only
   list real skills (languages, frameworks, datastores, cloud, tools); skip soft
   skills. Do **not** judge whether the candidate has them — that stays
   deterministic. Write `data/llm_labels.json` keyed by each job's `key`:
   ```json
   {
     "Senior Backend Engineer::Razorpay": {
       "required": ["go", "kafka", "postgresql", "aws"],
       "preferred": ["kubernetes", "grpc"]
     }
   }
   ```
   For 25 jobs, do this directly; for larger shortlists, dispatch a subagent per
   batch with this same instruction and a strict schema, then merge the JSON.

3. **Pass 3 — re-score with the labels:**
   ```bash
   python scripts/score_jobs.py jobs.json data/apify_jobs.json \
       --profile data/profile.json --top 50 --out-dir data/output \
       --llm-labels data/llm_labels.json
   ```
   Labeled jobs are re-scored as
   `(w_req·matched_required + w_pref·matched_preferred) ÷ (w_req·required +
   w_pref·preferred)` (defaults `--w-req 1.0 --w-pref 0.3`), re-sorted, and
   marked ✨ in the report; their Gaps column shows missing **required** skills.
   Unlabeled jobs keep their dictionary score.

### 8. Present

- Save `report.md`, `jobs_ranked.csv`, and `search_links.md` to
  `/mnt/user-data/outputs/` and present them with `present_files`.
- Summarise: how many matched, the top handful by score, and the strongest
  remote / visa-sponsored options if those were requested.
- Offer the resume-builder handoff: "Want me to tailor your (1-page) resume to
  any of these top roles?" — if yes, invoke the `resume-builder` skill with the
  chosen JD.

## Output

Always produce three artifacts:
1. `report.md` — ranked table + top-10 detail with apply links
2. `jobs_ranked.csv` — same data, spreadsheet-friendly for tracking applications
3. `search_links.md` — pre-filtered Tier-2 browse links

## Reference files

- `references/sources.md` — every source, access method, India vs international,
  visa/remote coverage, and how to add new sources
- `references/scoring.md` — the unified ATS formula and how to tune it
- `references/apify.md` — pulling LinkedIn/Naukri structured data via Apify
- `assets/candidate.example.json` — candidate profile template (skills feed ATS)
