# Path A — Browser (LinkedIn Voyager, Ollama local scorer)

The authenticated, in-browser LinkedIn path. You stay logged into your own
session; no Apify credits, no API keys. Richest source — full JD text + company
staff count + applicant count.

> **Fetch JDs via the voyager API, NEVER WebFetch.** `WebFetch` on
> `linkedin.com/jobs/view/<id>` frequently hits a login wall / HTTP 429 and returns
> nothing — which silently scores good jobs as 0. Always use the authenticated
> voyager endpoints below. After scoring, re-fetch any `fetched:false` rows via
> voyager before trusting the distribution.

## Prereq

An authenticated Claude-in-Chrome LinkedIn tab (load the chrome tools via
ToolSearch; `tabs_context_mcp` first). The CSRF token is the `JSESSIONID` cookie
value (strip quotes). CDP `javascript_tool` calls time out ~45s, so self-limit
loops to ~35s and resume.

## Step 0 — Two-step identity confirmation (MANDATORY, before any scraping)

**Before making any API call, navigating to any site, or reading any data**,
you MUST pass BOTH gates in order:

### Gate 1 — Browser profile confirmation

1. Call `tabs_context_mcp` to get available tabs.
2. Detect the browser profile's **email/account** — check tab titles, URLs,
   or run JavaScript to read the logged-in account info (e.g. Google account
   email from the nav bar).
3. Show the user: "I detected browser profile: **[email/name]**. Can I access
   this browser? (yes/no)"
4. **Only proceed to Gate 2 if the user confirms "yes".** If no, stop.

### Gate 2 — LinkedIn account confirmation

5. Navigate to the LinkedIn tab and run JavaScript to extract the logged-in
   LinkedIn profile name and URL (e.g. from the nav bar's profile link or
   the `me` API endpoint).
6. Show the user: "LinkedIn account detected: **[Name]** ([profile URL]).
   Can I use this LinkedIn account for job scraping? (yes/no)"
7. **Only proceed to Step 1 if the user confirms "yes".** If no, stop and
   ask the user to switch LinkedIn accounts in the browser tab.

Both gates are **mandatory safety checks**. The browser gate prevents accessing
the wrong Chrome profile. The LinkedIn gate prevents scraping the wrong LinkedIn
account even within the correct browser. Never skip either gate.

## Step 1 — Scrape job IDs (paginated)

For each title in `cfg["target_titles"]`, page the job-card endpoint
(`window_seconds = cfg["window_hours"] * 3600`, e.g. 5h → `r18000`):

```
GET /voyager/api/voyagerJobsDashJobCards
  ?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-220
  &count=100
  &q=jobSearch
  &query=(
      origin:JOB_SEARCH_PAGE_OTHER_ENTRY,
      keywords:<kw>,
      locationUnion:(seoLocation:(location:India)),
      selectedFilters:(
        timePostedRange:List(r<WINDOW_SECONDS>),
        sortBy:List(DD)
      ),
      spellCorrectionEnabled:true
  )
  &start=0,100,...,950
```

**The `experience:List(...)` clause is OPTIONAL and OMITTED when
`cfg["experience_filters"]` is empty `[]` (the default).** LinkedIn's
experience-level filter returns ONLY jobs explicitly tagged with a selected
level, and big-tech reqs (Microsoft/Google/Amazon) frequently leave that field
blank — so the search-time filter silently drops ~21% of postings (incl.
untagged senior-company roles) before they reach the funnel. It is **redundant
and strictly lossy**: the backbone's JD-based YoE gate (`extract_min_yoe` vs the
3-yr threshold) already does this correctly by reading each JD's stated minimum,
and is a safe no-op when the minimum is unknown. Gate on YoE once, in the
backbone — never at search time. Only emit the `experience:` clause if
`experience_filters` is explicitly non-empty.

Headers: `csrf-token: <token>`, `x-restli-protocol-version: 2.0.0`,
`accept: application/vnd.linkedin.normalized+json+2.1`, `credentials: include`.

Extract the ID from each element at
`elements[].jobCardUnion['*jobPostingCard']` with regex `\((\d{6,})`. Pull
title/company best-effort from the `JobPostingCard` entities in `included`
(`primaryDescription` is the company). Paginate `start += 25` until
`start >= paging.total` **or** `start >= cfg["max_pages_per_title"] * 25`
(default 8 pages = 200 results per title). Dedup IDs across titles.

**Pagination depth matters.** LinkedIn ranks results by relevance/promotion, so
smaller companies get pushed to later pages. With 11 target titles × 8 pages,
this yields up to ~2200 raw candidates before dedup — enough to catch most
relevant postings. If `max_pages_per_title` is absent, default to 8.

## Step 2 — Build candidate links

`https://www.linkedin.com/jobs/view/<id>` for every scraped ID.

## Step 3 — Pre-filter (cheap, in-browser)

Drop obvious non-fits by title (Salesforce/SAP/.NET/QA/trainer/etc.) and dedup by
`(title, company)`. Red-flag companies are dropped in the backbone, but you may
also drop them here to save fetches.

**Location filter:** If `cfg["target_locations"]` is non-empty, drop any job whose
`formattedLocation` does not match at least one target location (case-insensitive
substring). "Remote" also matches jobs with "remote" in the title or location.
This saves voyager JD fetches for jobs in non-target cities.

**Seniority by TITLE — drop only the unambiguously-too-senior:** `Staff`,
`Principal`, `Lead` (incl. "Tech Lead"/"Delivery Lead"), `Architect`, plus pure
management (`Manager`/`Director`/`VP`/`Head`/`Chief`). **NEVER title-purge
`Senior`/`Sr` — they are scored on merit.** A "Senior Software Engineer" often
needs only 3 yrs and can be a top match (the rubric scores a Senior Razorpay role
at 82). Do NOT add a `Senior|Sr` clause to the triage drop regex, and do NOT drop
on level numerals (`II`/`III`) either. Seniority that depends on years is gated
**once, by the JD-based YoE rule** (`extract_min_yoe` vs the 3-yr threshold) — that
already removes the Senior roles that genuinely state 4-5+ yrs, without blindly
discarding the ones that don't. Pairs with [[yoe-section-rule]] and
[[no-search-time-experience-filter]]. (A 2026-06-04 run wrongly title-purged 48
Senior roles before scoring; corrected to this rule.)

**Source of truth for the drop set:** `scripts/pipeline/pre_filter.py`
(`_SENIORITY_KILL_RE` + `_STAFF_LEVEL_RE` + MTS guard), with `tests/test_pre_filter.py`
as the executable spec and `references/backbone.md` "Seniority gating" as the
rationale. Your inline JS triage regex MUST mirror that token set exactly — if you
change one, change the other and re-run the test.

## Step 4 — Fetch each JD (voyager)

```
GET /voyager/api/jobs/jobPostings/<id>
  ?decorationId=com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65
```

**Output per job:**
`{jd: "<full text>", title, company, staffCount, listedAt, applies}`

- `originalListedAt` preferred over `listedAt` (stable across reposts)
- `staffCount` from `included[]` Company entity (used for MNC +5 bonus)
- `numApplicants` covers external-apply jobs; `applies` covers Easy Apply

Script auto-downloads as `ollama_input.json`. Move to the run dir.

**Polling:**
```javascript
window.__JD_PROGRESS   // {done, total, errors}
window.__JD_DONE       // true when complete
```

---

## Step 5 — Score with Ollama (`scripts/pipeline/run_ollama_local.py`)

```bash
# Ollama must be running first:
ollama serve

python3 scripts/pipeline/run_ollama_local.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Single-step scoring** (triage was removed — all jobs go directly to full scoring):

Each job is scored on the full JD (up to 8000 chars) via a 6-step rubric:
1. Primary job function (what's 80% of the role?)
2. Hard gap check → `discard_reason=hard_gap_*` + score ≤ 45 if primary = gap
3. YoE gate → `discard_reason=yoe_gt3` if JD states min_yoe > `min_yoe_gate`
4. Required skill literal coverage (0-2 missing → 75-90, 3-4 missing → max 65, 5+ → max 50)
5. Seniority fit (Lead/Principal/Staff/Architect → hard cap `seniority_cap`, default 55)
6. Company size bonus (+5 MNC >1000 staff, +8 tier1 companies, never past step-4 cap)

**Why no triage?** The old 2000-char triage window caused false positives — JD boilerplate front-loaded irrelevant keywords (e.g. "business intelligence platform" in an Azure SWE role's company overview) that caused legitimate roles to be discarded before full context was read.

**Post-hoc Python caps** (enforced regardless of LLM output):
- Title matches `seniority_cap_pattern` → `min(score, seniority_cap + tier1_bonus_if_applicable)`
- tier1 companies get `+tier1_bonus` (default +8) before cap

Writes `scores_ollama.jsonl` (resumable — skips IDs already in file). Run in background:
```bash
python3 scripts/pipeline/run_ollama_local.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/ > /tmp/ollama_<RUNID>.log 2>&1 &
```

---

## Step 6 — Build queue (`scripts/pipeline/build_queue.py`)

```bash
python3 scripts/pipeline/build_queue.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Gates (applied in order):**
1. `score >= 70`
2. `min_yoe <= min_yoe_gate` (default 3)
3. `company.lower() not in companies_avoid.txt`
4. Title not in `role_skip_patterns`
5. ID in `ollama_input.json` — prevents bleed-over from copied run dirs

**Output:**
- Groups direct company roles by company, sorted by best score
- Separate "Via Staffing / Platforms" section for `middleman_companies` matches
- Prepends new section to `data/pipeline/BROWSER_QUEUE.md` with IST timestamp
- Updates `data/pipeline/seen_jobs.json` with all scored IDs (`li:<id>` keys)

---

## Run directory files

```
data/pipeline/browser_runs/<YYYY-MM-DD_HHMM_Xh_v1>/
  to_score.json       raw scrape output (Step 2)
  to_fetch.json       filtered list for JD fetch (Step 3)
  ollama_input.json   full JDs keyed by ID (Step 4)
  scores_ollama.jsonl scored records, one JSON per line (Step 5)
```

`data/pipeline/BROWSER_QUEUE.md` — queue file (prepended each run, gitignored)
`data/pipeline/seen_jobs.json` — dedup store across all runs, gitignored)

---

## candidate_profile.json key fields

| Field | Used by | Purpose |
|-------|---------|---------|
| `triage_stack` / `triage_not_in_stack` | triage prompt | Fast yes/no discard |
| `strengths[]` | score prompt | Literal skill lookup for match scoring |
| `hard_gaps[]` | score prompt | Hard-gap check (primary function → score ≤ 45) |
| `min_yoe_gate` | filter + build_queue | YoE threshold (default 3) |
| `seniority_cap` | run_ollama + build_queue | Max score for capped titles (default 55) |
| `tier1_bonus` | run_ollama | Bonus for tier1 companies (default 8) |
| `tier1_companies[]` | run_ollama | Regex list of premium companies |
| `middleman_companies[]` | build_queue | Regex list of staffing agencies |
| `role_skip_patterns[]` | filter + build_queue | Title regex kills (SRE, intern, support) |
| `seniority_cap_pattern` | filter + run_ollama | Regex for capped titles (never include Senior/Sr) |
| `avoid_companies_file` | filter + build_queue | Path to companies_avoid.txt |
| `seen_jobs_file` | filter + build_queue | Path to seen_jobs.json |
| `queue_file` | build_queue | Path to BROWSER_QUEUE.md |
