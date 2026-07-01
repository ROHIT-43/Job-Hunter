# Profile Hunter — screening LinkedIn profiles for outreach targets

A different hunt shape than the voyager job-search paths (A/B/C in the main
skill): instead of searching job postings by keyword, you start from a **list
of LinkedIn profile URLs** (people who reacted/commented on a post, "people
also viewed", a recruiter's connections, etc.) and screen each profile to find
who is personally worth reaching out to. Feeds directly into connection-note /
InMail drafting — it does not touch `BROWSER_QUEUE.md` or `seen_jobs.json`.

## Categories

- **`would-be-hiring`** (implemented below) — profile has a recent post
  personally announcing/sharing an open role. The screen checks whether that
  role matches the candidate's YoE band, seniority, and domain.
- **`referral-hunting`** (planned, not yet built) — profile's headline/About
  explicitly offers referrals (e.g. "DM for referral", "Computer Scientist 2 at
  Adobe || DM for referral") regardless of whether they have an active hiring
  post. Wider net than `would-be-hiring`; worth a separate pass once the
  candidate wants volume over precision.

---

## `would-be-hiring` — screening steps

### Input

A raw pasted list of LinkedIn profile URLs (often messy — duplicate entries,
stray `componentkey="..."` attributes, anchor text, mixed formatting from a
copy-paste off a LinkedIn page). Dedupe by the `/in/<handle>/` path before
screening; strip everything else.

### Matching logic (reuse `candidate_profile.json` — no new config)

| Field | Use |
|---|---|
| `min_yoe_gate` | role must ask for roughly the candidate's YoE band or less (no stated minimum is fine); posts wanting well beyond it are excluded |
| `seniority_cap_pattern` | Lead/Principal/Staff/Architect/Director/Manager-titled roles excluded, same as the main pipeline — `Senior`/`Sr` is NOT excluded, scored on merit |
| `triage_stack` / `hard_gaps` | role's primary function must be an IC SWE/backend/SDE role in-stack — not ML/data/BI/support/embedded/QA/firmware/HR/campus-hiring as the primary ask |

Classify each profile as:
- **MATCH** — recent own post (not just a repost, unless it's clearly their
  own team's opening) personally announcing an IC SWE-band role in scope
- **NO MATCH** — no hiring post, wrong seniority/YoE/domain, or role closed/stale
- **UNCLEAR** — page wouldn't load, no visible posts, or genuinely ambiguous — don't burn retries on it, just log it and move on

### Execution mechanics

This runs through `mcp__claude-in-chrome__*` tools, not a scraper script —
LinkedIn's activity feed is JS-rendered and behind auth, so it's driven live in
the browser same as the rest of this skill's browser path.

1. **Batch size ~25-30 profiles per fork.** A batch this size produces a lot of
   raw post text per profile — dispatch it to a `fork` (inherits context/tools,
   keeps the raw text out of the coordinator's transcript) rather than doing it
   inline. Two batches can run concurrently in separate forks as long as each
   creates its **own** tab (`tabs_create_mcp`) rather than fighting over one.
2. Load browser tools once: `ToolSearch` with
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__tabs_create_mcp`
3. For each profile: navigate to `<profile-url>/recent-activity/all/`, then
   `get_page_text`. If it returns nothing useful (common on first load), wait
   1-2s and retry before falling back to a screenshot. Click any `...more` to
   expand truncated posts when the hiring details (YoE, role) are cut off.
4. Look at the 2-3 most recent posts only — don't scroll deep. Classify per
   the matching logic above.
5. Skip profiles a sibling batch already covered (dedupe the URL list across
   concurrent forks before launching).

### Output contract (fork → coordinator)

Keep it under ~400 words — **never dump raw post text back to the
coordinator**, only the extracted facts. Always return the **full profile URL**
(`https://www.linkedin.com/in/<handle>/`) alongside each name, not a bare
handle — it gets written straight into `POTENTIAL_HIRERS.md` as a clickable
link.

- **MATCH:** name, full profile URL, title, company, the specific role/level
  posted, stated YoE requirement, post age, one line on posting style
  (emoji-heavy vs terse, personal vs corporate) — the style note feeds the
  connection-note tailoring step next
- **NO MATCH / UNCLEAR:** one line per profile — name, full profile URL, and a
  3-5 word reason (e.g. "Kamlesh Borde — https://www.linkedin.com/in/kborde/ —
  Lead Engineer only")

### Tracking file

Every batch's results get appended to `data/pipeline/POTENTIAL_HIRERS.md`
(gitignored, same as `BROWSER_QUEUE.md`): a `⭐ Matches` section with full
profile URLs + a `- [ ] Connection note sent` checkbox per match, and a
`Screened, no match` table (`Name | Profile | Reason`) with full URLs so
nothing needs re-screening later. New batches append a new dated section
rather than overwriting prior ones.

### Downstream handoff

For every MATCH, the next step (done by the coordinator, not the fork) is a
tailored connection note or InMail:
- Mirror the poster's actual style (emoji density, terse vs warm, hashtag use)
  rather than a fixed template
- Reference the specific role/post, not a generic "interested in openings"
- Respect the channel's real limit — connection notes cap around 200-300
  characters; InMail/DM has no hard cap but stay to a few sentences
- Add `bytedex.github.io` (portfolio) or the resume link only when it fits
  without crowding out the actual hook
