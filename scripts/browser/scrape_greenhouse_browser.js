// ── Greenhouse my.greenhouse.io job scraper ───────────────────────────────────
// Paste into an authenticated my.greenhouse.io browser tab (DevTools console).
// Uses Inertia.js XHR API — handles pagination automatically.
//
// OUTPUT: auto-downloads `greenhouse_jobs.json`
//   Format: [{company_token, job_id, url, title, company, location,
//             firstPublished, keyword}]
//
// Poll: window.__GH_DONE === true
// Progress: window.__GH_PROGRESS  →  {query, page, total}
// Error:    window.__GH_ERR
//
// ── Configure here ───────────────────────────────────────────────────────────
const GH_QUERIES = [
  "Software Engineer",
  "Member Of Technical Staff",
  "software developer",
  "backend engineer",
  "devops engineer",
];
const GH_DATE_FILTER   = "past_day";
const GH_LOCATION      = "India";
const GH_LAT           = "22.687581";
const GH_LON           = "79.370366";
const GH_LOC_TYPE      = "country";
const GH_COUNTRY_SHORT = "IN";
const GH_DELAY_MS      = 400;   // ms between page requests
const GH_MAX_PAGES     = 20;    // safety cap per query
// ─────────────────────────────────────────────────────────────────────────────

window.__GH_JOBS     = window.__GH_JOBS || {};
window.__GH_DONE     = false;
window.__GH_ERR      = null;
window.__GH_PROGRESS = {query: '', page: 0, total: 0};

function _inertiaVersion() {
  try {
    const raw = document.getElementById('app')?.getAttribute('data-page') || '{}';
    return JSON.parse(raw.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'")).version || null;
  } catch { return null; }
}

async function _fetchPage(query, page, version) {
  const params = [
    `query=${encodeURIComponent(query)}`,
    `location=${encodeURIComponent(GH_LOCATION)}`,
    `lat=${GH_LAT}`,
    `lon=${GH_LON}`,
    `location_type=${GH_LOC_TYPE}`,
    `country_short_name=${GH_COUNTRY_SHORT}`,
    `date_posted=${GH_DATE_FILTER}`,
    `page=${page}`,
  ].join('&');

  const r = await fetch(`/jobs?${params}`, {
    credentials: 'include',
    headers: {
      'X-Inertia':         'true',
      'X-Inertia-Version': version,
      'Accept':            'text/html, application/xhtml+xml',
      'X-Requested-With':  'XMLHttpRequest',
    },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return {
    jobs:          d?.props?.jobPosts         || [],
    moreAvailable: d?.props?.moreResultsAvailable ?? false,
  };
}

(async () => {
  const version = _inertiaVersion();
  if (!version) {
    window.__GH_ERR = 'Could not detect Inertia version — make sure you are on my.greenhouse.io';
    window.__GH_DONE = true;
    return;
  }
  console.log(`[GH] Inertia version: ${version}`);

  for (const query of GH_QUERIES) {
    console.log(`[GH] Query: "${query}"`);
    let page = 1, pageAdded = 0;

    while (page <= GH_MAX_PAGES) {
      window.__GH_PROGRESS = {query, page, total: Object.keys(window.__GH_JOBS).length};
      try {
        const {jobs, moreAvailable} = await _fetchPage(query, page, version);
        let added = 0;
        for (const j of jobs) {
          const id = String(j.id || '');
          if (!id || window.__GH_JOBS[id]) continue;
          // viewJobPath: "/getwellnetwork/jobs/5315145008"
          const m = (j.viewJobPath || '').match(/\/([^/?#]+)\/jobs\/(\d+)/);
          window.__GH_JOBS[id] = {
            company_token:  m ? m[1] : '',
            job_id:         id,
            url:            m ? `https://my.greenhouse.io${j.viewJobPath}` : '',
            title:          j.title         || '',
            company:        j.companyName   || '',
            location:       (j.locations    || []).join(', '),
            firstPublished: j.firstPublished || null,
            keyword:        query,
          };
          added++;
        }
        pageAdded += added;
        console.log(`[GH]   page ${page}: ${jobs.length} jobs, +${added} new (total: ${Object.keys(window.__GH_JOBS).length})`);
        if (!moreAvailable || jobs.length === 0) break;
        page++;
        await new Promise(r => setTimeout(r, GH_DELAY_MS));
      } catch (e) {
        console.warn(`[GH]   page ${page} error:`, e);
        window.__GH_ERR = String(e);
        break;
      }
    }
    console.log(`[GH] "${query}" done: ${pageAdded} new jobs`);
    await new Promise(r => setTimeout(r, GH_DELAY_MS));
  }

  window.__GH_DONE = true;
  const allJobs = Object.values(window.__GH_JOBS);
  console.log(`[GH] Scrape complete: ${allJobs.length} unique jobs`);
  window.__GH_PROGRESS = {query: 'done', page: 0, total: allJobs.length};

  try {
    const b = new Blob([JSON.stringify(allJobs)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'greenhouse_jobs.json';
    a.click();
  } catch (e) {
    window.__GH_ERR = String(e);
    console.warn('[GH] Download failed — run: copy(JSON.stringify(Object.values(window.__GH_JOBS)))');
  }
})().catch(e => { window.__GH_ERR = String(e); window.__GH_DONE = true; console.error('[GH]', e); });

"GH scrape started — poll window.__GH_DONE";
