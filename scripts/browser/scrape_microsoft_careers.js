// ── Microsoft careers (Eightfold "PCSX") scraper + JD fetcher ───────────────
// Paste into a browser tab already navigated to the Microsoft careers search
// URL below (DevTools console or Claude-in-Chrome javascript_tool).
//
// The site's frontend does NOT use `/api/apply/v2/jobs` (that path 403s with
// "Not authorized for PCSX" even with real session cookies — it's dead/legacy).
// Confirmed via a live session (2026-07-04): the real endpoints are
// `/api/pcsx/search` (job list) and `/api/pcsx/position_details` (full JD per
// job). Both work with a plain same-origin `fetch(..., {credentials:
// 'include'})`. `/api/pcsx/search` hard-caps at 10 results per page regardless
// of `num`.
//
// CAVEAT: the live test ran in a tab logged into a Microsoft candidate
// account (results were personalized — "Hi <name>", "Good/Strong match"
// labels). Whether these two endpoints also work from a fully logged-out
// tab is NOT verified — if you hit a 401/403 here while logged out, that's
// the open question to resolve, not a sign the endpoints changed.
//
// OUTPUT: auto-downloads `ms_jobs.json` — normalized array:
//   [{id, title, company, location, url, description, posted,
//     employment_type, work_site, roletype}]
//   `roletype` is "Individual Contributor" vs people-manager tracks — use it
//   to drop management titles, same idea as Amazon's category-facet noise.
// Poll: window.__MS_DONE === true
// Progress: window.__MS_PROGRESS → {phase, count}
// Error:    window.__MS_ERR
//
// ── Configure here (mirrors the search URL's own query params) ─────────────
const QUERY               = "Software Engineer";
const LOCATION             = "India, Multiple Locations, Multiple Locations";
const FILTER_CAREER_DISC   = "Software Engineering";
const FILTER_EMPLOYMENT    = "full-time";
const FILTER_PROFESSION    = "software engineering";
const FILTER_SENIORITY     = "Mid-Level";
const INCLUDE_REMOTE       = 1;
const PAGE_SIZE            = 10;   // server hard-caps at 10 regardless of `num`
const MAX_PAGES            = 5;
const JD_CONCURRENCY       = 5;
const PAGE_DELAY_MS        = 400;
// ─────────────────────────────────────────────────────────────────────────────

window.__MS_JOBS     = window.__MS_JOBS || [];
window.__MS_DONE     = false;
window.__MS_ERR      = null;
window.__MS_PROGRESS = {phase: 'starting', count: 0};

function stripHtml(html) {
  return (html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

(async () => {
  // ── Step 1: search — cheap, gives id/title/location/postedTs ────────────
  window.__MS_PROGRESS.phase = 'search';
  const positions = [];
  const seen = new Set();
  for (let page = 0; page < MAX_PAGES; page++) {
    const start = page * PAGE_SIZE;
    const params = new URLSearchParams({
      domain: 'microsoft.com', query: QUERY, location: LOCATION,
      sort_by: 'timestamp', filter_include_remote: String(INCLUDE_REMOTE),
      filter_career_discipline: FILTER_CAREER_DISC,
      filter_employment_type: FILTER_EMPLOYMENT,
      filter_profession: FILTER_PROFESSION,
      filter_seniority: FILTER_SENIORITY,
      start: String(start), num: String(PAGE_SIZE),
    });
    let r;
    try {
      r = await fetch(`/api/pcsx/search?${params}`,
                       {credentials: 'include', headers: {Accept: 'application/json'}});
    } catch (e) {
      window.__MS_ERR = 'search_fetch: ' + String(e);
      break;
    }
    if (r.status !== 200) {
      window.__MS_ERR = `search_http_${r.status}: ${(await r.text()).slice(0, 200)}`;
      break;
    }
    const j = await r.json();
    const rows = j.data?.positions || [];
    for (const p of rows) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      positions.push(p);
    }
    window.__MS_PROGRESS.count = positions.length;
    const total = j.data?.count ?? 0;
    if (start + PAGE_SIZE >= total || rows.length === 0) break;
    await new Promise(res => setTimeout(res, PAGE_DELAY_MS));
  }

  // ── Step 2: position_details — full JD, fan out with bounded concurrency ─
  window.__MS_PROGRESS.phase = 'jd-fetch';
  window.__MS_PROGRESS.count = 0;
  for (let i = 0; i < positions.length; i += JD_CONCURRENCY) {
    await Promise.all(positions.slice(i, i + JD_CONCURRENCY).map(async (p) => {
      try {
        const dparams = new URLSearchParams({domain: 'microsoft.com', position_id: String(p.id)});
        const r = await fetch(`/api/pcsx/position_details?${dparams}`,
                               {credentials: 'include', headers: {Accept: 'application/json'}});
        if (r.status !== 200) return;
        const d = (await r.json()).data || {};
        window.__MS_JOBS.push({
          id: String(p.id), title: d.name || p.name || '',
          company: 'Microsoft',
          location: (d.locations || p.locations || []).join('; '),
          url: 'https://apply.careers.microsoft.com' + (d.positionUrl || p.positionUrl || ''),
          description: stripHtml(d.jobDescription),
          posted: p.postedTs ? new Date(p.postedTs * 1000).toISOString() : null,
          employment_type: (d.efcustomTextEmploymentType || [])[0] || null,
          work_site: (d.efcustomTextWorkSite || [])[0] || null,
          roletype: (d.efcustomTextRoletype || [])[0] || null,
        });
      } catch (e) {
        window.__MS_ERR = (window.__MS_ERR ? window.__MS_ERR + ' | ' : '') +
          `jd_fetch(${p.id}): ${e}`;
      }
      window.__MS_PROGRESS.count++;
    }));
    await new Promise(res => setTimeout(res, PAGE_DELAY_MS));
  }

  window.__MS_DONE = true;
  console.log(`Microsoft scrape done: ${window.__MS_JOBS.length}/${positions.length} JDs fetched` +
              (window.__MS_ERR ? ` | errors: ${window.__MS_ERR}` : ''));

  // Auto-download as ms_jobs.json
  try {
    const b = new Blob([JSON.stringify(window.__MS_JOBS, null, 2)],
                        {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'ms_jobs.json';
    a.click();
  } catch (e) {
    window.__MS_ERR = (window.__MS_ERR || '') + '|dl:' + e;
    console.warn('Auto-download failed. Run: copy(JSON.stringify(window.__MS_JOBS)) to get data.');
  }
})().catch(e => { window.__MS_ERR = String(e); window.__MS_DONE = true; });

"Microsoft scrape started — poll window.__MS_DONE";
