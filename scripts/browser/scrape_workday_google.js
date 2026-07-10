// ── Workday job scraper via Google site: search ───────────────────────────────
// Paste into any authenticated Google.com browser tab (DevTools console).
// Searches Google for myworkdayjobs.com postings from the past day for India.
//
// OUTPUT: auto-downloads `workday_jobs.json`
//   Format: [{url, tenant, wd, career_site, job_id, title, company, location,
//             location_slug, keyword}]
//
// Poll: window.__WD_DONE === true
// Progress: window.__WD_PROGRESS  →  {query, page, total}
// Error:    window.__WD_ERR
//
// ── Configure here ───────────────────────────────────────────────────────────
const WD_QUERIES = [
  '"software engineer" "India"',
  '"member of technical staff" "India"',
  '"software developer" "India"',
  '"backend engineer" "India"',
  '"devops engineer" "India"',
  '"sde" "India"',
];
const WD_DATE_FILTER = 'qdr:d';   // past day — change to qdr:w for past week
const WD_MAX_PAGES   = 5;         // safety cap; each page = 10 results → 50 max per query
const WD_DELAY_MS    = 1500;      // ms between requests (be polite to Google)
// ─────────────────────────────────────────────────────────────────────────────

window.__WD_JOBS     = window.__WD_JOBS || {};
window.__WD_DONE     = false;
window.__WD_ERR      = null;
window.__WD_PROGRESS = {query: '', page: 0, total: 0};

/** Extract all myworkdayjobs.com /job/ URLs from raw HTML. */
function _extractWdLinks(html) {
  // Decode HTML entities first
  const decoded = html
    .replace(/&amp;/g, '&')
    .replace(/&#x2F;/g, '/')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');

  const re = /https?:\/\/[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com\/[^\s"'<>\)\\]+/gi;
  const seen = new Set();
  let m;
  while ((m = re.exec(decoded)) !== null) {
    let url = m[0];
    // Trim trailing junk characters
    url = url.replace(/["\s<>\)\\%22]+$/, '');
    // Only job detail pages
    if (/\/job\//.test(url)) {
      try { url = decodeURIComponent(url); } catch {}
      seen.add(url.split('?')[0]);  // strip query params
    }
  }
  return [...seen];
}

/**
 * Parse a Workday job URL into its components.
 * Handles both: /career_site/job/location/Title_ID
 *          and: /en-US/career_site/job/location/Title_ID
 */
function _parseWdUrl(url, keyword) {
  const m = url.match(
    /https?:\/\/([^.]+)\.(wd\d+)\.myworkdayjobs\.com\/(?:[a-z]{2}-[A-Z]{2}\/)?([^\/]+)\/job\/([^\/]+)\/([^?#\/]+)/
  );
  if (!m) return null;
  const [, tenant, wd, career_site, location_slug, title_id] = m;
  // Job ID is the part after the last underscore
  const job_id = title_id.includes('_') ? title_id.split('_').pop() : title_id;
  // Readable title from the slug (before last _)
  const title_slug = title_id.includes('_')
    ? title_id.slice(0, title_id.lastIndexOf('_')).replace(/-/g, ' ')
    : title_id.replace(/-/g, ' ');
  return {
    url,
    tenant,
    wd,
    career_site,
    location_slug,
    job_id,
    title:    title_slug,
    company:  '',          // filled by fetch_workday_jd via JSON-LD
    location: location_slug.replace(/-/g, ' '),
    keyword,
  };
}

(async () => {
  for (const query of WD_QUERIES) {
    console.log(`[WD] Query: "${query}"`);
    let totalAdded = 0;

    for (let page = 0; page < WD_MAX_PAGES; page++) {
      const start = page * 10;
      const q = encodeURIComponent(`site:myworkdayjobs.com ${query}`);
      // num=10 is what Google actually serves for site: queries even if you ask for more
      const searchUrl = `https://www.google.com/search?q=${q}&tbs=${WD_DATE_FILTER}&start=${start}&hl=en`;
      window.__WD_PROGRESS = {query, page: page + 1, total: Object.keys(window.__WD_JOBS).length};

      try {
        const r = await fetch(searchUrl, {
          credentials: 'include',
          headers: {
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
          },
        });
        if (!r.ok) {
          console.warn(`[WD]   HTTP ${r.status} on page ${page + 1} — stopping this query`);
          break;
        }
        const html = await r.text();

        // Check if Google returned a CAPTCHA
        if (html.includes('g-recaptcha') || html.includes('recaptcha')) {
          window.__WD_ERR = 'CAPTCHA detected — try again later or reduce speed';
          console.warn('[WD] CAPTCHA hit — stopping');
          window.__WD_DONE = true;
          return;
        }

        // Google signals "no more results" in several ways
        const googleNoMore = html.includes('did not match any documents')
          || html.includes('No results found for')
          || html.includes('"pedestrian":true')  // internal no-results flag
          || (page > 0 && html.includes('id="botstuff"') && !html.includes(`start=${start + 10}`));

        const links = _extractWdLinks(html);
        let added = 0;
        for (const link of links) {
          if (!window.__WD_JOBS[link]) {
            const parsed = _parseWdUrl(link, query);
            if (parsed) {
              window.__WD_JOBS[link] = parsed;
              added++;
              totalAdded++;
            }
          }
        }
        // Check whether Google rendered a "Next" page link (start=N+10 appears in HTML)
        const hasNext = html.includes(`start=${start + 10}`);
        console.log(`[WD]   page ${page + 1}: ${links.length} WD URLs found, +${added} new (total: ${Object.keys(window.__WD_JOBS).length}, hasNext=${hasNext})`);

        // Stop on Google's own signals
        if (googleNoMore) {
          console.log(`[WD]   Google says no more results — stopping at page ${page + 1}`);
          break;
        }
        // No "Next" link → this is the last page; no point fetching start+10
        if (!hasNext) {
          console.log(`[WD]   No next-page link — last page reached at page ${page + 1}`);
          break;
        }
        await new Promise(res => setTimeout(res, WD_DELAY_MS));
      } catch (e) {
        console.warn(`[WD]   page ${page + 1} error:`, e);
        window.__WD_ERR = String(e);
        break;
      }
    }
    console.log(`[WD] "${query}" done: ${totalAdded} new jobs`);
    await new Promise(res => setTimeout(res, WD_DELAY_MS));
  }

  window.__WD_DONE = true;
  const allJobs = Object.values(window.__WD_JOBS);
  console.log(`[WD] Scrape complete: ${allJobs.length} unique Workday jobs`);
  window.__WD_PROGRESS = {query: 'done', page: 0, total: allJobs.length};

  try {
    const b = new Blob([JSON.stringify(allJobs)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'workday_jobs.json';
    a.click();
  } catch (e) {
    window.__WD_ERR = String(e);
    console.warn('[WD] Download failed — run: copy(JSON.stringify(Object.values(window.__WD_JOBS)))');
  }
})().catch(e => { window.__WD_ERR = String(e); window.__WD_DONE = true; console.error('[WD]', e); });

"WD scrape started — poll window.__WD_DONE";
