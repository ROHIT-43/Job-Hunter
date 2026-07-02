# Path A — Browser (LinkedIn Voyager, Ollama local scorer)

The authenticated, in-browser LinkedIn path. You stay logged into your own
session; no Apify credits, no API keys. Richest source — full JD text + company
staff count + applicant count.

> **Fetch JDs via the voyager API, NEVER WebFetch.** `WebFetch` on
> `linkedin.com/jobs/view/<id>` hits a login wall or HTTP 429 and silently
> returns nothing — scoring good jobs as 0. Always use the authenticated
> voyager endpoints below.

---

## Operational notes

### Calculating WINDOW_SECONDS
Set `WINDOW_SECONDS` to the gap in seconds since the **previous run's scraper was injected** (not since build_queue finished). Overlap is fine — `seen_jobs` dedup handles it in Step 3.

```
# Example: last scraper ran at 17:18 IST, current time 20:01 IST
WINDOW_SECONDS = (20*3600 + 1*60) - (17*3600 + 18*60) = 9060   # ~2.5h
```

Common values: `3600`=1h, `7200`=2h, `14400`=4h, `86400`=24h.

### Browser session recovery
The Claude-in-Chrome tab group is **session-scoped** — it drops when the Claude Code conversation ends or the extension disconnects. At the start of every pipeline run:

```javascript
// Step 1: get or create tab group
tabs_context_mcp(createIfEmpty=true)

// Step 2: if tab is "New Tab", navigate to LinkedIn
navigate(tabId, "https://www.linkedin.com/jobs/")

// Step 3: verify auth before injecting any script
const csrf = (document.cookie.match(/JSESSIONID="?(ajax:[0-9-]+)"?/) || [])[1];
csrf ? "auth ok" : "NOT LOGGED IN — user must log in first"
```

### Download file naming
Chrome appends ` (N)` to duplicate filenames. After multiple runs, downloads accumulate as `to_score.json`, `to_score (2).json`, …, `to_score (14).json`. **Always pick the newest file:**

```bash
ls -lt ~/Downloads/to_score*.json | head -1   # newest first
ls -lt ~/Downloads/ollama_input*.json | head -1
```

### Red-flag companies maintenance
Staffing agencies and job-board aggregators (Hired, hackajob, TekPillar, HireFeed, Uplers, etc.) post on behalf of clients — not real direct openings. Add them to `data/pipeline/redflag_companies.json` under `patterns` (regex) or `exact`. They are dropped in Step 3 before JD fetch, saving Ollama quota.

Signs a company is a job board / staffing aggregator:
- Multiple roles with identical titles across many different "clients"
- Company name contains "consulting", "staffing", "talent", "solutions", "hire*"
- JD says "our client" or "we are hiring on behalf of"

---

## Prerequisites

- Authenticated LinkedIn tab open in the browser
- Ollama running locally: `ollama serve` + `ollama pull qwen2.5-coder:14b`
- `candidate_profile.json` at the repo root (copy from `assets/candidate_profile.example.json`)
- `data/pipeline/seen_jobs.json` exists (create with `echo '{}' > data/pipeline/seen_jobs.json`)

---

## Step 1 — Scaffold a new run directory

```bash
python3 scripts/new_run.py --window 2h   # or 4h, 24h, etc.
```

Creates `data/pipeline/browser_runs/<YYYY-MM-DD_HHMM_Xh_v1>/` and prints the
exact commands for steps 2-6. Run dir contains only data files — scripts live in
the repo and are never copied.

---

## Step 2 — Scrape job cards (`scripts/browser/scrape_linkedin_browser.js`)

**Configure at the top of the file:**
```javascript
const WINDOW_SECONDS = 7200;  // 1h=3600, 2h=7200, 4h=14400, 24h=86400
const KEYWORDS = ["sde", "software engineer", "sde2", "swe", "mts",
                  "backend engineer", "full stack developer", "software developer",
                  "devops engineer", "cloud engineer"];
const LOCATION = "India";
```

**Voyager search endpoint (per keyword, paginated):**
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

**Critical rules:**
- `count=100` per page, paginate `start += 100` up to `start=950` (LinkedIn caps at 1000 results/keyword)
- **NEVER add `experience:List(...)` to the query** — silently drops ~21% of untagged big-tech roles. Gate YoE only downstream via JD text.
- Headers: `csrf-token: <JSESSIONID cookie>`, `x-restli-protocol-version: 2.0.0`, `accept: application/vnd.linkedin.normalized+json+2.1`, `credentials: include`

**Output per job** (extracted from `included[]` + `data.elements[]`):
`{id, title, company, location, listedAt, keyword}`

Script auto-downloads as `to_score.json` via blob click. Move to the run dir.

---

## Step 3 — Pre-fetch filter (`scripts/pipeline/filter_jobs.py`)

Runs entirely on `to_score.json` (no network). Saves ~70% of JD fetch + Ollama work.

```bash
python3 scripts/pipeline/filter_jobs.py \
    --run-dir data/pipeline/browser_runs/<RUNDIR>/
```

**Filters applied in order:**

| # | Filter | Source |
|---|--------|--------|
| 1 | seen_jobs dedup | `data/pipeline/seen_jobs.json` — strips `li:` prefix |
| 2 | companies_avoid | `data/pipeline/companies_avoid.txt` — exact name, case-insensitive |
| 3 | redflag_companies | `data/pipeline/redflag_companies.json` — regex patterns + exact |
| 4 | role_skip_patterns | `candidate_profile.json` — SRE, intern, support, embedded, etc. |
| 5 | seniority pre-cap | `seniority_cap_pattern` from profile — Lead/Principal/Staff/Architect/Manager/Head/Chief cap at ≤63, can never reach score≥70 |
| 6 | walk-in / spam titles | walk-in, urgent joiner, bulk hire, day-drive |
| 7 | specific-title dedup | collapse exact-dup non-generic titles across companies (staffing spam) |

**Seniority rule (non-negotiable):** `Senior`/`Sr` is NEVER in the pre-cap filter — these score on merit. A "Senior Software Engineer" at Razorpay scores 82. Seniority-by-years is gated exactly once, in Step 6 via `min_yoe` from the JD.

Output: `to_fetch.json` — the filtered job list.

---

## Step 4 — Fetch full JDs (`scripts/browser/fetch_jds_browser.js`)

Inject `to_fetch.json` into the same LinkedIn tab, then paste the script:

```javascript
// Option A — paste JSON directly (small lists):
window.__TO_SCORE = [{"id": "...", "title": "...", ...}];

// Option B — load from local HTTP server:
const d = await fetch('http://localhost:8000/to_fetch.json').then(r => r.json());
window.__TO_SCORE = d;
```

**Voyager JD endpoint (10 concurrent, 400ms between batches):**
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
