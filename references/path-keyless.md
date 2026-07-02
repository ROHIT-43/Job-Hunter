# Path C — Keyless (public APIs + ToS-safe links)

The free path: live data from sources with clean public APIs, plus pre-filtered
browse links for sites that forbid scraping. No login, no credits. Produces
normalized candidates (already carrying JD text), then hands off to
`references/backbone.md` (writes `APPLY_QUEUE.md`).

## Direct companies pipeline (Google + Amazon + Microsoft → Ollama)

When you want scored, queue-ready results from company career pages without
LinkedIn — use `fetch_direct_companies.py`. It fetches JDs directly (no
separate browser JD-fetch step), applies the same filter chain as the LinkedIn
pipeline, and writes `ollama_input.json` ready for `run_ollama_local.py`.

**Step 1 — Create run dir**
```bash
python3 scripts/new_run.py --window 7d --label direct_v1
```

**Step 2 — (Microsoft only) Scrape in browser**

Microsoft's careers site is a client-rendered SPA — it needs a real browser tab:
```
https://apply.careers.microsoft.com/careers?query=Software+Engineer&start=0
  &location=India%2C+Multiple+Locations%2C+Multiple+Locations
  &sort_by=timestamp&filter_include_remote=1
  &filter_career_discipline=Software+Engineering
  &filter_employment_type=full-time&filter_profession=software+engineering
  &filter_seniority=Mid-Level
```
Paste `scripts/browser/scrape_microsoft_careers.js` → auto-downloads `ms_jobs.json`.
Poll `window.__MS_DONE`. Google and Amazon don't need this step.

**Step 3 — Fetch + filter**
```bash
python3 scripts/pipeline/fetch_direct_companies.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/ \
    --sources google,amazon,microsoft \
    --ms-jobs ~/Downloads/ms_jobs.json \
    --since-days 7 \
    --max-pages 10
# Output: ollama_input.json + to_score.json
```
Omit `--sources microsoft` and `--ms-jobs` if skipping Microsoft.

**Step 4 — Score + queue** (same as LinkedIn pipeline)
```bash
python3 scripts/pipeline/run_ollama_local.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/ > /tmp/ollama_<ID>.log 2>&1 &

python3 scripts/pipeline/build_queue.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Adding a new source** — edit `scripts/pipeline/fetch_direct_companies.py`:
1. Write `_fetch_<name>(args, max_pages) → list[dict]` — required fields: `id` (`"source:raw_id"`), `source`, `title`, `company`, `location`, `description` (full JD text), `url`, `posted` (ISO-8601 or None)
2. Add source-specific CLI args to `_parse_args()` if needed
3. Register it: one line in `_build_dispatch()` → `"name": lambda: _fetch_name(...)`

**Filters applied** (same as LinkedIn path):
1. `seen_jobs` dedup — IDs in `data/pipeline/seen_jobs.json`
2. `companies_avoid` — exact name list
3. `redflag_companies` — regex + exact patterns
4. `role_skip_patterns` — from `candidate_profile.json`
5. Seniority pre-cap — Lead/Principal/Staff/Architect/Manager

---

## Step 1 — Live fetch (Tier 1)

```bash
python scripts/fetch_jobs.py \
    --departments software,engineering,technology \
    --since-days <ceil(cfg.window_hours / 24), min 1> \
    --adzuna-country in --adzuna-id "$ADZUNA_ID" --adzuna-key "$ADZUNA_KEY" \
    --out jobs.json
```

Jobs are kept by **department**, not keyword. One run sweeps India + remote + visa.
Add `--remote` and/or `--visa` to hard-filter. Omit the Adzuna flags to skip it
(free key from developer.adzuna.com unlocks the strongest India source). Map
`cfg["target_titles"]` to the relevant departments.

`--sources all` (the default) also pulls **Google careers** and **Amazon
jobs** directly — both are clean, keyless, no-auth Tier 1 sources (see
`references/sources.md` for the confirmed filter params and the caveats:
Amazon's `country=IND` must be bare, not `country[]=IND`; its
`category[]=software-development` facet still lets some manager titles
through).

## Step 1b — Microsoft careers (browser-assisted, optional)

Microsoft's careers site (`apply.careers.microsoft.com`, Eightfold-powered) is
a client-rendered SPA that cannot join `fetch_jobs.py` directly — but a real
authenticated tab can. **Verified live via Claude-in-Chrome (2026-07-04):**
the frontend does NOT use `/api/apply/v2/jobs` (that path 403s
`"Not authorized for PCSX"` even with real session cookies — it's dead/legacy,
found by guessing). The real endpoints, found via `performance.getEntriesByType
('resource')` in a live tab, are `/api/pcsx/search` (job list) and
`/api/pcsx/position_details` (full JD per job) — both plain same-origin
`fetch(..., {credentials:'include'})` calls, no anti-bot token needed beyond
normal session cookies.

1. Open the search URL in a browser tab (no login needed to browse — only
   applying needs an account):
   ```
   https://apply.careers.microsoft.com/careers?query=Software+Engineer&start=0
     &location=India%2C+Multiple+Locations%2C+Multiple+Locations
     &sort_by=timestamp&filter_include_remote=1
     &filter_career_discipline=Software+Engineering
     &filter_employment_type=full-time&filter_profession=software+engineering
     &filter_seniority=Mid-Level
   ```
2. Paste `scripts/browser/scrape_microsoft_careers.js` into DevTools console
   (or Claude-in-Chrome's `javascript_tool`).
3. It calls `/api/pcsx/search` (paginated — **hard-capped at 10 results per
   page** regardless of the requested `num`), then fans out to
   `/api/pcsx/position_details` per job (5 concurrent) for the full JD.
4. Poll `window.__MS_DONE`; auto-downloads `ms_jobs.json` —
   `{id, title, company, location, url, description, posted, employment_type,
   work_site, roletype}`. **`roletype` is "Individual Contributor" vs a
   people-manager track** — a cleaner signal than Amazon's category facet for
   dropping management titles, use it the same way.

Confirmed end-to-end in a live session: 15/15 jobs, full JD text (avg ~5KB),
zero errors, one query = one script run (search + all JDs, no manual
second step needed). Output already carries JD text, so it plugs straight
into Step 3 below like any other keyless source — no separate JD-fetch pass
required (unlike the LinkedIn browser path, which splits scrape/JD-fetch into
two scripts because of volume).

**This is a lightweight browser assist, not the LinkedIn-style Path A.** It
doesn't need a Microsoft login (only applying does), doesn't use
`new_run.py`/Ollama/`filter_jobs.py`, and its output merges straight into this
keyless flow — don't route a Microsoft request through
`references/path-browser.md`. One open caveat: the live verification above ran
in a tab **already logged into a Microsoft candidate account** (results were
personalized). Whether `/api/pcsx/search`/`position_details` also work fully
logged-out is unconfirmed — if a logged-out tab 401s/403s, that's the thing to
resolve, not a sign the endpoints moved again.

## Step 2 — Browse links (Tier 2)

```bash
python scripts/search_urls.py \
    --keywords "backend engineer haskell rust" \
    --location "Bengaluru" --remote --since-days 7 \
    --category general,tech --out search_links.md
```

ToS-safe deep links grouped by `--category` (general, tech, remote, freshers,
bluecollar, freelance, all). Match the category to the candidate's level.

## Step 3 — Hand to the backbone

Candidates already carry JD text, so scoring uses `scripts/score_jobs.py`
(dictionary ATS + optional LLM required-vs-preferred re-weight; see
`references/scoring.md`). Then run `references/backbone.md` (dedup → red-flag →
YoE split → persist + queue). Writes `data/pipeline/APPLY_QUEUE.md`.
