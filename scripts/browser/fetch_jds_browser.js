// ── LinkedIn Voyager JD fetcher ───────────────────────────────────────────────
// Paste into an authenticated LinkedIn browser tab AFTER loading to_fetch.json
// as window.__TO_SCORE (the filtered job list from filter_jobs.py).
//
// Usage:
//   1. python3 scripts/pipeline/filter_jobs.py   →  data/.../to_fetch.json
//   2. In DevTools console, inject to_fetch.json:
//        const d = await fetch('file:///path/to/to_fetch.json').then(r=>r.json());
//        window.__TO_SCORE = d;
//      Or paste the JSON directly:
//        window.__TO_SCORE = [{"id":"...", ...}, ...];
//   3. Paste this script.
//   4. Poll: window.__JD_PROGRESS  →  {done, total, errors}
//   5. When window.__JD_DONE === true, download fires automatically.
//
// OUTPUT: auto-downloads `ollama_input.json`
//   Format: { "<id>": { jd, title, company, staffCount, listedAt, applies } }
//
// ── Configure here ───────────────────────────────────────────────────────────
const CONCURRENCY   = 10;    // parallel fetches per batch
const BATCH_DELAY   = 400;   // ms between batches
// ─────────────────────────────────────────────────────────────────────────────

window.__JD_DATA     = {};
window.__JD_DONE     = false;
window.__JD_ERR      = null;
window.__JD_PROGRESS = {done: 0, total: 0, errors: 0};

(async () => {
  const jobs = window.__TO_SCORE;
  if (!Array.isArray(jobs) || jobs.length === 0) {
    window.__JD_ERR  = 'window.__TO_SCORE is empty or not set — inject to_fetch.json first';
    window.__JD_DONE = true;
    return;
  }
  window.__JD_PROGRESS.total = jobs.length;

  const csrf = (document.cookie.match(/JSESSIONID="?(ajax:[0-9-]+)"?/) || [])[1];
  if (!csrf) {
    window.__JD_ERR  = 'no_csrf_cookie';
    window.__JD_DONE = true;
    return;
  }
  const HEADERS = {
    'csrf-token': csrf,
    'x-restli-protocol-version': '2.0.0',
    'accept': 'application/vnd.linkedin.normalized+json+2.1',
  };

  function extractText(desc) {
    if (!desc) return '';
    if (typeof desc === 'string') return desc;
    return desc.text || '';
  }

  for (let i = 0; i < jobs.length; i += CONCURRENCY) {
    await Promise.all(jobs.slice(i, i + CONCURRENCY).map(async (job) => {
      const id  = job.id;
      const url = `https://www.linkedin.com/voyager/api/jobs/jobPostings/${id}` +
                  `?decorationId=com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65`;
      try {
        const r = await fetch(url, {headers: HEADERS, credentials: 'include'});
        if (r.status !== 200) {
          window.__JD_PROGRESS.errors++;
        } else {
          const j    = await r.json();
          const jd   = extractText(j?.data?.description).trim();

          let company    = job.company || '?';
          let staffCount = null;
          for (const it of (j?.included || [])) {
            const t = it?.$type || '';
            if (typeof t === 'string' && /organization\.Company$/.test(t) && it.name) {
              company    = it.name;
              staffCount = it.staffCount || it.staffCountRange?.start || null;
              break;
            }
            if (!staffCount && it?.entityUrn && /_company:/.test(it.entityUrn) && it.name) {
              company    = it.name;
              staffCount = it.staffCount || it.staffCountRange?.start || null;
            }
          }

          const title    = j?.data?.title?.text || job.title || '';
          const listedAt = j?.data?.originalListedAt || j?.data?.listedAt || job.listedAt || null;
          const applies  = j?.data?.numApplicants    || j?.data?.applies  || null;

          window.__JD_DATA[id] = {jd, title, company, staffCount, listedAt, applies};
        }
      } catch (e) {
        window.__JD_PROGRESS.errors++;
      }
      window.__JD_PROGRESS.done++;
    }));
    await new Promise(res => setTimeout(res, BATCH_DELAY));
  }

  window.__JD_DONE = true;
  console.log(`JD fetch done: ${Object.keys(window.__JD_DATA).length} fetched, ${window.__JD_PROGRESS.errors} errors`);

  // Auto-download as ollama_input.json
  try {
    const b = new Blob([JSON.stringify(window.__JD_DATA)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'ollama_input.json';
    a.click();
  } catch (e) {
    window.__JD_ERR = (window.__JD_ERR || '') + '|dl:' + e;
    console.warn('Auto-download failed. Run: copy(JSON.stringify(window.__JD_DATA)) to get data.');
  }
})().catch(e => { window.__JD_ERR = String(e); window.__JD_DONE = true; });

"fetch_jds started — poll window.__JD_DONE";
