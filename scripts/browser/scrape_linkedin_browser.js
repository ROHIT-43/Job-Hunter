// ── LinkedIn Voyager job-card scraper ────────────────────────────────────────
// Paste into an authenticated LinkedIn browser tab (DevTools console or
// Claude-in-Chrome javascript_tool). Runs as a single async IIFE so it
// continues even if the tab is backgrounded (no self-perpetuating setTimeout).
//
// OUTPUT: auto-downloads `to_score.json` when complete.
// Poll: window.__SCRAPE_DONE === true
// Progress: window.__SCRAPE_PROGRESS  →  {keyword, start}
// Error:    window.__SCRAPE_ERR
//
// ── Configure here ───────────────────────────────────────────────────────────
const WINDOW_SECONDS = 43200;  // time window: 3600=1h, 7200=2h, 86400=24h
const KEYWORDS = [
  "sde", "software engineer", "sde2", "swe", "mts",
  "member of technical staff",
  "backend engineer", "full stack developer", "software developer",
  "devops engineer", "cloud engineer",
];
const LOCATION  = "India";     // LinkedIn seoLocation value
const PAGE_SIZE = 100;         // max per page (LinkedIn hard-caps at 100)
const MAX_START = 950;         // LinkedIn returns 0 results past start=1000
const PAGE_DELAY_MS = 300;     // gentle pacing between pages
// ─────────────────────────────────────────────────────────────────────────────

window.__SCRAPE          = window.__SCRAPE || [];
window.__SCRAPE_DONE     = false;
window.__SCRAPE_ERR      = null;
window.__SCRAPE_PROGRESS = {keyword: '', start: 0};

(async () => {
  const csrf = (document.cookie.match(/JSESSIONID="?(ajax:[0-9-]+)"?/) || [])[1];
  if (!csrf) {
    window.__SCRAPE_ERR = 'no_csrf_cookie — make sure you are on linkedin.com and logged in';
    window.__SCRAPE_DONE = true;
    return;
  }
  const HEADERS = {
    'csrf-token': csrf,
    'x-restli-protocol-version': '2.0.0',
    'accept': 'application/vnd.linkedin.normalized+json+2.1',
  };

  const seen = new Set();

  try {
    for (const kw of KEYWORDS) {
      const ekw = encodeURIComponent(kw);
      let start = 0;
      while (start <= MAX_START) {
        window.__SCRAPE_PROGRESS = {keyword: kw, start};
        const url =
          `https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards` +
          `?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-220` +
          `&count=${PAGE_SIZE}&q=jobSearch` +
          `&query=(origin:JOB_SEARCH_PAGE_OTHER_ENTRY,keywords:${ekw},` +
          `locationUnion:(seoLocation:(location:${encodeURIComponent(LOCATION)})),` +
          `selectedFilters:(timePostedRange:List(r${WINDOW_SECONDS}),sortBy:List(DD)),` +
          `spellCorrectionEnabled:true)&start=${start}`;

        const r = await fetch(url, {headers: HEADERS, credentials: 'include'});
        if (r.status !== 200) break;
        const j = await r.json();

        // Build id → {title, company, location, listedAt} from included[]
        const cardMap = {};
        for (const it of (j.included || [])) {
          if (it.$type === 'com.linkedin.voyager.dash.jobs.JobPostingCard') {
            const m = (it.entityUrn || '').match(/(\d{8,12})/);
            if (m && (it.title?.text || it.primaryDescription?.text || it.secondaryDescription?.text)) {
              const prev = cardMap[m[1]] || {};
              cardMap[m[1]] = {
                title:    it.title?.text             || prev.title    || '',
                company:  it.primaryDescription?.text || prev.company  || '',
                location: it.secondaryDescription?.text || prev.location || '',
                listedAt: it.listedAt                || prev.listedAt || null,
              };
            }
          }
        }

        const elements = j.data?.elements || [];
        for (const el of elements) {
          const cardUrn = el.jobCardUnion?.['*jobPostingCard'];
          const m = (cardUrn || '').match(/(\d{8,12})/);
          if (!m) continue;
          const id = m[1];
          if (seen.has(id)) continue;
          seen.add(id);
          const card = cardMap[id] || {};
          window.__SCRAPE.push({
            id,
            title:    card.title    || '',
            company:  card.company  || '',
            location: card.location || '',
            listedAt: card.listedAt || null,
            keyword:  kw,
          });
        }

        if (elements.length < PAGE_SIZE) break; // last page for this keyword
        start += PAGE_SIZE;
        await new Promise(res => setTimeout(res, PAGE_DELAY_MS));
      }
    }
  } catch (e) {
    window.__SCRAPE_ERR = String(e);
  }

  window.__SCRAPE_DONE = true;
  console.log(`Scrape done: ${window.__SCRAPE.length} jobs`);

  // Auto-download as to_score.json
  try {
    const b = new Blob([JSON.stringify(window.__SCRAPE)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'to_score.json';
    a.click();
  } catch (e) {
    window.__SCRAPE_ERR = (window.__SCRAPE_ERR || '') + '|dl:' + e;
    console.warn('Auto-download failed. Run: copy(JSON.stringify(window.__SCRAPE)) to get data.');
  }
})();

"scrape started — poll window.__SCRAPE_DONE";
