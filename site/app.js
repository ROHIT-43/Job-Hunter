// Fresh Dev Jobs — renders site/data/jobs.json (scripts/live/run.py) and
// site/data/posts.json (LinkedIn hiring posts, scripts/live/posts.py), both hourly.
(() => {
  "use strict";

  const DATA_URL = "data/jobs.json";
  const POSTS_URL = "data/posts.json";
  const REFRESH_MS = 10 * 60 * 1000;
  const $ = (sel) => document.querySelector(sel);

  let data = { jobs: [], config: { salary_buckets_lpa: [10, 20], max_age_hours: 24 } };
  let posts = { jobs: [], status: { ok: true } };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const opened = new Set(); // expanded job ids survive re-renders

  // Applied jobs live only in this browser (localStorage) as full snapshots, so they
  // stay listed after they drop out of the 24h feed. Export/Import moves them.
  const APPLIED_KEY = "fdj-applied";
  let applied = (() => {
    try { return JSON.parse(store.get(APPLIED_KEY) || "{}") || {}; } catch { return {}; }
  })();
  const saveApplied = () => store.set(APPLIED_KEY, JSON.stringify(applied));
  const appliedJobs = () => Object.values(applied)
    .map((a) => ({ ...a.job, applied_at: a.applied_at }))
    .sort((a, b) => Date.parse(b.applied_at) - Date.parse(a.applied_at));

  // "Not interested" works the same way; snapshots older than 30 days are dropped
  // (the job left the 24h feed long ago, so there is nothing left to hide).
  const HIDDEN_KEY = "fdj-hidden";
  let hidden = (() => {
    try {
      const all = JSON.parse(store.get(HIDDEN_KEY) || "{}") || {};
      const cutoff = Date.now() - 30 * 86400000;
      return Object.fromEntries(Object.entries(all).filter(([, h]) => Date.parse(h.hidden_at) > cutoff));
    } catch { return {}; }
  })();
  const saveHidden = () => store.set(HIDDEN_KEY, JSON.stringify(hidden));
  const hiddenJobs = () => Object.values(hidden)
    .map((h) => ({ ...h.job, hidden_at: h.hidden_at }))
    .sort((a, b) => Date.parse(b.hidden_at) - Date.parse(a.hidden_at));

  // sections listing your own saved jobs rather than the live feed
  const personalJobs = (section) => (section === "applied" ? appliedJobs() : hiddenJobs());
  const isPersonal = (section) => section === "applied" || section === "hidden";
  const state = { section: "eligible", bucket: "", q: "", co: "", city: "", kw: "", age: "24" };

  // ── helpers ────────────────────────────────────────────────────────────
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));


  function bucketLabels() {
    const [a, b] = data.config.salary_buckets_lpa || [10, 20];
    return [`0-${a}`, `${a}-${b}`, `${b}+`, "none"];
  }

  const bucketName = (b) => (b === "none" ? "Not disclosed" : `${b} LPA`);

  function city(job) {
    const first = (job.location || "").split(",")[0].trim();
    return /^india$/i.test(first) ? "India (other)" : first || "—";
  }

  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  }

  function ageHours(job) {
    return (Date.now() - Date.parse(job.posted_at || job.first_seen_at)) / 3600000;
  }

  function salaryTag(s) {
    if (!s) return "";
    if (s.source === "none") {
      const why = { pending: "Salary lookup pending", internship: "Internship (stipend)",
                    "staffing agency": "Via staffing agency" }[s.reason] || "Not disclosed";
      return `<span class="tag salary-none" title="${esc(s.reason || "")}">${esc(why)}</span>`;
    }
    const range = s.min_lpa === s.max_lpa ? `₹${s.min_lpa} LPA` : `₹${s.min_lpa}–${s.max_lpa} LPA`;
    const basis = s.basis === "ctc" ? " (CTC)" : "";
    const sources = (s.sources || []).map((x) => x.title).filter(Boolean).join(", ");
    const label = { listed: "Listed", web: "Web data", approx: "Approx.", override: "Set manually" }[s.source] || "";
    const title = {
      listed: "Stated in the job posting",
      web: `Reported salaries for this company + role${sources ? ` — ${sources}` : ""}` +
           `${s.year ? ` (${s.year})` : ""}; confidence: ${s.confidence || "low"}`,
      approx: `${s.note || "Company's general SWE range"}${sources ? ` — ${sources}` : ""}`,
      override: s.note || "Set in salary_overrides.json",
    }[s.source] || "";
    return `<span class="tag salary-${esc(s.source)}" title="${esc(title)}">${esc(range + basis)} · ${esc(label)}</span>`;
  }

  function yoeTag(job) {
    if (job.yoe_min == null) return `<span class="tag">YoE not stated</span>`;
    const label = job.yoe_min === 0 ? "Fresher / 0 yrs"
      : `Min ${job.yoe_min} yr${job.yoe_min === 1 ? "" : "s"}`;
    return `<span class="tag yoe" title="Minimum experience the job description asks for">${label}</span>`;
  }

  // ── filtering ──────────────────────────────────────────────────────────
  function live() {
    const max = data.config.max_age_hours || 24;
    return data.jobs.filter((j) => ageHours(j) <= max && !applied[j.id] && !hidden[j.id]);
  }

  function livePosts() {
    return (posts.jobs || []).filter((j) => ageHours(j) <= 24 && !applied[j.id] && !hidden[j.id]);
  }

  function matches(job, { ignoreBucket = false, ignoreSection = false, isApplied = false, isPost = false } = {}) {
    if (isPost) {
      if (ageHours(job) > Number(state.age)) return false;
    } else if (!isApplied) {
      if (!ignoreSection && job.section !== state.section) return false;
      if (!ignoreBucket && state.bucket && job.salary?.bucket !== state.bucket) return false;
      if (ageHours(job) > Number(state.age)) return false;
    }
    if (state.city && city(job) !== state.city) return false;
    if (state.kw && !(job.keywords || []).includes(state.kw)) return false;
    // every word must appear: "backend java" matches "Java Backend Engineer"
    const words = (q) => q.toLowerCase().split(/\s+/).filter(Boolean);
    const title = (job.title || "").toLowerCase();
    if (state.q && !words(state.q).every((w) => title.includes(w))) return false;
    const company = (job.company || "").toLowerCase();
    if (state.co && !words(state.co).every((w) => company.includes(w))) return false;
    return true;
  }

  // ── rendering ──────────────────────────────────────────────────────────
  function renderTabs(jobs) {
    document.querySelectorAll("[data-section]").forEach((btn) => {
      btn.setAttribute("aria-selected", String(btn.dataset.section === state.section));
    });
    document.querySelectorAll("[data-count-section]").forEach((el) => {
      const s = el.dataset.countSection;
      el.textContent = s === "posts"
        ? livePosts().filter((j) => matches(j, { isPost: true })).length
        : isPersonal(s)
        ? personalJobs(s).filter((j) => matches(j, { isApplied: true })).length
        : jobs.filter((j) => j.section === s && matches(j, { ignoreBucket: true, ignoreSection: true })).length;
    });

    const inPersonal = isPersonal(state.section);
    const bar = $(".buckets");
    bar.hidden = inPersonal || state.section === "posts";
    $("#posts-status").hidden = state.section !== "posts" || posts.status?.ok !== false;
    $("#posts-status").textContent = `⚠ LinkedIn posts paused: ${posts.status?.message || "unknown problem"}`;
    $("#age").disabled = inPersonal;
    $("#applied-tools").hidden = state.section !== "applied";
    const labels = bucketLabels();
    if (!labels.includes(state.bucket)) state.bucket = labels[0];
    bar.innerHTML = labels.map((b) => {
      const n = jobs.filter((j) => j.salary?.bucket === b && matches(j, { ignoreBucket: true })).length;
      return `<button role="tab" class="bucket-btn" data-bucket="${esc(b)}" aria-selected="${b === state.bucket}">
        ${esc(bucketName(b))} <span class="count">${n}</span></button>`;
    }).join("");
  }

  function renderJobs(jobs) {
    const lastScrape = data.last_scrape_at ? Date.parse(data.last_scrape_at) : 0;
    const section = state.section;
    const inPersonal = isPersonal(section);
    const shown = section === "posts"
      ? livePosts().filter((j) => matches(j, { isPost: true })).sort(byCompany)
      : inPersonal
      ? personalJobs(section).filter((j) => matches(j, { isApplied: true }))
      : jobs.filter((j) => matches(j));
    $("#jobs").innerHTML = shown.map((j) => {
      if (j.kind === "post") return postCard(j, section, inPersonal);
      const isNew = !inPersonal && lastScrape && Date.parse(j.first_seen_at) >= lastScrape;
      const initial = esc((j.company || "?").trim().charAt(0).toUpperCase());
      const avatar = j.logo
        ? `<img src="${esc(j.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.textContent=this.parentNode.dataset.i">`
        : initial;
      const extra = [j.applicants, j.employment_type, j.seniority].filter(Boolean)
        .map((t) => `<span class="tag">${esc(t)}</span>`).join("");
      const open = opened.has(j.id);
      return `<li class="job${open ? " open" : ""}" data-id="${esc(j.id)}">
        <div class="avatar" data-i="${initial}">${avatar}</div>
        <div class="job-main">
          <a class="job-title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${isNew ? '<span class="new">NEW</span>' : ""}
          <div class="job-co">${esc(j.company)} · ${esc(j.location)}</div>
          <div class="tags">${salaryTag(j.salary)}${yoeTag(j)}${extra}</div>
          ${j.snippet ? `<p class="snippet">${esc(j.snippet)}</p><button class="more" type="button">${open ? "Hide" : "Show"} details</button>` : ""}
        </div>
        <div class="job-side">
          <span class="ago" title="${esc(new Date(j.posted_at).toLocaleString())}">${
            section === "applied" ? `applied ${ago(j.applied_at)}`
              : section === "hidden" ? `hidden ${ago(j.hidden_at)}` : ago(j.posted_at)}</span>
          <div class="actions">
            ${section === "applied" ? '<button class="mark" type="button" data-unapply>Undo</button>'
              : section === "hidden" ? '<button class="mark" type="button" data-unhide>Undo</button>'
              : `<button class="mark skip" type="button" data-hide title="Hide this job">Not interested</button>
                 <button class="mark" type="button" data-applied title="Move to Applied">✓ Applied</button>`}
            <a class="apply" href="${esc(j.url)}" target="_blank" rel="noopener">${inPersonal ? "Open" : "Apply"}</a>
          </div>
        </div>
      </li>`;
    }).join("");
    $("#empty").hidden = shown.length > 0;
    $("#empty").textContent = section === "applied"
      ? "Nothing marked as applied yet. Use “✓ Applied” on a job to move it here."
      : section === "hidden"
      ? "No hidden jobs. “Not interested” on a job moves it here (kept for 30 days)."
      : section === "posts"
      ? "No matching LinkedIn hiring posts right now. Posts are checked every hour."
      : "No jobs match these filters right now. New jobs arrive every hour.";
    $("#result-line").textContent = shown.length
      ? `${shown.length} job${shown.length === 1 ? "" : "s"} · ${section === "applied" ? "most recently applied first"
        : section === "hidden" ? "most recently hidden first" : "newest first"}` : "";
  }

  function actionsHtml(j, section, inPersonal, openLabel) {
    return section === "applied" ? '<button class="mark" type="button" data-unapply>Undo</button>'
      : section === "hidden" ? '<button class="mark" type="button" data-unhide>Undo</button>'
      : `<button class="mark skip" type="button" data-hide title="Hide this">Not interested</button>
         <button class="mark" type="button" data-applied title="Move to Applied">✓ Applied</button>`;
  }

  function agoLabel(j, section) {
    return section === "applied" ? `applied ${ago(j.applied_at)}`
      : section === "hidden" ? `hidden ${ago(j.hidden_at)}` : ago(j.posted_at);
  }

  // Posts: best company first (Claude's 0-100 company_score), newest first within a score
  function byCompany(a, b) {
    return (b.company_score ?? -1) - (a.company_score ?? -1)
      || Date.parse(b.posted_at) - Date.parse(a.posted_at);
  }

  function companyTag(j) {
    const s = j.company_score;
    if (s == null) return "";
    const [label, cls] = s >= 90 ? ["Top company", "top"] : s >= 75 ? ["Strong company", "strong"]
      : s >= 60 ? ["Good company", "good"] : s >= 45 ? ["Average company", ""] : ["Lesser-known", "low"];
    return `<span class="tag co-${cls || "avg"}" title="Claude's company rating: ${s}/100">${label}</span>`;
  }

  // A role found in a LinkedIn hiring post (not a job listing)
  function postCard(j, section, inPersonal) {
    const p = j.poster || {};
    const isNew = !inPersonal && posts.last_scrape_at && Date.parse(j.first_seen_at) >= Date.parse(posts.last_scrape_at);
    const open = opened.has(j.id);
    const tags = [
      companyTag(j),
      j.salary?.source === "listed" ? salaryTag(j.salary) : "",
      yoeTag(j),
      j.location_unclear ? '<span class="tag" title="The post does not say where — check it">Location not stated</span>' : "",
      j.work_mode ? `<span class="tag">${esc(j.work_mode)}</span>` : "",
      j.via_recruiter ? '<span class="tag">Via recruiter</span>' : "",
      j.has_email ? '<span class="tag" title="The post includes an email to send your CV to — open the post">✉ Email in post</span>' : "",
      ...(j.skills || []).slice(0, 4).map((s) => `<span class="tag">${esc(s)}</span>`),
    ].join("");
    const applyLink = (j.apply_links || [])[0];
    const emails = (j.apply_emails || []).map((e) => `<a href="mailto:${esc(e)}">${esc(e)}</a>`).join(", ");
    return `<li class="job post${open ? " open" : ""}" data-id="${esc(j.id)}">
      <div class="avatar" data-i="${esc((p.name || "?").charAt(0).toUpperCase())}">${esc((p.name || "?").charAt(0).toUpperCase())}</div>
      <div class="job-main">
        <a class="job-title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${isNew ? '<span class="new">NEW</span>' : ""}
        <div class="job-co">${esc(j.company)}${j.location ? ` · ${esc(j.location)}${j.location_inferred ? " (likely)" : ""}` : ""}</div>
        <div class="poster">Posted by ${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name)}${p.headline ? ` — ${esc(p.headline)}` : ""}</div>
        <div class="tags">${tags}</div>
        ${j.snippet ? `<p class="snippet">${esc(j.snippet)}${emails ? `<br>✉ ${emails}` : ""}</p><button class="more" type="button">${open ? "Hide" : "Show"} post</button>` : ""}
      </div>
      <div class="job-side">
        <span class="ago" title="${esc(new Date(j.posted_at).toLocaleString())}">${agoLabel(j, section)}</span>
        <div class="actions">
          ${actionsHtml(j, section, inPersonal)}
          ${applyLink ? `<a class="mark" href="${esc(applyLink)}" target="_blank" rel="noopener">Apply link</a>` : ""}
          <a class="apply" href="${esc(j.url)}" target="_blank" rel="noopener">Open post</a>
        </div>
      </div>
    </li>`;
  }

  function fillSelect(sel, values, current) {
    const first = sel.options[0].outerHTML;
    sel.innerHTML = first + values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    sel.value = values.includes(current) ? current : "";
  }

  function render() {
    const jobs = live();
    const filterSource = state.section === "posts" ? livePosts() : jobs;
    const counts = (f) => Object.entries(jobs.reduce((m, j) => (f(j).forEach((k) => (m[k] = (m[k] || 0) + 1)), m), {}))
      .sort((a, b) => b[1] - a[1]).map(([k]) => k);
    const countsIn = (list, f) => Object.entries(list.reduce((m, j) => (f(j).forEach((k) => (m[k] = (m[k] || 0) + 1)), m), {}))
      .sort((a, b) => b[1] - a[1]).map(([k]) => k);
    fillSelect($("#city"), countsIn(filterSource, (j) => [city(j)]), state.city);
    fillSelect($("#kw"), countsIn(filterSource, (j) => j.keywords || []), state.kw);
    $("#companies").innerHTML = counts((j) => [j.company || ""])
      .concat(appliedJobs().map((j) => j.company))
      .filter((c, i, all) => c && all.indexOf(c) === i)
      .map((c) => `<option value="${esc(c)}">`).join("");
    state.city = $("#city").value;
    state.kw = $("#kw").value;
    renderTabs(jobs);
    renderJobs(jobs);

    const updated = data.generated_at ? ago(data.generated_at).replace(" ago", "") : "—";
    $("#meta").textContent = `${jobs.length} software jobs in India · last 24h · updated ${updated} ago`;
    // the hourly workflow should refresh this; if it hasn't for 3h, something is stuck
    const staleHours = data.generated_at ? (Date.now() - Date.parse(data.generated_at)) / 3600000 : 0;
    $("#stale").hidden = staleHours < 3;
    $("#stale").textContent = `⚠ Not updated for ${Math.floor(staleHours)}h — the hourly workflow may be stuck. ` +
      "Check the repo's Actions tab.";
    saveState();
  }

  // ── state in URL hash (shareable) + localStorage ───────────────────────
  function saveState() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) if (v && !(k === "age" && v === "24")) p.set(k, v);
    const hash = p.toString();
    history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
    store.set("fdj-state", hash);
  }

  function loadState() {
    const raw = location.hash.slice(1) || store.get("fdj-state") || "";
    const p = new URLSearchParams(raw);
    for (const k of Object.keys(state)) if (p.has(k)) state[k] = p.get(k);
    $("#q").value = state.q;
    $("#co").value = state.co;
    $("#age").value = state.age;
  }

  // ── events ─────────────────────────────────────────────────────────────
  function bind() {
    document.addEventListener("click", (e) => {
      const sec = e.target.closest("[data-section]");
      if (sec) { state.section = sec.dataset.section; render(); return; }
      const b = e.target.closest("[data-bucket]");
      if (b) { state.bucket = b.dataset.bucket; render(); return; }
      const mark = e.target.closest("[data-applied], [data-unapply], [data-hide], [data-unhide]");
      if (mark) {
        const id = mark.closest(".job").dataset.id;
        const now = new Date().toISOString();
        const job = data.jobs.find((j) => j.id === id) || (posts.jobs || []).find((j) => j.id === id);
        if (mark.hasAttribute("data-applied") && job) applied[id] = { job, applied_at: now };
        if (mark.hasAttribute("data-unapply")) delete applied[id];
        if (mark.hasAttribute("data-hide") && job) hidden[id] = { job, hidden_at: now };
        if (mark.hasAttribute("data-unhide")) delete hidden[id];
        saveApplied();
        saveHidden();
        render();
        return;
      }
      if (e.target.closest("#export-applied")) { exportApplied(); return; }
      if (e.target.closest("#import-applied")) { $("#import-file").click(); return; }
      const more = e.target.closest(".more");
      if (more) {
        const li = more.closest(".job");
        li.classList.toggle("open");
        if (li.classList.contains("open")) opened.add(li.dataset.id); else opened.delete(li.dataset.id);
        more.textContent = li.classList.contains("open") ? "Hide details" : "Show details";
      }
    });
    let t;
    $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 150); });
    $("#co").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.co = e.target.value.trim(); render(); }, 150); });
    $("#city").addEventListener("change", (e) => { state.city = e.target.value; render(); });
    $("#kw").addEventListener("change", (e) => { state.kw = e.target.value; render(); });
    $("#age").addEventListener("change", (e) => { state.age = e.target.value; render(); });
    $("#import-file").addEventListener("change", importApplied);
    $("#theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      store.set("fdj-theme", document.documentElement.dataset.theme);
    });
  }

  function exportApplied() {
    const blob = new Blob([JSON.stringify(applied, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `applied-jobs-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function importApplied(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const incoming = JSON.parse(await file.text());
      let n = 0;
      for (const [id, a] of Object.entries(incoming || {})) {
        if (a && a.job && a.applied_at && !applied[id]) { applied[id] = a; n++; }
      }
      saveApplied();
      render();
      $("#result-line").textContent = `Imported ${n} applied job${n === 1 ? "" : "s"}.`;
    } catch {
      $("#result-line").textContent = "That file isn't an applied-jobs export.";
    }
  }

  async function load() {
    try {
      const r = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      data = await r.json();
      data.config = data.config || { salary_buckets_lpa: [10, 20], max_age_hours: 24 };
    } catch (err) {
      $("#meta").textContent = "Couldn't load jobs — retrying soon.";
      return;
    }
    try {  // posts are optional: the jobs list works without them
      const r = await fetch(`${POSTS_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (r.ok) posts = await r.json();
    } catch { /* keep the previous posts */ }
    render();
  }

  const savedTheme = store.get("fdj-theme");
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  loadState();
  bind();
  load();
  setInterval(load, REFRESH_MS);
  setInterval(() => data.jobs.length && render(), 60 * 1000); // keep "Xm ago" + 24h cutoff fresh
})();
