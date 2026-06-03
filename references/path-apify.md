# Path B — Apify (actor pull)

> This is the **Apify pull path** of the gated skill. It produces normalized
> candidates via a maintained actor, then hands off to `references/backbone.md`
> (dedup → red-flag → score → YoE split → queue; writes `APPLY_QUEUE.md`). The
> actor defaults to `cfg["apify_actor"]`; titles/window come from `hunt_config`.
> Pay-per-result — confirm credit use with the user before pulling.

The user has an **Apify connector** available. Apify hosts maintained actors that
return structured job data from LinkedIn/Naukri/Indeed without you writing or
running a scraper. This is the robust alternative to the Tier-2 search URLs when
the user wants results *pulled into the report* rather than browsing themselves.

This requires the user's explicit go-ahead (it consumes their Apify credits) and
the Apify tools to be loaded via `tool_search`.

## Coverage reality (verify each run — actors change)

Apify does NOT have a good actor for every job site. As observed:

| Site | Apify coverage | Notes |
|---|---|---|
| LinkedIn | strong (4+ actors) | e.g. `curious_coder/linkedin-jobs-scraper`, `cheap_scraper/linkedin-job-scraper`, `fantastic-jobs/advanced-linkedin-job-search-api`; ~$0.0003–0.001/result |
| Naukri | good (5 actors) | e.g. `memo23/naukri-scraper` (India + Gulf), `muhammetakkurtt/naukri-job-scraper`; quality varies, ~$0.001–0.005/result |
| Indeed, Glassdoor, RemoteOK | covered | dedicated actors + the aggregator below |
| Multi-source | `lenient_grove/Daily-Job-Pulse` scans 25+ platforms with apply links | convenient but pricey (~$0.05–0.08/result) and skips niche India sites |
| CutShort, Instahyre, Hirist, Apna, WorkIndia, Shine, Freshersworld, Foundit, TimesJobs, NCS | **none found** | many are login-walled (Instahyre/CutShort/Apna) — use `search_urls.py` for these, do NOT automate login |

So: use Apify for the covered sites, and fall back to `search_urls.py` deep links
for everything else. Don't assume an actor exists — confirm with `search-actors`.

## Cost & safety

- Every actor is **pay-per-result**. Always set a small row cap first
  (e.g. 25–50) to validate output, confirm the spend with the user, then scale.
- Actors are **community-maintained** and break when a site changes its markup
  (success rates seen: 91–100%). If one returns junk, try another from the list.
- Using an actor against LinkedIn/Naukri still runs against those sites' ToS;
  Apify treats that as the user's responsibility. Surface this, don't bury it.
- Never feed the user's account credentials to a login-walled actor.

## Workflow

1. `tool_search(query="apify search actors")` to load the Apify tools.
2. `Apify:search-actors` with a query like `"linkedin jobs"` or `"naukri jobs"`
   to find a current, well-rated actor (actor availability changes over time, so
   don't hardcode an actor ID — search each run).
3. `Apify:fetch-actor-details` on the chosen actor to read its input schema.
4. `Apify:call-actor` with input built from the candidate profile, e.g.:
   ```json
   {
     "keywords": "backend engineer haskell rust",
     "location": "India",
     "remote": true,
     "rows": 50
   }
   ```
   (Field names vary per actor — use the schema from step 3.)
5. `Apify:get-actor-output` with the returned `datasetId` to read results.
6. Map each row to the normalized schema (same fields `fetch_jobs.py` produces:
   `title, company, location, remote, visa_sponsorship, tags, salary,
   description, url, posted, source`), write to a JSON file, then feed into
   `score_jobs.py` alongside the keyless results. `scripts/apify_scrape.py`
   already normalizes the rows it pulls, so its output drops straight in.

## Notes

- Confirm credit usage with the user before calling an actor.
- Set a modest `rows`/`maxItems` first to validate output shape, then scale up.
- Merge Apify results with Tier-1 results before scoring — `score_jobs.py` dedups
  on (title, company).
