# job-hunter

A reusable [Claude Code](https://claude.com/claude-code) **skill** that finds,
aggregates, and ranks software / tech job openings across the Indian market
(Naukri, LinkedIn, Instahyre, Hirist, foundit) and international roles that are
remote or visa-sponsored (RemoteOK, Remotive, Arbeitnow, Himalayas, Wellfound,
Adzuna, company career pages).

It pulls live listings from sources with clean public APIs, generates ToS-safe
pre-filtered browse links for the sites that forbid scraping, ranks everything
against a candidate profile, and produces a shortlist with apply links.

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
│   ├── sources.md               # every job source, access method, coverage
│   ├── scoring.md               # the ranking formula and how to tune it
│   └── apify.md                 # pulling LinkedIn/Naukri via Apify (consent-gated)
├── scripts/
│   ├── fetch_jobs.py            # live fetch from keyless/keyed public APIs
│   ├── search_urls.py           # ToS-safe pre-filtered browse links
│   ├── apify_scrape.py          # pull LinkedIn/Naukri via Apify (token from env)
│   ├── rank_jobs.py             # score + order listings against a profile
│   └── ats_scorer.py            # ATS-direction scoring + company-tier ordering
├── .env.example                 # token template → copy to .env (git-ignored)
├── assets/
│   ├── profile.example.json     # ranking profile template (rank_jobs.py)
│   └── candidate.example.json   # candidate profile template (ats_scorer.py)
└── data/                        # ⟵ you create this; git-ignored
    ├── profile.json             #    your real candidate profile (input)
    ├── linkedin_export.json     #    raw job export (input)
    └── output/                  #    generated reports (csv + md)
```

Scripts use only the Python standard library (Python 3.8+). Fetching needs
network egress enabled.

**Everything personal lives in `data/`, which is fully git-ignored** — your
profile, raw job dumps, and every generated report. The repo tracks only the
skill and the `*.example.json` templates.

## Quick start

```bash
# 1. Live fetch (Adzuna key optional but unlocks the strongest India source)
python scripts/fetch_jobs.py --keywords haskell,rust,backend \
    --location India --since-days 30 --out jobs.json

# 2. Rank against your profile (copy the template first, then edit)
cp assets/profile.example.json profile.json
python scripts/rank_jobs.py --jobs jobs.json --profile profile.json \
    --top 40 --out-md report.md --out-csv jobs_ranked.csv

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
    --keywords "backend engineer python rust" \
    --location India --rows 50 \
    --out data/linkedin_export.json
```

Token resolution order: `APIFY_TOKEN` env var → a `.env` file in the CWD or repo
root. Actor input field names vary per actor — start a small `--rows 25` run to
validate output, then scale. Use `--input-file data/actor_input.json` when an
actor needs a custom input schema. The output drops straight into the scorer:

```bash
python scripts/ats_scorer.py data/linkedin_export.json --profile data/profile.json
```

> Apify actors run against the target sites' ToS — that is the user's
> responsibility. Never feed account credentials to a login-walled actor.

## ATS scorer with company-tier ordering

`scripts/ats_scorer.py` scores LinkedIn/Apify exports in the **ATS direction** —
*how much of what this JD asks for do you already have?* —

```
ATS % = skills you HAVE that the JD mentions ÷ ALL skills the JD mentions
```

and then **orders results by ATS match first, company prestige second**:

```bash
# 1. Describe yourself once (copy the template, then edit)
cp assets/candidate.example.json data/profile.json

# 2. Score a job export against your profile
python scripts/ats_scorer.py data/linkedin_export.json \
    --profile data/profile.json --top 100
# → data/output/ats_full_report.md + data/output/ats_full_report.csv
```

`--profile` defaults to `data/profile.json` and `--out-dir` to `data/output`,
so once your profile is in place a bare `python scripts/ats_scorer.py
data/linkedin_export.json` just works. If no profile file exists, the script
falls back to built-in default skill sets and says so.

**Sort key (all descending):** `ats_pct → tier → have_count → recency`. ATS
match stays primary; the company tier only breaks ties between equal-ATS roles.

### Your skills come from the candidate profile

`ats_scorer.py` no longer hardcodes your skills — it reads them from the
profile JSON (`assets/candidate.example.json` is the template):

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
  ],
  "gap_skills": ["spring boot", "terraform"]      // skills you know you lack
}
```

- **HAVE** = the union of `skills[]` + every `experience[].skills[]` +
  every `projects[].skills[]`.
- **GAP** = the explicit `gap_skills[]`.
- Any JD keyword that is neither HAVE nor GAP is counted as a gap (conservative
  — it can only lower the score, never inflate it).

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

## Privacy

This repository is the **reusable skill only** — no resumes, application
trackers, or job dumps. The entire `data/` directory (your `profile.json`, raw
`linkedin_*.json` exports, and every generated report under `data/output/`) is
git-ignored, with extra belt-and-suspenders patterns for `master.md`,
`*tracker*.md`, etc. in case scripts are run from the repo root. Personal data
never lands in git — keep it that way.

## License

MIT — see [LICENSE](LICENSE).
