# Method-gated job-hunter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `SKILL.md` into a method-gated router (Browser / Apify / Keyless) where the chosen path feeds a single shared backbone (dedup → red-flag → score → YoE split → queue), driven by a new `hunt_config.json`.

**Architecture:** Thin-router `SKILL.md` + one reference file per pull-path + an externalized `references/backbone.md`. Three small new Python modules (`config.py`, `yoe_split.py`, `queue_writer.py`) make the deterministic backbone bits testable; the existing `dedup.py`, `pre_filter.py`, `mark_applied.py`, `score_jobs.py` are reused unchanged.

**Tech Stack:** Python 3.8+ stdlib only; `unittest` (run via `python3 -m unittest`); Markdown skill/reference docs.

**Spec:** `docs/superpowers/specs/2026-06-02-method-gated-job-hunter-design.md`

---

## File structure

| File | Responsibility |
|------|----------------|
| `scripts/pipeline/config.py` | Load `hunt_config.json` with defaults; one source of run knobs. |
| `scripts/pipeline/yoe_split.py` | Parse min YoE from JD text (fallback); classify/split matches into Primary/Stretch. |
| `scripts/pipeline/queue_writer.py` | Render the two-section (Primary/Stretch) queue markdown. |
| `assets/hunt_config.example.json` | Tracked template for the run config. |
| `tests/test_config.py`, `tests/test_yoe_split.py`, `tests/test_queue_writer.py` | Unit tests for the three modules. |
| `references/backbone.md` | The shared post-pull stage (dedup→red-flag→score→split→queue). |
| `references/path-browser.md` | Browser (voyager) pull mechanics. |
| `references/path-keyless.md` | Keyless public-API pull mechanics. |
| `references/path-apify.md` | Apify pull (renamed from `apify.md`). |
| `SKILL.md` | Router: config-load → gate → path handoff → backbone → present. |
| `README.md`, `.gitignore` | Document/ignore `hunt_config.json`. |

---

## Task 1: hunt_config loader + example template

**Files:**
- Create: `assets/hunt_config.example.json`
- Create: `scripts/pipeline/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the example template**

Create `assets/hunt_config.example.json`:

```json
{
  "window_hours": 24,
  "target_titles": ["Software Engineer", "Software Development Engineer", "Member of Technical Staff"],
  "geo_id": "102713980",
  "experience_filters": ["3", "4"],
  "yoe_threshold": 3,
  "score_threshold": 70,
  "dictionary": "assets/skills_dictionary.json",
  "redflag_path": "data/pipeline/redflag_companies.json",
  "seen_path": "data/pipeline/seen_jobs.json",
  "apify_actor": "curious_coder/linkedin-jobs-scraper"
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_config.py`:

```python
import os, sys, json, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import config  # noqa: E402


class TestLoadConfig(unittest.TestCase):
    def test_defaults_when_missing(self):
        cfg = config.load_config(os.path.join(tempfile.gettempdir(), "no_such_hunt_config.json"))
        self.assertEqual(cfg["yoe_threshold"], 3)
        self.assertEqual(cfg["score_threshold"], 70)
        self.assertIn("Software Engineer", cfg["target_titles"])

    def test_user_file_overrides_and_keeps_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"window_hours": 5, "score_threshold": 65}, fh)
            path = fh.name
        cfg = config.load_config(path)
        os.unlink(path)
        self.assertEqual(cfg["window_hours"], 5)      # overridden
        self.assertEqual(cfg["score_threshold"], 65)  # overridden
        self.assertEqual(cfg["yoe_threshold"], 3)     # default kept

    def test_none_values_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"window_hours": None}, fh)
            path = fh.name
        cfg = config.load_config(path)
        os.unlink(path)
        self.assertEqual(cfg["window_hours"], 24)      # None ignored → default

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json")
            path = fh.name
        cfg = config.load_config(path)
        os.unlink(path)
        self.assertEqual(cfg["yoe_threshold"], 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.config'`

- [ ] **Step 4: Write minimal implementation**

Create `scripts/pipeline/config.py`:

```python
#!/usr/bin/env python3
"""
config.py — Load data/pipeline/hunt_config.json (run knobs) with safe defaults.

Single source of run parameters for every path (browser / apify / keyless).
Missing file, missing keys, or null values all fall back to DEFAULTS.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..", "..")
DEFAULT_PATH = os.path.join(_ROOT, "data", "pipeline", "hunt_config.json")

DEFAULTS = {
    "window_hours": 24,
    "target_titles": [
        "Software Engineer",
        "Software Development Engineer",
        "Member of Technical Staff",
    ],
    "geo_id": "102713980",
    "experience_filters": ["3", "4"],
    "yoe_threshold": 3,
    "score_threshold": 70,
    "dictionary": "assets/skills_dictionary.json",
    "redflag_path": "data/pipeline/redflag_companies.json",
    "seen_path": "data/pipeline/seen_jobs.json",
    "apify_actor": "curious_coder/linkedin-jobs-scraper",
}


def load_config(path: str = None) -> dict:
    cfg = dict(DEFAULTS)
    p = path or DEFAULT_PATH
    if os.path.exists(p):
        try:
            with open(p) as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if v is not None})
        except (ValueError, OSError):
            pass
    return cfg
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest tests.test_config -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline/config.py tests/test_config.py assets/hunt_config.example.json
git commit -m "feat(pipeline): hunt_config loader + example template"
```

---

## Task 2: YoE min-parse + Primary/Stretch split

**Files:**
- Create: `scripts/pipeline/yoe_split.py`
- Test: `tests/test_yoe_split.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_yoe_split.py`:

```python
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import yoe_split  # noqa: E402


class TestParseMinYoe(unittest.TestCase):
    def test_range_returns_lower_bound(self):
        self.assertEqual(yoe_split.parse_min_yoe("We want 4-6 years of experience"), 4)

    def test_plus_form(self):
        self.assertEqual(yoe_split.parse_min_yoe("3+ years required"), 3)

    def test_no_numeric_mention_returns_none(self):
        self.assertIsNone(yoe_split.parse_min_yoe("Senior engineer, strong fundamentals"))

    def test_multiple_mentions_takes_minimum(self):
        # fallback parser is a lower-bound heuristic
        self.assertEqual(yoe_split.parse_min_yoe("2-3 years; 5 years preferred"), 2)


class TestClassify(unittest.TestCase):
    def test_above_threshold_is_stretch(self):
        self.assertEqual(yoe_split.classify(4, threshold=3), "stretch")

    def test_at_threshold_is_primary(self):
        self.assertEqual(yoe_split.classify(3, threshold=3), "primary")

    def test_none_is_primary(self):
        self.assertEqual(yoe_split.classify(None, threshold=3), "primary")


class TestSplitMatches(unittest.TestCase):
    def test_split_respects_preset_min_yoe(self):
        # caller (the model) may set min_yoe explicitly (handles word-numbers,
        # header-vs-body contradictions); the splitter must honor it.
        matches = [
            {"id": "1", "min_yoe": 5, "jd_summary": "3-5 years"},   # preset wins → stretch
            {"id": "2", "jd_summary": "3+ years"},                  # parsed 3 → primary
            {"id": "3", "jd_summary": "4-6 years"},                 # parsed 4 → stretch
            {"id": "4", "jd_summary": "Senior, no number"},         # None → primary
        ]
        primary, stretch = yoe_split.split_matches(matches, threshold=3)
        self.assertEqual({m["id"] for m in primary}, {"2", "4"})
        self.assertEqual({m["id"] for m in stretch}, {"1", "3"})
        # tags are written back
        self.assertTrue(all("stretch" in m and "min_yoe" in m for m in matches))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_yoe_split -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.yoe_split'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/pipeline/yoe_split.py`:

```python
#!/usr/bin/env python3
"""
yoe_split.py — Years-of-experience triage for the shared backbone.

parse_min_yoe() is a digit-only fallback heuristic. The authoritative min_yoe is
set by the model during scoring (it reads the full JD, resolves word-numbers like
"six years", and applies the header-wins rule for self-contradicting JDs). When a
match already carries min_yoe, the splitter honors it.

A role whose stated minimum exceeds the candidate's threshold (default 3 yrs) goes
to the Stretch section; everything else (incl. no explicit minimum) stays Primary.
"""
import re

_YOE_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:[-–]|to)?\s*(\d{1,2})?\s*\+?\s*years?", re.IGNORECASE)


def parse_min_yoe(text: str):
    """Lowest stated minimum YoE (digit forms only), or None if no numeric mention."""
    if not text:
        return None
    mins = [int(m.group(1)) for m in _YOE_RE.finditer(text)]
    return min(mins) if mins else None


def classify(min_yoe, threshold: int = 3) -> str:
    """'stretch' when an explicit minimum exceeds threshold, else 'primary'."""
    if min_yoe is not None and min_yoe > threshold:
        return "stretch"
    return "primary"


def split_matches(matches, threshold: int = 3, text_key: str = "jd_summary"):
    """Tag each match with min_yoe + stretch, and return (primary, stretch) lists.

    Honors a preset match['min_yoe']; otherwise falls back to parsing text_key.
    """
    primary, stretch = [], []
    for m in matches:
        mn = m.get("min_yoe")
        if mn is None:
            mn = parse_min_yoe(m.get(text_key, ""))
        m["min_yoe"] = mn
        is_stretch = classify(mn, threshold) == "stretch"
        m["stretch"] = is_stretch
        (stretch if is_stretch else primary).append(m)
    return primary, stretch
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_yoe_split -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline/yoe_split.py tests/test_yoe_split.py
git commit -m "feat(pipeline): YoE min-parse + Primary/Stretch split"
```

---

## Task 3: Two-section queue renderer

**Files:**
- Create: `scripts/pipeline/queue_writer.py`
- Test: `tests/test_queue_writer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_queue_writer.py`:

```python
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from pipeline import queue_writer  # noqa: E402


def _m(i, score, stretch=False, min_yoe=None):
    return {
        "id": i, "score": score, "title": f"Role {i}", "company": f"Co {i}",
        "url": f"https://www.linkedin.com/jobs/view/{i}",
        "resume_pdf": f"/x/{i}/resume.pdf",
        "matched_skills": ["go", "react"], "gap_skills": ["cassandra"],
        "jd_summary": "summary", "stretch": stretch, "min_yoe": min_yoe,
    }


class TestRenderQueue(unittest.TestCase):
    def setUp(self):
        self.primary = [_m("1", 84), _m("2", 72)]
        self.stretch = [_m("3", 82, stretch=True, min_yoe=4)]
        self.md = queue_writer.render_queue(
            "browser 5h (run X)", self.primary, self.stretch,
            scored_n=200, cand_n=210, threshold=3)

    def test_has_both_section_headers(self):
        self.assertIn("### Primary", self.md)
        self.assertIn("### Stretch", self.md)

    def test_header_counts(self):
        self.assertIn("2 primary", self.md)
        self.assertIn("1 stretch", self.md)

    def test_entries_have_apply_and_checkbox(self):
        self.assertIn("**JobId:** 1", self.md)
        self.assertIn("- [ ] Applied", self.md)

    def test_stretch_entry_shows_min_yoe(self):
        self.assertIn("**Min YoE:**", self.md)

    def test_primary_entry_omits_min_yoe(self):
        primary_block = self.md.split("### Stretch")[0]
        self.assertNotIn("**Min YoE:**", primary_block)

    def test_empty_sections_render_placeholder(self):
        md = queue_writer.render_queue("t", [], [], 0, 0, 3)
        self.assertIn("_none_", md)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_queue_writer -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.queue_writer'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/pipeline/queue_writer.py`:

```python
#!/usr/bin/env python3
"""
queue_writer.py — Render the two-section (Primary / Stretch) match queue markdown.

Primary = roles within the candidate's YoE; Stretch = roles whose JD states a
minimum above the threshold (kept for visibility + dedup, out of the main list).
"""


def render_entry(m: dict, show_yoe: bool = False) -> str:
    yoe = ""
    if show_yoe:
        label = m.get("yoe_label") or (f"min {m['min_yoe']} yrs" if m.get("min_yoe") else "4+ yrs")
        yoe = f"\n**Min YoE:** {label}"
    return (
        f"#### [{m['score']}] {m['title']} — {m['company']}\n"
        f"**Apply:** {m['url']}  |  **JobId:** {m['id']}{yoe}\n"
        f"**Resume:** {m.get('resume_pdf', 'N/A')}\n"
        f"**Strengths:** {', '.join(m.get('matched_skills', []))}\n"
        f"**Gaps:** {', '.join(m.get('gap_skills', []))}\n"
        f"> {m.get('jd_summary', '')}\n"
        f"- [ ] Applied"
    )


def _section(title: str, items, show_yoe: bool) -> str:
    if not items:
        return f"### {title}\n\n_none_\n"
    body = "\n\n".join(render_entry(m, show_yoe) for m in items)
    return f"### {title}\n\n{body}\n"


def render_queue(run_label: str, primary, stretch, scored_n: int, cand_n: int,
                 threshold: int = 3) -> str:
    header = (
        f"## Hunt — {run_label} — {len(primary)} primary + {len(stretch)} stretch "
        f"/ {scored_n} scored / {cand_n} candidates\n"
    )
    pri = _section("Primary matches — within YoE / no stated minimum", primary, False)
    stre = _section(
        f"Stretch — JD states a minimum above {threshold} yrs (kept for dedup, not in the main list)",
        stretch, True)
    return f"{header}\n{pri}\n{stre}\n---\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_queue_writer -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline/queue_writer.py tests/test_queue_writer.py
git commit -m "feat(pipeline): two-section Primary/Stretch queue renderer"
```

---

## Task 4: `references/backbone.md`

**Files:**
- Create: `references/backbone.md`

- [ ] **Step 1: Write the backbone reference**

Create `references/backbone.md` documenting the shared post-pull stage. It MUST contain, in order, these sections with the stated content:

1. **Input contract** — every path hands the backbone a list of normalized candidates `[{id, title, company, url, kw}]`, plus the loaded `hunt_config` and `profile`.
2. **Step 1 — Dedup.** Use `scripts/pipeline/dedup.py` against `config["seen_path"]`. Key = `li:<id>` from the URL, else `title::company`. Drop anything already present or `status:"applied"`. Show: `from pipeline import dedup`.
3. **Step 2 — Red-flag filter.** Use `pipeline.pre_filter.is_redflag_company(company)` (backed by `config["redflag_path"]`). Drop matches with reason `"red-flag company"`. State that companies are added by editing `redflag_companies.json` (`patterns` regex + `exact`).
4. **Step 3 — Score.** State the output contract: each job gets a numeric `score`, `matched_skills`, `gap_skills`, `jd_summary`. Keyless/Apify use `score_jobs.py` (+ optional LLM re-weight from `references/scoring.md`); the browser path LLM-scores fetched JDs against the rubric. Both emit the same `jobs_scored` shape.
5. **Step 4 — YoE split.** Use `pipeline.yoe_split.split_matches(matches, threshold=config["yoe_threshold"])`. Note the model should set `min_yoe` per match while scoring (word-numbers, header-wins); the parser is a fallback. Matches = `score >= config["score_threshold"]`.
6. **Step 5 — Persist + queue.** Record ALL scored IDs in `seen_jobs.json` (stretch included, so dedup keeps filtering them). Render the queue with `pipeline.queue_writer.render_queue(...)`; browser path writes `data/pipeline/BROWSER_QUEUE.md`, Apify/keyless write `APPLY_QUEUE.md`.
7. **Applied loop** — after the user ticks `- [x] Applied`, run `python3 scripts/pipeline/mark_applied.py` to promote those IDs to `status:"applied"` and strike them from the queue.

- [ ] **Step 2: Commit**

```bash
git add references/backbone.md
git commit -m "docs: add shared-backbone reference (dedup/red-flag/score/split/queue)"
```

---

## Task 5: `references/path-browser.md`

**Files:**
- Create: `references/path-browser.md`

- [ ] **Step 1: Write the browser-path reference**

Create `references/path-browser.md`. It MUST document, with the exact strings, these sections:

1. **Prereq** — an authenticated Claude-in-Chrome LinkedIn tab. CSRF token from the `JSESSIONID` cookie.
2. **ID scrape** — `GET /voyager/api/voyagerJobsDashJobCards?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-227&count=25&q=jobSearch&query=(origin:JOB_SEARCH_PAGE_JOB_FILTER,keywords:<title>,locationUnion:(geoId:<geo_id>),selectedFilters:(timePostedRange:List(r<window_seconds>),employmentType:List(F),experience:List(<experience_filters>)),spellCorrectionEnabled:true)&start=<n>`. Headers: `csrf-token`, `x-restli-protocol-version: 2.0.0`, `accept: application/vnd.linkedin.normalized+json+2.1`. Extract ID from `elements[].jobCardUnion['*jobPostingCard']` (regex `\((\d{6,})`); paginate `start += 25` until `start >= paging.total`; self-limit each CDP call to ~35s and resume. Loop over `target_titles`; `window_seconds = window_hours * 3600`.
3. **Build links** — `https://www.linkedin.com/jobs/view/<id>`.
4. **JD fetch (CRITICAL — voyager, never WebFetch)** — `GET /voyager/api/jobs/jobPostings/<id>?decorationId=com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65`. Returns `description.text`, `title`, `companyDetails` (name), `formattedLocation`. State plainly: WebFetch on `/jobs/view/<id>` walls (login/429) and silently scores good jobs 0 — always use voyager.
5. **Browser→disk transfer** — render the JSON into an `<article>` element and read it with `get_page_text`; keep each chunk **under 50 KB** (it errors above that). `javascript_tool` inline return truncates ~1 KB.
6. **Score** — fan out parallel agents (batch the candidates); each WebFetch-free agent scores from the supplied JD text against the rubric and writes a per-batch file. Re-fetch any `fetched:false` rows via voyager before trusting the distribution.
7. **Hand to backbone** — see `references/backbone.md`. Writes `BROWSER_QUEUE.md` + the timestamped `data/pipeline/browser_runs/<date>_<time>_<window>/` folder (`jobs_raw.json`, `candidates_fresh.json`, `jobs_scored.json`, `matches.json`, `<id>_<idx>/resume.{tex,pdf}`).

- [ ] **Step 2: Commit**

```bash
git add references/path-browser.md
git commit -m "docs: add browser (voyager) path reference"
```

---

## Task 6: `references/path-keyless.md`

**Files:**
- Create: `references/path-keyless.md`

- [ ] **Step 1: Write the keyless-path reference**

Create `references/path-keyless.md` documenting the free path. It MUST contain:

1. **Live fetch** — the `scripts/fetch_jobs.py` invocation (Adzuna + public APIs), reading `target_titles`/`window_hours` from config (`--since-days` from `window_hours/24` rounded up, min 1). Note Adzuna key is optional.
2. **Browse links** — the `scripts/search_urls.py` invocation for ToS-safe deep links (`--category general,tech`).
3. **Hand to backbone** — candidates already carry JD text, so scoring uses `score_jobs.py` (dictionary ATS + optional LLM re-weight per `references/scoring.md`). Writes `APPLY_QUEUE.md`.

Reuse the command blocks already in the current `SKILL.md` steps 3–4 and 6–7 verbatim; do not invent new flags.

- [ ] **Step 2: Commit**

```bash
git add references/path-keyless.md
git commit -m "docs: add keyless public-API path reference"
```

---

## Task 7: `references/path-apify.md` (rename + reframe)

**Files:**
- Rename: `references/apify.md` → `references/path-apify.md`

- [ ] **Step 1: Rename the file**

```bash
git mv references/apify.md references/path-apify.md
```

- [ ] **Step 2: Add a path framing header**

Prepend a short intro to `references/path-apify.md`: this is the **Apify pull path** of the gated skill — it produces normalized candidates, then hands off to `references/backbone.md` (writes `APPLY_QUEUE.md`). The actor is `config["apify_actor"]`; titles/window from config. Keep all existing Apify content below unchanged.

- [ ] **Step 3: Update any in-repo references to the old filename**

Run: `grep -rn "apify.md" SKILL.md README.md references/ scripts/`
For each hit that points to `references/apify.md`, update it to `references/path-apify.md`.

- [ ] **Step 4: Commit**

```bash
git add -A references/ SKILL.md README.md
git commit -m "docs: reframe apify.md as path-apify.md (Apify pull path)"
```

---

## Task 8: Rewrite `SKILL.md` as the router

**Files:**
- Modify: `SKILL.md` (keep YAML front-matter unchanged; rewrite the body)

- [ ] **Step 1: Rewrite the workflow body**

Keep the existing front-matter (lines 1–15) verbatim. Replace the body with these sections:

1. **Ground rules** — keep the existing three bullets (ToS, network, information-not-advice). Add: LinkedIn JDs are fetched via the authenticated voyager API, never WebFetch.
2. **Step 0 — Load config + profile.** `from pipeline.config import load_config`; read `data/profile.json` for the HAVE skills. State both feed every path.
3. **Step 1 — Build/confirm the profile** — keep the existing profile guidance (one-line confirm).
4. **Step 2 — Method gate (ALWAYS ASK).** Present exactly:
   > Which source method?
   > **A) Browser** — Claude-in-Chrome + voyager (authenticated LinkedIn; richest)
   > **B) Apify** — actor pull (pay-per-result)
   > **C) Keyless** — public APIs + ToS-safe browse links (free)

   Then open the matching reference: A → `references/path-browser.md`, B → `references/path-apify.md`, C → `references/path-keyless.md`. Run that path's PULL steps to produce normalized candidates.
5. **Step 3 — Shared backbone.** Run `references/backbone.md` (dedup → red-flag → score → YoE split → persist + queue).
6. **Step 4 — Present.** Summarize Primary vs Stretch counts and the top handful; offer the `resume-builder` handoff for matches `>= score_threshold`.
7. **Reference files** — list `backbone.md`, `path-browser.md`, `path-apify.md`, `path-keyless.md`, `scoring.md`, `sources.md`, `assets/hunt_config.example.json`, `assets/candidate.example.json`.

Remove the old linear steps 2–8 (their content now lives in the path/backbone references).

- [ ] **Step 2: Sanity-check the skill still parses / references resolve**

Run: `grep -n "references/" SKILL.md`
Expected: only `path-browser.md`, `path-apify.md`, `path-keyless.md`, `backbone.md`, `scoring.md`, `sources.md` (no bare `apify.md`).

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "feat(skill): method-gated router (Browser/Apify/Keyless) over shared backbone"
```

---

## Task 9: README + .gitignore + full suite

**Files:**
- Modify: `README.md`, `.gitignore`

- [ ] **Step 1: Document hunt_config in README**

In `README.md`, under the existing "Where state lives" section, add a row/note: run knobs live in `data/pipeline/hunt_config.json` (template: `assets/hunt_config.example.json`), read once at the top of every run by `scripts/pipeline/config.py`. Update the Layout tree to show `assets/hunt_config.example.json` and `scripts/pipeline/{config,yoe_split,queue_writer}.py`.

- [ ] **Step 2: Confirm hunt_config.json is git-ignored**

`data/` is already fully ignored, so `data/pipeline/hunt_config.json` is covered. Verify:

Run: `git check-ignore data/pipeline/hunt_config.json`
Expected: prints the path (ignored). If it does NOT, add `hunt_config.json` to `.gitignore`.

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK, test count = previous 46 + new (4 config + 8 yoe + 6 queue = 18) → ~64 tests.

- [ ] **Step 4: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: document hunt_config; confirm it stays git-ignored"
```

---

## Self-review notes (author)

- **Spec coverage:** gate (Task 8) · 3 paths (Tasks 5/6/7) · shared backbone (Task 4) · hunt_config (Task 1) · YoE split (Task 2) · queue split (Task 3) · tests (Tasks 1–3, 9) · voyager-not-WebFetch rule (Tasks 5, 8) · scoring-mechanism-differs nuance (Task 4 step 4). All spec sections map to a task.
- **No placeholders:** code tasks ship full code + tests; doc tasks enumerate required sections with exact endpoint/decoration strings.
- **Type consistency:** `load_config`→dict keys reused as `config["..."]` in Tasks 4–8; `split_matches(matches, threshold)` and `render_queue(run_label, primary, stretch, scored_n, cand_n, threshold)` signatures match across Tasks 2/3/4. Match dicts carry `score, title, company, url, id, resume_pdf, matched_skills, gap_skills, jd_summary, min_yoe, stretch` consistently.
