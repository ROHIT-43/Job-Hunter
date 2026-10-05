# job-hunter

> **Live site:** an hourly GitHub Actions job scrapes LinkedIn's public job search
> for 0–2 YoE software roles in India and publishes them, grouped by salary, at
> <https://rohit-43.github.io/Job-Hunter/>. See [Hourly jobs website](#hourly-jobs-website).

A reusable [Claude Code](https://claude.com/claude-code) **skill** that finds,
aggregates, and ranks software / tech job openings across the Indian market
(Naukri, LinkedIn, Instahyre, Hirist, foundit) and international roles that are
remote or visa-sponsored (RemoteOK, Remotive, Arbeitnow, Himalayas, Wellfound,
Adzuna, company career pages).

Each run starts by asking **which source method** to use — **Browser**
(Claude-in-Chrome + voyager), **Apify** (actor pull), or **Keyless** (public APIs +
ToS-safe links) — then the chosen path feeds one shared backbone that dedups,
drops red-flag companies, scores against a candidate profile, splits matches by
years-of-experience, and produces a shortlist with apply links.

> **Information, not advice.** It surfaces and ranks openings; it makes no
> career or financial guarantees. It never scrapes sites that forbid it or
> bypasses bot protection — for those it emits search URLs you open yourself,
> or uses an Apify actor with your consent.

## Install

Drop the skill into your Claude Code skills directory:

```bash
git clone https://github.com/<you>/job-hunter.git
cp -R job-hunter ~/.claude/skills/job-hunter
```

Then in Claude Code: `/job-hunter` (or just ask "find me backend roles in
Bengaluru"). The `SKILL.md` front-matter handles auto-discovery.

## Layout

```
job-hunter/
├── SKILL.md                     # the skill: workflow Claude follows
├── references/
│   ├── backbone.md              # shared post-pull stage (dedup/red-flag/score/split/queue)
│   ├── path-browser.md          # Browser (Claude-in-Chrome + voyager) pull path
│   ├── path-apify.md            # Apify actor pull path
│   ├── path-keyless.md          # keyless public-API pull path
│   ├── sources.md               # every job source, access method, coverage
│   └── scoring.md               # the ranking formula and how to tune it
├── scripts/
│   ├── fetch_jobs.py            # live fetch by department from public APIs
│   ├── search_urls.py           # ToS-safe pre-filtered browse links
│   ├── apify_scrape.py          # pull LinkedIn/Naukri via Apify (token from env)
│   ├── score_jobs.py            # unified ATS scorer + company-tier ordering
│   ├── pipeline/                # the recurring (cron / browser) pipeline
│   │   ├── config.py            #   load hunt_config.json (run knobs) + defaults
│   │   ├── runner.py            #   orchestrates fetch → filter each run
│   │   ├── fetch_and_filter.py  #   fetch + normalize + pre-filter + dedup
│   │   ├── pre_filter.py        #   title / seniority / YoE / red-flag-company kills
│   │   ├── dedup.py             #   persistent seen-jobs store (also apply status)
│   │   ├── yoe_split.py         #   split matches into Primary / Stretch by YoE
│   │   ├── queue_writer.py      #   render the two-section match queue
│   ├── live/                    # hourly LinkedIn → website pipeline (GitHub Actions)
│   └── lib/                     # department.py, ats.py, paths.py (shared)
├── site/                        # the static jobs website (GitHub Pages)
├── live_config.json             # knobs for the hourly pipeline
├── .github/workflows/hourly-jobs.yml
├── .env.example                 # token template → copy to .env (git-ignored)
├── assets/
│   ├── departments.json         # department taxonomy (fetch filter)
│   ├── skills_dictionary.json   # master skill vocabulary (ATS detection)
│   ├── hunt_config.example.json # run-knobs template (→ data/pipeline/hunt_config.json)
│   └── candidate.example.json   # candidate profile template (skills feed ATS)
├── tests/                       # stdlib unittest suite (ats, dept, paths, config, yoe…)
└── data/                        # ⟵ you create this; git-ignored
    ├── profile.json             #    your real candidate profile (input)
    ├── resume/                  #    base resume .tex + bullet bank (tailoring)
    └── pipeline/                #    recurring-run state (see "Where state lives")
        ├── hunt_config.json     #      run knobs (window, titles, thresholds, paths)
        ├── seen_jobs.json       #      dedup + apply-status store
        ├── redflag_companies.json #    banned-company blocklist
        ├── APPLY_QUEUE.md       #      scripted-run shortlist (tick to apply)
        ├── BROWSER_QUEUE.md     #      Claude-in-Chrome shortlist (tick to apply)
        └── browser_runs/<ts>/   #      per-run artifacts (raw, scored, matches, PDFs)
```

Scripts use only the Python standard library (Python 3.8+). Fetching needs
network egress enabled.

**Everything personal lives in `data/`, which is fully git-ignored** — your
profile, raw job dumps, and every generated report. The repo tracks only the
skill and the `*.example.json` templates.

## Quick start

```bash
# 1. Live fetch by department (Adzuna key optional; unlocks the India source)
python scripts/fetch_jobs.py \
    --departments software,engineering,technology \
    --location India --since-days 30 --out jobs.json

# 2. Score against your profile (copy the template first, then edit)
cp assets/candidate.example.json data/profile.json
python scripts/score_jobs.py jobs.json --profile data/profile.json \
    --top 50 --out-dir data/output

# 3. ToS-safe browse links for LinkedIn/Naukri/etc.
python scripts/search_urls.py --keywords "backend engineer haskell rust" \
    --location Bengaluru --category general,tech --out search_links.md
```

## Pulling LinkedIn / Naukri via Apify

For sites that forbid scraping, `scripts/apify_scrape.py` uses a maintained
[Apify](https://apify.com) actor to pull structured listings (pay-per-result).
The API token is read from the environment — **never** hardcoded or passed on
the command line:

```bash
cp .env.example .env          # then put your real APIFY_TOKEN in .env (git-ignored)

python scripts/apify_scrape.py \
    --actor curious_coder/linkedin-jobs-scraper \
    --departments software,engineering,technology \
    --location India --rows 50 \
    --out data/linkedin_export.json
```

Token resolution order: `APIFY_TOKEN` env var → a `.env` file in the CWD or repo
root. Actor input field names vary per actor — start a small `--rows 25` run to
validate output, then scale. Use `--input-file data/actor_input.json` when an
actor needs a custom input schema. The output is normalized to the shared schema,
so it drops straight into the scorer alongside the keyless fetch:

```bash
python scripts/score_jobs.py data/linkedin_export.json jobs.json \
    --profile data/profile.json
```

> Apify actors run against the target sites' ToS — that is the user's
> responsibility. Never feed account credentials to a login-walled actor.

## Unified ATS scorer with company-tier ordering

`scripts/score_jobs.py` (backed by `scripts/lib/ats.py`) scores **every** source
the same way — in the **ATS direction**, *how much of what this JD asks for do
you already have?* —

```
ATS % = skills you HAVE that the JD mentions ÷ ALL skills the JD mentions
```

JD skills are master-dictionary terms (`assets/skills_dictionary.json`) detected
in the JD text, so the score is identical whether a job came from Adzuna, a
remote board, or an Apify LinkedIn pull. Results are **ordered by ATS match
first, company prestige second**:

```bash
# 1. Describe yourself once (copy the template, then edit)
cp assets/candidate.example.json data/profile.json

# 2. Score one or more normalized job files against your profile
python scripts/score_jobs.py jobs.json data/linkedin_export.json \
    --profile data/profile.json --top 100
# → data/output/report.md + data/output/jobs_ranked.csv
```

`--out-dir` defaults to `data/output`. Pass any number of job JSON files; they
are merged and deduped on (title, company) before scoring.

**Sort key (all descending):** `high-signal-first → ats_pct → tier →
have_count → recency`. ATS match stays primary; the company tier only breaks
ties between equal-ATS roles, and JDs mentioning fewer than 3 detected skills are
flagged low-signal and sink below high-signal roles.

### Your skills come from the candidate profile

`score_jobs.py` reads your skills from the profile JSON
(`assets/candidate.example.json` is the template):

```jsonc
{
  "name": "Your Name",
  "title": "Backend Engineer",
  "years_experience": 4,
  "skills": ["python", "go", "rust"],            // baseline HAVE skills
  "experience": [
    { "company": "Acme", "role": "SWE", "start": "2022-06", "end": "present",
      "skills": ["kafka", "aws", "grpc"], "highlights": ["..."] }
  ],
  "projects": [
    { "name": "raft-kv", "description": "...", "skills": ["rust", "distributed systems"] }
  ]
}
```

- **HAVE** = the union of `skills[]` + every `experience[].skills[]` +
  every `projects[].skills[]`.
- **JD skills** = master-dictionary terms found in the JD text.
- **GAP** = the JD skills you do not have (`JD − HAVE`) — derived per job, not
  declared up front.

So `ATS %` answers: *of the skills this JD asks for, how many can I evidence
from my own experience and projects?*

| Tier | Meaning | Examples |
|------|---------|----------|
| **T1** | most renowned big tech | Google, Apple, Microsoft, Amazon, Adobe, Walmart Global Tech |
| **T2** | renowned startups / unicorns | Razorpay, Swiggy, Stripe, Databricks, Postman |
| **·** | neutral (unrecognised, incl. large IT-services firms like TCS/Infosys) | — |
| **⚠️** | likely **< 100-dev** shop — sinks to the bottom of its ATS band | staffing / consultancy / HR-solutions firms |

### How tiers are decided (and the honest caveat)

LinkedIn/Apify data exposes `companyName` / `sector` but **no employee or
developer count**, so prestige and org size can't be read from the data. The
tiers are **curated, in-file lists** plus a name/sector heuristic for the
red flag — extend them as you learn more:

- `TIER1_NAMES`, `TIER2_NAMES` — substring matches on the company name.
- `KNOWN_LARGE_NAMES` — IT-services giants (TCS, Infosys, Accenture, …) and
  product firms (HackerRank, …) that would otherwise trip a red-flag pattern;
  forced to **neutral** because they are clearly > 100 devs.
- `RED_FLAG_PATTERNS` / `RED_FLAG_SECTORS` — "staffing", "consultancy",
  "recruiting", etc. The red flag is a *hint, not a verdict*.

All of these are plain Python sets near the top of the file. Edit them to fit
your market.

## Claude-in-Chrome browser runs

For LinkedIn — which forbids scraping and walls guest fetches — the skill can run
an **authenticated, in-browser** hunt through Claude's Chrome integration. You stay
logged into your own LinkedIn session; nothing is automated against a login you
don't control. The flow:

1. **Scrape job IDs** for a time window (e.g. last 5h = `f_TPR=r18000`) across the
   target titles via the authenticated `voyagerJobsDashJobCards` endpoint —
   page-context `fetch()` using your session's CSRF token. IDs only, paginated.
2. **Build candidate links** — `https://www.linkedin.com/jobs/view/<jobId>`.
3. **Pre-filter** obvious non-fits by title/company (reuses `pre_filter.py`'s
   red-flag-company and title kills) and **dedup** against `seen_jobs.json`.
4. **Fetch each JD** and score it against the profile, fanned out across parallel
   agents.
5. **Queue** every match ≥ 70 in `BROWSER_QUEUE.md` (`build_queue.py`); tailor a
   resume for any of them with the `tailor` skill.

> **Fetch JDs via the voyager API, not WebFetch.** `WebFetch` on
> `linkedin.com/jobs/view/<id>` frequently hits a login wall / HTTP 429 and returns
> nothing — which silently scores good jobs as 0. Use the authenticated
> `GET /voyager/api/jobs/jobPostings/<id>?decorationId=…WebFullJobPosting-65`
> endpoint instead (full `description.text`, title, company, location). After
> scoring, always re-fetch any `fetched:false` rows through voyager before trusting
> the distribution.

Each run writes a uniquely timestamped folder under
`data/pipeline/browser_runs/<date>_<time>_<window>/`:

| File | Contents |
|------|----------|
| `jobs_raw.json` | every scraped job (id, title, company, `jd_link`) |
| `candidates_fresh.json` | post-dedup, post-filter candidates fed to scoring |
| `jobs_scored.json` | all candidates with ATS score, matched/gap skills, JD summary |
| `matches.json` | the ≥ 70 shortlist, each with its tailored `resume.pdf` path |
| `<jobId>_<idx>/resume.{tex,pdf}` | the per-match tailored resume |

## Where state lives (dedup, applied, banned)

All cross-run state is small JSON/Markdown under `data/pipeline/` (git-ignored).
The *logic* is in `scripts/pipeline/`; the *data* is yours:

| Concern | Store (git-ignored) | Logic |
|---------|--------------------|-------|
| **Run knobs** — window, titles, thresholds | `data/pipeline/hunt_config.json` (template `assets/hunt_config.example.json`) | `scripts/pipeline/config.py` |
| **Dedup** — never re-process a job | `data/pipeline/seen_jobs.json` | `scripts/pipeline/dedup.py` |
| **Banned** — skip red-flag companies | `data/pipeline/redflag_companies.json` | `scripts/pipeline/pre_filter.py` |
| **YoE split** — stretch roles separate | tags on `matches.json` (`min_yoe`/`stretch`) | `scripts/pipeline/yoe_split.py` + `queue_writer.py` |
| **Shortlists** — what to apply to | `APPLY_QUEUE.md` / `BROWSER_QUEUE.md` | written by the run; ticked by you |

- **Run knobs**: `config.load_config()` reads `hunt_config.json` once at the top of
  every run (any path) and layers it over defaults — `window_hours`,
  `target_titles`, `geo_id`, `yoe_threshold`, `score_threshold`, and the store
  paths. Missing file/keys fall back to defaults, so it always runs.

- **Dedup** keys every job by its LinkedIn job ID (`li:<id>`, parsed from the URL),
  falling back to `title::company`. Once seen, a posting never resurfaces — even if
  its URL params change between runs.
- **Banned**: add a company to `redflag_companies.json` and every future run skips
  it **before** fetch/score (matched case-insensitively):

  ```jsonc
  {
    "patterns": ["stealth"],          // regex / substring on the company name
    "exact": ["Some Exact Co Pvt Ltd"]
  }
  ```

  `pre_filter.is_redflag_company()` loads this once and short-circuits
  `is_relevant()` — flagged companies are dropped with reason `"red-flag company"`.
- **YoE split**: matches whose JD states a minimum above `yoe_threshold` (your
  years) go into a separate **Stretch** section of the queue — still recorded in
  `seen_jobs.json` for dedup, just out of the main list. `yoe_split.split_matches()`
  tags each match `min_yoe`/`stretch`; `queue_writer.render_queue()` renders the two
  sections.

## Hourly jobs website

`.github/workflows/hourly-jobs.yml` runs `scripts/live/run.py` every hour and deploys
`site/` to GitHub Pages:

1. **Search** LinkedIn's public (guest, no-login) job search for every keyword in
   `live_config.json` across India, last `window_hours` (3h — overlaps the hourly
   cadence so a late or failed run leaves no gap). A keyword that hits LinkedIn's
   ~1000-result cap is re-searched per city in `split_locations`.
2. **Skip** anything already published (LinkedIn job ID, or same title + company + city
   reposted under a new ID), senior/management titles, and titles that aren't software
   roles (`software_only`; LinkedIn's keyword search is loose) — before any detail fetch.
3. **Fetch** each new job's description and parse its YoE requirement
   (`scripts/live/yoe.py`): ≤ `yoe_max` → *0–2 years*, nothing stated → *YoE not
   stated*, more → dropped.
4. **Salary**, first hit wins (the site labels each one):
   - *Listed* — stated in the posting (`scripts/live/salary.py` parses "₹12–18 LPA",
     "₹80K/month", …).
   - *Set manually* — `salary_overrides.json`.
   - *Web data* — `scripts/live/salary_lookup.py` runs **Claude Code headless**
     (`claude -p`, only WebSearch/WebFetch allowed) to find what that company pays
     for that role family + level in India (AmbitionBox, Glassdoor, Levels.fyi…),
     keeping only answers that cite real pages. One lookup per `company slug | family | level` (e.g.
     `razorpay|frontend|l1`), 5 per session, logged in with your Claude subscription
     (`CLAUDE_CODE_OAUTH_TOKEN`), capped at 100 per run / 600 per day so it leaves room
     in the plan's limits, cached ~90 days in `salary_cache.json` on the repo's **`data`
     branch**. Interns, staffing agencies and non-software titles are never looked up.
   - *Approx.* — the same company's SWE range while the exact role is pending.
   - otherwise *Not disclosed*.
   Bucketed by midpoint into 0–10 / 10–20 / 20+ LPA, plus a *Not disclosed* tab.
5. **Publish** `site/data/jobs.json`, dropping anything posted more than 24h ago.

The previous run's job list is read back from the published site; the salary cache
is the only thing the workflow commits (to the `data` branch, never `main`). Run locally
(salary lookups are skipped unless `SALARY_LOOKUP_LOCAL=1` is set, which uses your
local `claude` login):

```bash
python3 scripts/live/run.py --force           # writes site/data/jobs.json
python3 -m http.server -d site 8000           # open http://localhost:8000
```

**One-time setup:** repo *Settings → Pages → Source: GitHub Actions*, and run
`claude setup-token` locally and save the token as the Actions secret
`CLAUDE_CODE_OAUTH_TOKEN` (salary lookups use your Claude subscription). To change how
often it fires, edit the `cron` line in the workflow; `interval_hours` in
`live_config.json` additionally skips runs that come too soon.

## Privacy

This repository is the **reusable skill only** — no resumes, application
trackers, or job dumps. The entire `data/` directory (your `profile.json`, raw
`linkedin_*.json` exports, and every generated report under `data/output/`) is
git-ignored, with extra belt-and-suspenders patterns for `master.md`,
`*tracker*.md`, etc. in case scripts are run from the repo root. Personal data
never lands in git — keep it that way.

## License

MIT — see [LICENSE](LICENSE).
