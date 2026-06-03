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

## Step 0 — Load config + profile

```python
import sys; sys.path.insert(0, "scripts")
from pipeline.config import load_config
cfg = load_config()   # window_hours, target_titles, geo_id, yoe_threshold, score_threshold, …
```

`hunt_config.json` (template: `assets/hunt_config.example.json`) holds every run
knob; both the profile and config feed **all** paths. Read `data/profile.json` for
the candidate's HAVE skills (`assets/candidate.example.json` is the template).

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
- **C →** `references/path-keyless.md`

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
- Offer the resume-builder handoff: "Want me to tailor your 1-page resume to any of
  these?" — if yes, invoke `resume-builder` with the chosen JD (matches
  `>= cfg["score_threshold"]`).
- After the user ticks `- [x] Applied` in the queue, run
  `python3 scripts/pipeline/mark_applied.py` to record those as applied (dedup
  filters them out forever).

## Reference files

- `references/backbone.md` — the shared post-pull stage (dedup/red-flag/score/split/queue)
- `references/path-browser.md` — Browser (voyager) pull path
- `references/path-apify.md` — Apify actor pull path
- `references/path-keyless.md` — keyless public-API pull path
- `references/scoring.md` — the unified ATS formula and the LLM required-vs-preferred re-weight
- `assets/scoring_rubric.md` — canonical LLM scoring rubric (skillset + penalties + caps + YoE + output contract); sent verbatim to every scoring subagent, schema-bounded 0–100, Sonnet-only
- `references/sources.md` — every source, access method, coverage
- `assets/hunt_config.example.json` — run-knobs template (→ `data/pipeline/hunt_config.json`)
- `assets/candidate.example.json` — candidate profile template (skills feed ATS)
