# Path A — Browser (Claude-in-Chrome + voyager)

The authenticated, in-browser LinkedIn path. Richest source; you stay logged into
your own session. Produces normalized candidates, then hands off to
`references/backbone.md`.

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

## Step 1 — Scrape job IDs (paginated)

For each title in `cfg["target_titles"]`, page the job-card endpoint
(`window_seconds = cfg["window_hours"] * 3600`, e.g. 5h → `r18000`):

```
GET /voyager/api/voyagerJobsDashJobCards
  ?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-227
  &count=25&q=jobSearch&start=<n>
  &query=(origin:JOB_SEARCH_PAGE_JOB_FILTER,keywords:<title>,
          locationUnion:(geoId:<cfg.geo_id>),
          selectedFilters:(timePostedRange:List(r<window_seconds>),
                           employmentType:List(F)
                           [, experience:List(<cfg.experience_filters>)]),
          spellCorrectionEnabled:true)
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
`start >= paging.total`; dedup IDs across titles.

## Step 2 — Build candidate links

`https://www.linkedin.com/jobs/view/<id>` for every scraped ID.

## Step 3 — Pre-filter (cheap, in-browser)

Drop obvious non-fits by title (Salesforce/SAP/.NET/QA/trainer/etc.) and dedup by
`(title, company)`. Red-flag companies are dropped in the backbone, but you may
also drop them here to save fetches.

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

Returns `description.text` (full JD), `title`, `companyDetails` (name),
`formattedLocation`.

## Step 5 — Browser → disk transfer

`javascript_tool` inline return truncates ~1 KB. To move bulk data out: render the
JSON into an `<article>` element and read it with `get_page_text`, keeping each
chunk **under 50 KB** (it errors above that — split into multiple chunks). Wrap the
payload in sentinels (e.g. `__BEGIN__ … __END__`) for clean extraction.

## Step 6 — Score (fan-out)

Batch the candidates and fan out parallel agents (a Workflow, or parallel Agent
calls). Each agent scores from the supplied JD text — no WebFetch — and **sets
`min_yoe`** per its reading of the JD. Write per-batch result files, then merge.
Re-fetch any `fetched:false` rows via the Step-4 voyager endpoint and re-score
before trusting the totals.

**Non-negotiable scoring guardrails** (a Haiku run on 2026-06-02 produced scores of
113 and false-100s by ignoring these):
- **Canonical rubric:** give every scoring subagent the entire contents of
  `assets/scoring_rubric.md` verbatim (skillset + formula + penalties + caps + YoE +
  output contract + worked examples). Never hand-write a shortened rubric.
- **Bounded schema:** the `score` field MUST be `{type:'integer', minimum:0,
  maximum:100}` so out-of-range outputs are rejected.
- **Model:** Sonnet or better for scoring; **Haiku is banned for scoring** (fine for
  the tailoring step in Step 7).

## Step 7 — Hand to the backbone

Pass the scored candidates to `references/backbone.md` (dedup → red-flag → YoE
split → persist + queue). The browser path writes a uniquely timestamped folder
`data/pipeline/browser_runs/<date>_<time>_<window>/` containing:

| File | Contents |
|------|----------|
| `jobs_raw.json` | every scraped job (id, title, company, `jd_link`) |
| `candidates_fresh.json` | post-dedup, post-filter candidates |
| `jobs_scored.json` | all candidates scored (score, matched/gap, summary) |
| `matches.json` | the ≥ `score_threshold` shortlist (with `min_yoe`/`stretch` + `resume_pdf`) |
| `<id>_<idx>/resume.{tex,pdf}` | per-match tailored resume |

and `BROWSER_QUEUE.md` (eligible matches only; >`yoe_threshold`-yr roles are
excluded from the queue and not tailored — dedup-tracked in `seen_jobs.json` only).
