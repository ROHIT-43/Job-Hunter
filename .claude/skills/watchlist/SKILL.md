---
name: watchlist
description: >
  Check job openings at specific target companies against the candidate's profile.
  Use this skill when the user says "check my watchlist", "any openings at Google",
  "search target companies", "check my companies", "watchlist", or any variation of
  searching specific companies for jobs. Trigger on phrases like "check companies",
  "target companies", "dream companies", "specific companies", "watchlist".
---

# Company Watchlist

Scrapes official company career pages for openings, scores them against the
candidate profile, and writes ranked results to a dedicated output file.

## Step 0 — Load config + profile

```python
import json
with open("data/profile.json") as f:
    profile = json.load(f)
with open("data/pipeline/target_companies.json") as f:
    targets = json.load(f)
with open("data/pipeline/hunt_config.json") as f:
    cfg = json.load(f)
```

- **Target companies**: `data/pipeline/target_companies.json` — user-maintained list with `name` and `careers_url` per company
- **Candidate profile**: `data/profile.json` — skills, experience, gap_skills
- **Config**: `data/pipeline/hunt_config.json` — target_titles, yoe_threshold, score_threshold

If the user passes company names as arguments (e.g., `/watchlist Google Microsoft`),
filter to only those companies from the file. If no arguments and file is empty, ask
the user which companies to track.

## Step 0.5 — Two-step identity confirmation (MANDATORY, before any browser access)

Before using ANY browser tools (navigating, reading pages, executing JavaScript),
pass BOTH gates:

### Gate 1 — Browser profile confirmation

1. Call `tabs_context_mcp` to get available tabs
2. Detect the browser profile's **email/account** from tab titles, URLs, or
   visible account info
3. Show the user: "I detected browser profile: **[email/name]**. Can I access
   this browser? (yes/no)"
4. **Only proceed to Gate 2 if the user confirms "yes".** If no, stop.

### Gate 2 — Logged-in accounts confirmation

5. If any LinkedIn tab is open, detect the logged-in LinkedIn profile name/URL
   and show: "LinkedIn account detected: **[Name]** ([URL]). Can I use this
   account? (yes/no)"
6. If no LinkedIn tab is open (career-page-only scraping), skip Gate 2 but
   still confirm: "No LinkedIn detected — I'll only access career pages.
   Proceed? (yes/no)"
7. **Only proceed after explicit "yes".** If no, stop immediately.

Both gates prevent accidentally accessing the wrong browser profile or the
wrong LinkedIn account. Never skip them.

## Step 1 — Scrape each company's career page

Use Claude-in-Chrome browser tools to scrape each company's official career page.

For each company in the target list:

1. Open a new tab with `tabs_create_mcp` and navigate to the company's `careers_url`
2. Wait for the page to load, then use `read_page` or `get_page_text` to extract
   all visible job listings from the page
3. If the career page has search/filter functionality, use `form_input` to search
   for each of the `cfg["target_titles"]` (e.g., "Software Engineer", "Backend Engineer")
4. Extract job titles, job URLs (apply links), and any visible details (location,
   experience level, team) from the listings
5. For each matching job, navigate to the individual job posting page and use
   `get_page_text` to extract the full job description (JD)
6. Close the tab when done with that company

### Handling different career page formats

Career pages vary widely. Use these strategies:
- **Single-page listings** (e.g., Zerodha, Razorpay): Read the full page text and
  extract all engineering/tech roles
- **Search-based pages** (e.g., Google, Microsoft, Amazon): Use the search box to
  filter by target titles and location (Bangalore/India)
- **Paginated results**: Check for pagination and scrape at least the first 2-3
  pages of results
- **JavaScript-heavy SPAs** (e.g., Flipkart): Use `javascript_tool` to wait for
  content to render, or extract data from the DOM directly

### Filtering criteria

Keep only roles that:
- Match (even partially) one of the `cfg["target_titles"]`
- Are located in one of `cfg["target_locations"]` (e.g., Bangalore, Hyderabad,
  Gurugram, Remote) — case-insensitive substring match on the job's location field.
  If `target_locations` is empty, skip this filter.
- Have `min_yoe <= cfg["yoe_threshold"] + 1` or no stated minimum. For example,
  if `yoe_threshold` is 1, only keep roles requiring 0–2 years.
- Are NOT clearly senior-only (Lead/Principal/Staff/Director) unless no level is
  specified
- Are engineering/tech roles (skip HR, marketing, sales, etc.)

## Step 2 — Score against profile

Score each job using the same rubric as job-hunter:
- ATS keyword overlap with `profile["skills"]`
- Penalties for stack mismatches (.NET/C#/Angular, SAP, etc.)
- Caps for QA roles, 5+ yrs, 7+ yrs, Lead/Principal/Staff
- Rewards for matching domain (fintech, microservices, etc.)
- Extract `min_yoe` from each JD
- Cross-reference with `profile["gap_skills"]` for gap identification

Output per job: `score`, `min_yoe`, `matched_skills`, `gap_skills`, `jd_summary`.

## Step 3 — Write results

Write results to **`data/pipeline/target_matches.json`** — sorted by score descending:

```json
[
  {
    "company": "Razorpay",
    "title": "Software Engineer - Backend",
    "score": 85,
    "min_yoe": 2,
    "matched_skills": ["java", "microservices", "postgresql", "redis", "aws"],
    "gap_skills": ["kafka"],
    "jd_summary": "Backend SWE for payments platform with Java/microservices",
    "url": "https://razorpay.com/jobs/backend-engineer-12345",
    "id": "razorpay-backend-12345"
  }
]
```

Also write **`data/pipeline/TARGET_QUEUE.md`** — a human-readable ranked queue:

```markdown
## Watchlist — <date> — <N> matches / <M> companies searched

### Matches (score >= threshold)
#### [85] Software Engineer - Backend — Razorpay
**Apply:** <url>
**Strengths:** java, microservices, postgresql, redis, aws
**Gaps:** kafka
> Backend SWE for payments platform
- [ ] Applied

### No openings found
- Google (0 matching roles)
- Zerodha (0 matching roles)
```

Group results by company. Companies with no matching openings go in a
"No openings found" section so the user knows they were checked.

## Step 4 — Update dedup + present

- Add all scored job IDs to `seen_jobs.json` (so `/job-hunter` won't resurface them)
- Present a summary: how many companies checked, how many openings found, top matches
- Offer `/tailor` for top matches

## Editing the watchlist

The user can edit `data/pipeline/target_companies.json` directly, or say:
- "add Google to my watchlist" → append to the companies array (must include `careers_url`)
- "remove Uber from my watchlist" → remove from the array
- "show my watchlist" → print the current list

When adding a new company, search the web for their official careers page URL and
add it in the format: `{ "name": "Company", "careers_url": "https://..." }`.

## What NOT to do

- Do NOT fabricate job listings — only return roles actually found on career pages
- Do NOT score jobs that are already in seen_jobs.json (dedup first)
- Do NOT mix results with the main job-hunter queue — watchlist has its own files
- Do NOT use LinkedIn for watchlist — always go to official career pages
- Do NOT spend more than ~2 minutes per company — if a career page is broken or
  unscrapeable, log it and move on
