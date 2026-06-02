# Method-gated job-hunter skill — design

**Date:** 2026-06-02
**Status:** Approved (brainstorming) — ready for implementation plan

## Problem

`SKILL.md` today is a single linear pipeline (profile → decide mix → `fetch_jobs.py`
→ `search_urls.py` → optional Apify → `score_jobs.py` → optional LLM-weight →
present). Two problems:

1. **No upfront method choice.** Apify is an optional sub-step; the keyless
   public-API fetch always runs first. There is no "pick a source method, then
   the whole run follows it."
2. **The Claude-Code + voyager browser flow is not in the skill at all.** The
   authenticated LinkedIn run developed in practice (voyager ID scrape → voyager
   JD fetch → fan-out scoring → tailor) plus its run machinery (persistent dedup,
   red-flag company blocklist, YoE primary/stretch split, mark-applied, the
   timestamped run folder + queue format) lives only in conversation history and
   `README.md`. A fresh `/job-hunter` invocation cannot reproduce it.

## Goal

Restructure the skill into a **method-gated router**: every invocation explicitly
asks which source method to use, the chosen path drives the pull, and all paths
feed a single shared backbone (dedup → red-flag → score → YoE split →
queue/applied). Run knobs move into a dedicated `hunt_config.json`.

## Decisions (locked during brainstorming)

1. **3-way gate:** A) Browser (Claude-in-Chrome + voyager), B) Apify, C) Keyless
   public APIs + ToS-safe links.
2. **Always ask explicitly** — the gate is shown every run regardless of phrasing.
3. **Shared backbone for all paths** — paths differ only in *how* they pull;
   everything after the pull is identical.
4. **Separate `hunt_config.json`** for run knobs; `profile.json` stays skills-only.
5. **Structure = Approach B** — thin router `SKILL.md` + one reference file per
   path + an externalized `backbone.md`.

## Architecture

`SKILL.md` is a thin router that always performs five steps:

```
1. Load hunt_config.json (run knobs) + profile.json (skills / HAVE set)
2. Ask the 3-way method gate:  A) Browser   B) Apify   C) Keyless
3. Open the chosen path's reference file → run its PULL steps
        → normalized candidates [{id, title, company, url, kw}]
4. Run the SHARED BACKBONE (references/backbone.md)
5. Present results + offer the resume-builder handoff
```

The model loads exactly **one** path reference per run; the gate and backbone are
constant. The keyless and Apify paths reuse today's scripts; the browser path is
newly documented.

## Components & files

| File | Status | Role |
|------|--------|------|
| `SKILL.md` | rewrite | Router: front-matter (triggers unchanged) → config load → gate → path handoff → backbone → present. Lean. |
| `references/path-browser.md` | new | Voyager `voyagerJobsDashJobCards` ID scrape (paginated, CSRF from JSESSIONID); build `/jobs/view/<id>` links; **voyager `jobPostings` JD fetch (never WebFetch)**; `get_page_text` chunked transfer trick (<50KB chunks); parallel scoring fan-out; re-fetch any `fetched:false` rows before trusting the distribution. |
| `references/path-apify.md` | rename/extend `apify.md` | Apify path: actor discovery, token from env, pull, normalize to shared schema. |
| `references/path-keyless.md` | new | Keyless path: `fetch_jobs.py` (Adzuna + public APIs) + `search_urls.py` (ToS-safe browse links). |
| `references/backbone.md` | new | The shared post-pull stage (see contract below). |
| `references/scoring.md`, `references/sources.md` | keep | Unchanged. |
| `assets/hunt_config.example.json` | new | Tracked template for `hunt_config.json`. |
| `scripts/pipeline/yoe_split.py` | new | Parse minimum YoE from a JD; classify a match as Primary (`min <= threshold` or no explicit min) vs Stretch (`min > threshold`). |
| `scripts/pipeline/dedup.py`, `pre_filter.py`, `mark_applied.py` | keep | Already implement dedup, red-flag filtering, applied-tracking. |
| `data/pipeline/hunt_config.json` | user-created | Real run config (git-ignored, like all of `data/`). |

## `hunt_config.json` schema

```jsonc
{
  "window_hours": 5,                       // browser TPR (e.g. r18000); keyless --since-days
  "target_titles": ["Software Engineer", "Software Development Engineer",
                    "Member of Technical Staff"],
  "geo_id": "102713980",                   // LinkedIn India
  "experience_filters": ["3", "4"],        // LinkedIn f_E: mid-senior + associate
  "yoe_threshold": 3,                       // min stated YoE > this → Stretch section
  "score_threshold": 70,                    // match / resume-tailor cutoff
  "dictionary": "assets/skills_dictionary.json",
  "redflag_path": "data/pipeline/redflag_companies.json",
  "seen_path": "data/pipeline/seen_jobs.json",
  "apify_actor": "curious_coder/linkedin-jobs-scraper"
}
```

A loader returns these values with sensible defaults when the file or any key is
missing (so the skill still runs without a config).

## Shared backbone contract

The backbone is the well-defined interface every path targets.

- **Input:** normalized candidates `[{id, title, company, url, kw}]` +
  `hunt_config` + `profile`.
- **Steps:**
  1. **Dedup** vs `seen_jobs.json` (`dedup.py`) — drop anything already seen or
     `status:"applied"`.
  2. **Red-flag filter** (`pre_filter.is_redflag_company`, backed by
     `redflag_companies.json`) — drop banned companies before fetch/score.
  3. **Score** — the scoring *mechanism* is the one place a path may differ, but
     the *output contract* (each job gets a numeric `score` + matched/gap skills)
     is identical. Keyless/Apify use the dictionary ATS (`score_jobs.py` /
     `lib/ats.py`) with the optional LLM required-vs-preferred re-weight; the
     browser path, having fetched full JD text inline, LLM-scores each JD against
     the rubric (`references/scoring.md`). Both emit the same `jobs_scored` shape,
     so every downstream backbone step is path-agnostic.
  4. **Split** matches `>= score_threshold` into **Primary** vs **Stretch** by
     `yoe_split.py` against `yoe_threshold`; record **all** scored IDs in
     `seen_jobs.json` (stretch roles stay deduped out of future runs).
- **Output:** `jobs_scored.json`, `matches.json` (each match tagged `min_yoe` /
  `stretch`), updated `seen_jobs.json`, and a queue markdown with two sections
  (Primary; Stretch — "JD states a min > N yrs"). Browser path writes
  `BROWSER_QUEUE.md`; Apify/keyless write `APPLY_QUEUE.md`.

`mark_applied.py` is the inverse step the user runs after ticking
`- [x] Applied` in a queue: it promotes those IDs to `status:"applied"` in
`seen_jobs.json` and strikes them from the queue.

## Data flow (all paths)

```
PULL (path-specific) ─┐
                      ├─► normalized candidates
                      │
           ┌──────────┴── SHARED BACKBONE ──────────┐
           │ dedup → red-flag → score → YoE split    │
           │ → record seen → write queue (Primary/Stretch)
           └──────────┬──────────────────────────────┘
                      ▼
            present + offer resume tailoring (≥ score_threshold)
```

## YoE split rule (formalized from practice)

- Parse the JD's stated **minimum** YoE: "3-4 yrs"→3, "4-6 yrs"→4, "5+"→5, "7+"→7.
- `min <= yoe_threshold` OR no explicit numeric minimum (incl. bare "Senior"
  titles with no number) → **Primary**.
- `min > yoe_threshold` → **Stretch** (annotated with the YoE label).
- When a JD contradicts itself (header vs qualifications), the higher stated
  minimum wins (e.g. "Desired Experience 5+ years" header beats "3-5 years" body).
- This is triage/presentation only — it does **not** change the ATS score.

## Testing

Extend the existing stdlib `unittest` suite (no new deps):

- `hunt_config` loader — defaults applied when file/keys missing.
- `yoe_split` — min-YoE parsing across phrasings; Primary/Stretch classification;
  contradictory-JD (header-wins) case.
- Red-flag filtering and dedup keying are already covered.

## Scope / non-goals (YAGNI)

- **No** unified CLI orchestrator for the browser path — it is inherently
  Claude-driven and interactive. The reference documents the steps; scripts own
  only the deterministic backbone bits.
- **No** new job sources or scoring model.
- **No** rewrite of the existing `score_jobs.py` / `lib/ats.py` scoring core.

## Risks

- **Voyager endpoint drift** — LinkedIn may change the `voyagerJobsDashJobCards` /
  `jobPostings` shapes. `path-browser.md` must keep the decoration IDs and the
  JSON-shape probes (e.g. `elements[].jobCardUnion['*jobPostingCard']`) close to
  the surface so they are easy to repair.
- **WebFetch regression** — the skill must state plainly that LinkedIn JDs are
  fetched via the authenticated voyager API, never WebFetch (which walls and
  silently zeros good jobs).
