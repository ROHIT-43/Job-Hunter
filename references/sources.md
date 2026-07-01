# Job source catalog

Sources are tiered by how they can be accessed legitimately. Always prefer
Tier 1. Use Tier 2 only via the user's browser (search URLs) or an Apify actor.
Never build a stealth scraper that evades a site's bot protections.

## Tier 1 — clean public API / RSS (fetched by `scripts/fetch_jobs.py`)

| Source | Coverage | Access | Key needed | Notes |
|---|---|---|---|---|
| Adzuna | **India** + US/UK/DE/CA/AU… | REST API | yes (free) | Best programmatic source for the Indian market. Country code `in`. Register at developer.adzuna.com |
| RemoteOK | Global remote | Public JSON | no | Tech-heavy, good tag data |
| Remotive | Global remote | Public JSON | no | Supports `search=` |
| Arbeitnow | EU + global remote | Public JSON | no | **Has a `visa_sponsorship` flag** — valuable for sponsorship hunts |
| Himalayas | Global remote | Public JSON | no | Salary data often present |
| Jobicy | Global remote | Public JSON | no | Filter by tag |
| The Muse | Global (incl. India offices) | Public API | optional | Company + category data |
| We Work Remotely | Global remote | RSS | no | Programming feed |
| Google careers | Global (India via `location=`) | Public JSON (SSR blob) | no | `src_google_careers` — parses the `AF_initDataCallback` block the search page server-renders for SEO. Confirmed filters: `q` (quote for exact phrase), `location`, `target_level` (EARLY/MID/ADVANCED), `degree`, `employment_type`, `sort_by=date`. No login, no JS execution. |
| Amazon jobs | Global (India via `country=IND`) | Public JSON API | no | `src_amazon_jobs` — `amazon.jobs/en/search.json`. Department-native `category[]=software-development` facet (wired into `assets/departments.json`) beats free-text query. **`country=IND` bare works; `country[]=IND` is silently ignored** and falls back to a global search — confirmed by live testing. `sort=recent` is the real recency param (`sort_by=recency`/`sort=recency` are no-ops). Still returns some non-IC noise (e.g. "Software Development Manager") since the category facet is broader than pure engineering titles. |

To add a source: write an adapter in `fetch_jobs.py` returning records via the
`_norm(...)` helper, then register it in `ALL_SOURCES` (or as a `--sources`
special case if it needs explicit args, like `adzuna`/`google`/`amazon`).

**Microsoft careers** is deliberately left out of Tier 1: its site
(`apply.careers.microsoft.com`, Eightfold-powered) is a client-rendered SPA
with no SSR job data, so `fetch_jobs.py` can't reach it without a browser
session. It goes through the **browser path** instead
(`scripts/browser/scrape_microsoft_careers.js`, see `references/path-keyless.md`
Step 1b) — **verified live via Claude-in-Chrome (2026-07-04)**: the real
endpoints are `/api/pcsx/search` + `/api/pcsx/position_details` (found via
`performance.getEntriesByType('resource')` in a live tab; the earlier
`/api/apply/v2/jobs` guess was a dead path that 403s regardless of session).
Both work with plain same-origin `fetch(credentials:'include')` — no anti-bot
token juggling needed. One script run does search + full JD fan-out in one
pass: 15/15 jobs, complete JD text, zero errors in the live test. Also
carries `roletype` (Individual Contributor vs manager track) — cleaner than
Amazon's category-facet noise for dropping management titles.

## Tier 2 — ToS forbids scraping (use `search_urls.py` or Apify)

These portals block bots; never scrape them. `search_urls.py` builds
pre-filtered deep links the user opens themselves — the ToS-safe substitute.
For LinkedIn/Naukri, Apify actors can pull structured data with consent
(`path-apify.md`). Portals are grouped by `--category`.

| Category | Portals | Notes |
|---|---|---|
| general | Naukri, LinkedIn, Indeed (India), Foundit (Monster), Shine, TimesJobs, Glassdoor, Google Jobs, NCS | Naukri = largest India board; Google Jobs `&ibp=htl;jobs` opens the aggregator panel; NCS is the free government portal (form-based, landing link only) |
| tech | CutShort, Instahyre, Wellfound, Hirist, Hirect | Best for startup/dev roles; Hirect is app-first (landing link) |
| remote | LinkedIn (remote filter), Wellfound (remote), Google Jobs (remote) | |
| freshers | Internshala, Freshersworld | Internships + entry-level |
| bluecollar | Apna, WorkIndia | App-first, hyper-local (landing links) |
| freelance | Upwork | Global freelance |

Default category is `general,tech`. For a senior/experienced search, leave it
default; add `freshers`/`bluecollar` only when relevant. Filter parameters
(LinkedIn `f_WT`/`f_TPR`, Naukri `jobAge`/`wfhType`) change occasionally — if
one looks stale, the user adjusts it once in the UI and the rest still applies.

**Links marked _(landing)_** (NCS, Hirect, Apna, WorkIndia) open the site's
search page rather than a pre-filled query, because the portal is app-first or
its URL format is unstable. The user types the query once there.

International equivalents worth a `web_search` (Tier 3): DrJobPro (Middle East),
Shine/foundit Gulf, plus visa-sponsor lists for EU/UK/Canada.

## Tier 3 — company career pages & curated lists (Claude's own tools)

Use `web_search` / `web_fetch` for:
- Specific company career pages ("Jane Street careers Haskell", "Juspay careers")
  — Google and Amazon now have dedicated Tier 1 adapters (see above); this
  tier is for everyone else, plus Microsoft until its browser path exists.
- Curated visa-sponsorship lists (e.g. companies that sponsor in the EU/UK/Canada;
  the `nemecek-filip/Awesome-Companies-Sponsoring-Visa` style GitHub lists)
- Niche functional-programming boards (functional.works-hub, haskellers, etc.)

When the user wants visa-sponsored international roles, combine: Arbeitnow's visa
flag (Tier 1) + a `web_search` for current curated sponsor lists (Tier 3) +
filtered LinkedIn URLs with the target country (Tier 2).
