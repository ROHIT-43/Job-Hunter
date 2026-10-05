# Shared backbone — the post-pull stage

Every path (browser / apify / keyless) ends by handing the backbone the same thing
and getting the same artifacts out. The pull paths differ only in *how* they
produce candidates; everything below is identical.

## Input contract

The path produces **normalized candidates**: a list of
`{id, title, company, url, kw}` dicts. The backbone also reads the loaded
`hunt_config` (run knobs) and `data/profile.json` (the candidate's HAVE skills).

```python
import sys, os
sys.path.insert(0, "scripts")
from pipeline.config import load_config
cfg = load_config()                 # window_hours, yoe_threshold, score_threshold, …
```

## Step 1 — Dedup against seen_jobs

Drop anything already processed or applied. The store is `cfg["seen_path"]`
(`data/pipeline/seen_jobs.json`).

```python
from pipeline import dedup
job_key = dedup.job_id(job)          # "li:<id>" from the URL, else "title::company"
```

Keep only candidates whose key is **not** in the store (any status), so a posting
never resurfaces across runs even if its URL params change.

## Step 1.5 — Location filter

If `cfg["target_locations"]` is non-empty, drop any job whose `location` field
does not contain at least one of the target location strings (case-insensitive).
"Remote" in the target list also matches jobs whose location or title contains
"remote". This filter runs **before** fetching JDs (cheap, saves API calls).

```python
target_locs = [loc.lower() for loc in cfg.get("target_locations", [])]
if target_locs:
    candidates = [c for c in candidates
                  if any(loc in (c.get("location","") + " " + c.get("title","")).lower()
                         for loc in target_locs)]
```

If `target_locations` is empty or absent, no location filtering is applied.

## Step 2 — Drop red-flag companies

```python
from pipeline.pre_filter import is_redflag_company
candidates = [c for c in candidates if not is_redflag_company(c["company"])]
```

`is_redflag_company` loads `cfg["redflag_path"]`
(`data/pipeline/redflag_companies.json`: `patterns` regex + `exact` names). To ban
a company, add it there — flagged companies are dropped **before** any fetch/score
with reason `"red-flag company"`.

## Step 3 — Score

Output contract (identical across paths): each job gets an integer `score` 0–100,
plus `matched_skills`, `gap_skills`, `min_yoe`, `jd_summary`.

- **Keyless / Apify:** candidates already carry JD text → `scripts/score_jobs.py`
  (dictionary ATS, `ATS% = JD skills you have ÷ all JD skills`, deterministic and
  bounded by construction) with the optional LLM required-vs-preferred re-weight
  (see `references/scoring.md`).
- **Browser:** the path fetched full JD text inline → LLM-score each JD (fan-out,
  batched). This MUST follow three rules so scores stay trustworthy:
  1. **Send the canonical rubric verbatim** — every scoring subagent receives the
     whole of `assets/scoring_rubric.md` (skillset + formula + penalties + caps +
     YoE + output contract + worked examples). Do not paraphrase it inline.
  2. **Bound the score in the schema** — the StructuredOutput `score` field MUST be
     `{type:'integer', minimum:0, maximum:100}`, so an out-of-range value (e.g.
     113) is rejected at the tool layer on any model.
  3. **Use Sonnet or better. Haiku is NOT allowed for scoring** — it mis-applies the
     penalty/cap arithmetic and emits false 100s (4h-run post-mortem). Haiku is for
     *tailoring* only.

Both emit the same `jobs_scored` shape, so every step below is path-agnostic.

## Step 4 — YoE gate (eligible vs excluded)

```python
from pipeline.yoe_split import split_matches
matches = [j for j in scored if j["score"] >= cfg["score_threshold"]]
primary, stretch = split_matches(matches, threshold=cfg["yoe_threshold"])
# ONLY `primary` is queued and tailored. `stretch` is dedup-only.
```

While scoring, **set `min_yoe` on each match** from your reading of the JD — it
handles word-numbers ("six years") and self-contradicting JDs (header-wins, e.g.
"Desired 5+ years" beats a "3-5 years" in the body). `split_matches` honors a
preset `min_yoe` and falls back to a digit parser otherwise.

**Hard YoE gate (cost-critical):** The eligible range is `0` to
`yoe_threshold + 1` (inclusive). For example, if `yoe_threshold` is 1, jobs
requiring 0–2 years are eligible; jobs requiring 3+ are excluded. Formally: a
role whose `min_yoe > yoe_threshold + 1` is **excluded entirely** — it is NOT
queued and **NOT tailored**. Its only footprint is its ID in `seen_jobs.json`
(dedup). Everything else (`min_yoe <= yoe_threshold + 1` or no explicit minimum /
bare "Senior") is eligible. Never spend tailoring tokens on a `stretch` role —
doing so is a wasted-cost mistake. This is a gate, not a re-score: the ATS score
is unchanged.

## Seniority gating — TWO layers, and only two (read before touching any filter)

Seniority is handled in exactly two places. Do not invent a third, and never
collapse them into a blanket "drop senior-sounding titles" rule.

1. **Title layer (pre-fetch, cheap) — drops only the unambiguously-too-senior.**
   By *title* you may drop `Lead` (incl. "Tech Lead"/"Delivery Lead"),
   `Principal`, `Staff`, `Architect`, `Distinguished`/`Fellow`, and pure
   management (`Manager`/`Director`/`VP`/`Head`/`Chief`). This is implemented once,
   canonically, in `scripts/pipeline/pre_filter.py` (`_SENIORITY_KILL_RE` +
   `_STAFF_LEVEL_RE`, with an MTS guard); the browser path's inline JS triage MUST
   mirror that exact token set. `tests/test_pre_filter.py` is the executable spec.

   **`Senior` / `Sr` / level numerals (`II`/`III`) are NEVER dropped by title.** A
   Senior SWE frequently needs only ~3 yrs and can be a top match (the rubric
   scores a Senior Razorpay role at 82). `Member of Technical Staff` is a *target*
   title (`hunt_config.target_titles`) — the "Staff" kill must not touch it.

2. **YoE layer (post-fetch, accurate) — the only seniority gate that reads years.**
   Step 4 below. A role whose JD-stated `min_yoe` exceeds `yoe_threshold + 1` is
   excluded — e.g. if `yoe_threshold` is 1, roles requiring 3+ yrs are excluded,
   roles requiring 0–2 yrs are eligible. This removes the Senior roles that
   genuinely want too many years, *after* reading the JD, without blindly
   discarding the ones that don't.

History: a 2026-06-04 run added a bogus `Senior|Sr` clause to the title layer and
purged 48 Senior roles before scoring. That conflated the two layers. The split
above is the fix. See `references/path-browser.md` Step 3 and the
`no-senior-title-purge` + `yoe-section-rule` memories.

## Step 5 — Persist + queue

- Record **all** scored IDs (primary, stretch, and below-threshold) in
  `seen_jobs.json` so dedup keeps filtering them — stretch roles included.
- Render the queue and write it:

```python
from pipeline.queue_writer import render_queue
md = render_queue(run_label, primary, stretch, scored_n=len(scored),
                  cand_n=len(candidates), threshold=cfg["yoe_threshold"])
```

  Browser path writes `data/pipeline/BROWSER_QUEUE.md`; Apify/keyless write
  `data/pipeline/APPLY_QUEUE.md`.
