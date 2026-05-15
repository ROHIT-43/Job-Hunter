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

Write it to `profile.json` using `assets/profile.example.json` as the template.
Confirm the filled profile with the user in one line before searching.

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
    --keywords haskell,rust,backend,scala \
    --location India --since-days 30 \
    --adzuna-country in --adzuna-id "$ADZUNA_ID" --adzuna-key "$ADZUNA_KEY" \
    --out jobs.json
```

Add `--remote` and/or `--visa` to hard-filter. Omit Adzuna flags to skip it.
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
python scripts/rank_jobs.py \
    --jobs jobs.json --profile profile.json \
    --top 40 --out-md report.md --out-csv jobs_ranked.csv
```

Scoring is transparent (see `references/scoring.md`): a 0–100 match score per job
with a component breakdown for the top 10 so the user can see *why* each ranked.

### 7. Present

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
- `references/scoring.md` — the ranking formula and how to tune it
- `references/apify.md` — pulling LinkedIn/Naukri structured data via Apify
- `assets/profile.example.json` — candidate profile template
