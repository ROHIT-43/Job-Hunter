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

A **method-gated router**: every run asks which source method to use (Browser /
Apify / Keyless), the chosen path pulls candidates, then a single **shared
backbone** dedups, drops red-flag companies, scores, splits matches into
excluding roles whose stated minimum exceeds the candidate's years, and writes a
queue. Top matches optionally
hand off to `resume-builder` for per-JD tailoring.

## Ground rules (read first)

- **Respect site terms.** LinkedIn, Naukri, Indeed, Wellfound and similar sites
  forbid automated scraping and actively block bots. This skill never builds a
  stealth scraper or bypasses bot protection. For those sites it generates
  **pre-filtered search URLs** the user opens themselves, uses an **Apify actor**
  (`references/path-apify.md`) with consent, or runs the **authenticated browser
  path** in the user's own logged-in session.
- **LinkedIn JDs are fetched via the authenticated voyager API, never WebFetch.**
  WebFetch on `/jobs/view/<id>` walls (login/429) and silently scores good jobs 0.
- **Network is required** for fetching. Scripts use only the Python standard
  library but need egress. If a fetch fails with a network error, tell the user.
- This is **information, not advice.** Present matches; don't make guarantees.

## Primary workflow — LinkedIn Voyager pipeline (Browser path)

When the user says "run the pipeline", "run another pipeline", "scrape last Xh", or similar — **this is the primary workflow**. Do NOT use `fetch_jobs.py` or Apify for this. Always read `references/path-browser.md` first — it has all guardrails, endpoints, and operational notes.

**Quick reference (6 steps):**

**Step 1 — Create run dir**
```bash
python3 scripts/new_run.py --window 2h   # or 4h, 24h, etc.
# Prints exact commands for steps 2-6 with the correct --run-dir path
# WINDOW_SECONDS = seconds since previous run's scraper was injected
```

**Step 2 — Scrape** (user action in LinkedIn browser tab via Claude-in-Chrome)
- Update `WINDOW_SECONDS` in `scripts/browser/scrape_linkedin_browser.js`
- Inject via `javascript_tool` in authenticated LinkedIn tab → auto-downloads `to_score.json`
- Always pick the **newest** `to_score*.json` from Downloads (`ls -lt ~/Downloads/to_score*.json | head -1`)
- Move to run dir

**Step 3 — Filter**
```bash
python3 scripts/pipeline/filter_jobs.py --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Step 4 — Fetch full JDs** (user action in same LinkedIn tab)
- Inject `to_fetch.json` as `window.__TO_SCORE` via `javascript_tool`
- Inject `scripts/browser/fetch_jds_browser.js` → auto-downloads `ollama_input.json`
- Always pick newest `ollama_input*.json` from Downloads
- Move to run dir

**Step 5 — Score** (`ollama serve` must be running)
```bash
python3 scripts/pipeline/run_ollama_local.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/ > /tmp/ollama_<ID>.log 2>&1 &
# Single-step scoring — all jobs go directly to full JD score (no triage)
# Resumable — skips IDs already in scores_ollama.jsonl
```

**Step 6 — Build queue**
```bash
python3 scripts/pipeline/build_queue.py --run-dir data/pipeline/browser_runs/<RUNDIR>/
# Prepends to data/pipeline/BROWSER_QUEUE.md, updates seen_jobs.json
```

**Non-negotiable rules:**
- Never add `experience:List(...)` to the voyager query — silently drops ~21% of untagged big-tech roles
- Never drop `Senior`/`Sr` titles in seniority pre-cap — they score on merit
- `build_queue.py` scopes to `ollama_input.json` IDs — prevents bleed-over from copied run dirs
- Candidate profile lives at `candidate_profile.json` (repo root), not `data/profile.json`

---

## Secondary workflow — Direct companies pipeline (Google / Amazon / Microsoft)

When the user says "run direct companies", "fetch from Google/Amazon/Microsoft", or "no LinkedIn" — use this path. JD text is already present after fetch; no browser JD-fetch step needed. Always read `references/path-keyless.md` (top section) for the full filter list and "adding a new source" guide.

**Quick reference (4 steps):**

**Step 1 — Create run dir**
```bash
python3 scripts/new_run.py --window 7d --label direct_v1
```

**Step 2 — (Microsoft only) Browser scrape**
- Navigate to Microsoft careers search URL (see `references/path-keyless.md`)
- Inject `scripts/browser/scrape_microsoft_careers.js` → auto-downloads `ms_jobs.json`
- Poll `window.__MS_DONE`

**Step 3 — Fetch + filter**
```bash
python3 scripts/pipeline/fetch_direct_companies.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/ \
    --sources google,amazon,microsoft \
    --ms-jobs ~/Downloads/ms_jobs.json \
    --since-days 7 --max-pages 10
# Writes ollama_input.json directly — no separate filter_jobs.py or fetch_jds_browser.js
```

**Step 4 — Score + queue** (identical to LinkedIn steps 5–6)
```bash
python3 scripts/pipeline/run_ollama_local.py --run-dir data/pipeline/browser_runs/<RUNDIR>/ > /tmp/ollama_<ID>.log 2>&1 &
python3 scripts/pipeline/build_queue.py      --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Adding a new source** — one function + one line in `_build_dispatch()` in `fetch_direct_companies.py`. See module docstring for the required field schema.

---

## Step 0 — Load profile

The candidate profile lives at `candidate_profile.json` in the repo root.
Copy from `assets/candidate_profile.example.json` if it doesn't exist.
All pipeline scripts auto-discover it by walking up from the run directory.

## Step 1 — Build / confirm the profile

Derive `target_titles` and skills from the user's resume (the `resume-builder`
skill knows their stack) rather than asking them to retype. Otherwise collect
target role(s), key skills, seniority, locations, and the switches
(`remote_only`, `visa_required`, avoid-companies → red-flag list). Confirm the
filled profile in one line before searching.

## Step 2 — Method gate (ALWAYS ASK)

Ask explicitly, every run:

> **Which source method?**
> **A) Browser** — Claude-in-Chrome + voyager (authenticated LinkedIn; richest)
> **B) Apify** — actor pull (pay-per-result)
> **C) Keyless** — public APIs + ToS-safe browse links (free)

Then open the matching reference and run its **pull** steps to produce normalized
candidates `[{id, title, company, url, kw}]`:

- **A →** `references/path-browser.md`
- **B →** `references/path-apify.md`
- **C →** `references/path-keyless.md` (includes Google/Amazon career-page
  APIs as Tier 1 sources, and an optional lightweight Microsoft careers
  browser-assist in Step 1b — not the same as Path A's LinkedIn machinery,
  don't conflate the two)

## Step 3 — Shared backbone

Run `references/backbone.md` on the candidates: **dedup** vs `seen_jobs.json` →
drop **red-flag** companies → **score** (output contract: `score` +
`matched_skills`/`gap_skills`/`jd_summary`) → **YoE gate**: keep only matches
with `min_yoe <= cfg["yoe_threshold"]` (or no stated minimum); roles stating a
higher minimum are **excluded from the queue and never tailored** — record their
IDs in `seen_jobs.json` for dedup only → record all scored IDs in
`seen_jobs.json` → write the eligible-only queue (`BROWSER_QUEUE.md` for path A,
`APPLY_QUEUE.md` for B/C).

## Step 4 — Present

- Summarise the eligible match count (and how many >YoE roles were excluded) and the top handful by score.
- Offer the tailoring handoff: "Want me to tailor your 1-page resume to any of
  these?" — if yes, run the `tailor` skill with the chosen JD (matches
  `>= cfg["score_threshold"]`).

## Step 5 — Profile Hunter (optional, outreach)

A separate hunt shape for when the user hands you a **list of LinkedIn profile
URLs** (reactions/comments on a post, "people also viewed", a recruiter's
connections) instead of a job search. Screens each profile for someone
personally posting a hiring call that matches the candidate's YoE/seniority/
domain, then feeds tailored connection-note/InMail drafting. Doesn't touch
`BROWSER_QUEUE.md` or `seen_jobs.json`. See `references/path-profile-hunter.md`.

## Reference files

- `references/backbone.md` — the shared post-pull stage (dedup/red-flag/score/split/queue)
- `references/path-browser.md` — Browser (voyager) pull path
- `references/path-apify.md` — Apify actor pull path
- `references/path-keyless.md` — keyless public-API pull path
- `references/path-profile-hunter.md` — profile-list screening for outreach (would-be-hiring / referral-hunting)
- `references/scoring.md` — the unified ATS formula and the LLM required-vs-preferred re-weight
- `assets/scoring_rubric.md` — canonical LLM scoring rubric (skillset + penalties + caps + YoE + output contract); sent verbatim to every scoring subagent, schema-bounded 0–100, Sonnet-only
- `references/sources.md` — every source, access method, coverage
- `assets/candidate_profile.example.json` — candidate profile template (copy → `candidate_profile.json` at repo root)
- `assets/redflag_companies.json` — starter red-flag list (copy → `data/pipeline/redflag_companies.json`)
