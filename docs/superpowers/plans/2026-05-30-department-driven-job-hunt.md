# Department-driven Job Hunt + Unified ATS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace keyword-driven job fetching with a department-taxonomy filter and score every job through one unified local ATS scorer, so a single run sweeps India + global-remote + visa-sponsored roles (last 30 days) into one ATS-ranked report.

**Architecture:** Approach A — keep `fetch_jobs.py` / `apify_scrape.py` as entry points but move shared logic into two new modules, `scripts/lib/department.py` (taxonomy + classifier) and `scripts/lib/ats.py` (master skill dictionary + scorer + company tiers). A new `scripts/score_jobs.py` replaces both old scorers (`ats_scorer.py`, `rank_jobs.py`), which are backed up under `scripts/_legacy/` and deleted from the main path. Two data assets — `assets/departments.json` and `assets/skills_dictionary.json` — keep the taxonomy and vocabulary tunable without code edits.

**Tech Stack:** Python 3 standard library only (no third-party deps at runtime). Tests use the stdlib `unittest` runner (`python -m unittest`).

---

## Spec reference

Design: `docs/superpowers/specs/2026-05-30-department-driven-job-hunt-design.md`

Key decisions locked in:
- Fetch by **department**, never keyword. Default departments on: `software`, `engineering`, `technology`. Off by default (opt-in): `data`, `devops`, `security`, `qa`.
- One run fetches **all three buckets** (india/remote/visa), merges, dedups on `(title, company)`.
- **Unified local ATS** via a master skill dictionary: `ATS% = |JD∩HAVE| / |JD|`. Low-signal flag when `|JD| < 3`.
- Company tiers preserved as a tiebreaker only.

## File structure

**Create:**
- `scripts/lib/__init__.py` — package marker (empty).
- `scripts/lib/paths.py` — repo-root + assets path helper (one responsibility: locating bundled assets).
- `scripts/lib/department.py` — taxonomy loader, `classify`, `matches`, `default_departments`, `facet_codes`.
- `scripts/lib/ats.py` — dictionary loader, `build_alias_index`, `extract_jd_skills`, `score_job`, plus the company-tier logic moved from `ats_scorer.py`.
- `scripts/score_jobs.py` — single scoring CLI (replaces `ats_scorer.py` + `rank_jobs.py`).
- `assets/departments.json` — taxonomy: per-department title/tag matchers + per-source native facet codes + `default_on`.
- `assets/skills_dictionary.json` — master tech-skill vocabulary (canonical → aliases).
- `tests/__init__.py` — empty.
- `tests/test_department.py`, `tests/test_ats.py`, `tests/test_score_jobs.py`.
- `tests/fixtures/jobs_sample.json` — small recorded jobs fixture (no network).

**Modify:**
- `scripts/fetch_jobs.py` — drop `--keywords`, add `--departments`, gate by department, Adzuna `category` facet.
- `scripts/apify_scrape.py` — department-driven actor input + normalize output to the shared schema.
- `SKILL.md`, `README.md` — point at the new flow.

**Remove (with backup):**
- `scripts/ats_scorer.py` → copied to `scripts/_legacy/ats_scorer.py`, then deleted from `scripts/`.
- `scripts/rank_jobs.py` → copied to `scripts/_legacy/rank_jobs.py`, then deleted from `scripts/`.

**Import convention:** scripts are run directly (`python scripts/fetch_jobs.py`). Each entry-point script adds its own dir to `sys.path` then imports the package: `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` followed by `from lib import department, ats`. Tests add `scripts/` to `sys.path` the same way.

---

### Task 1: Scaffold the `lib` package and asset-path helper

**Files:**
- Create: `scripts/lib/__init__.py`
- Create: `scripts/lib/paths.py`
- Create: `tests/__init__.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Create the empty package markers**

```bash
mkdir -p scripts/lib tests tests/fixtures
: > scripts/lib/__init__.py
: > tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/test_paths.py`:
```python
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from lib import paths  # noqa: E402


class TestPaths(unittest.TestCase):
    def test_repo_root_contains_assets(self):
        self.assertTrue(os.path.isdir(os.path.join(paths.REPO_ROOT, "assets")))

    def test_asset_joins_under_assets(self):
        p = paths.asset("departments.json")
        self.assertEqual(os.path.basename(p), "departments.json")
        self.assertTrue(p.startswith(paths.REPO_ROOT))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m unittest tests.test_paths -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.paths'`.

- [ ] **Step 4: Write the implementation**

`scripts/lib/paths.py`:
```python
"""Locate bundled assets relative to the repo root.

lib/paths.py lives at <repo>/scripts/lib/paths.py, so the repo root is three
directories up. All bundled data (departments.json, skills_dictionary.json)
lives under <repo>/assets/.
"""
import os

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")


def asset(name):
    """Absolute path to a bundled asset file under assets/."""
    return os.path.join(ASSETS_DIR, name)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest tests.test_paths -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/__init__.py scripts/lib/paths.py tests/__init__.py tests/test_paths.py
git commit -m "feat: add lib package scaffold and asset-path helper"
```

---

### Task 2: Department taxonomy asset

**Files:**
- Create: `assets/departments.json`
- Test: `tests/test_department.py` (asset-shape test only in this task)

- [ ] **Step 1: Write the failing test**

`tests/test_department.py`:
```python
import json, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


class TestTaxonomyAsset(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "assets", "departments.json")) as f:
            self.tax = json.load(f)

    def test_default_on_buckets(self):
        on = {k for k, v in self.tax.items()
              if isinstance(v, dict) and v.get("default_on")}
        self.assertEqual(on, {"software", "engineering", "technology"})

    def test_every_dept_has_matchers_and_facets(self):
        for k, v in self.tax.items():
            if k.startswith("_"):
                continue
            self.assertTrue(v.get("title_match"), f"{k} has no title_match")
            self.assertIn("facets", v, f"{k} has no facets")

    def test_has_global_deny_list(self):
        self.assertIn("_deny", self.tax)
        self.assertIn("sales engineer", self.tax["_deny"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_department -v`
Expected: FAIL — `FileNotFoundError: assets/departments.json`.

- [ ] **Step 3: Create the asset**

`assets/departments.json`:
```json
{
  "software": {
    "default_on": true,
    "title_match": ["software engineer", "software developer", "backend", "back-end", "frontend", "front-end", "full stack", "full-stack", "sde", "swe", "developer", "programmer", "software development engineer"],
    "facets": {"linkedin": ["eng"], "adzuna": ["it-jobs"]}
  },
  "engineering": {
    "default_on": true,
    "title_match": ["engineer", "engineering", "platform engineer", "systems engineer", "embedded", "firmware", "mobile engineer", "android engineer", "ios engineer"],
    "facets": {"linkedin": ["eng"], "adzuna": ["it-jobs"]}
  },
  "technology": {
    "default_on": true,
    "title_match": ["information technology", "technology", "cloud engineer", "infrastructure engineer", "it specialist", "technical lead", "tech lead"],
    "facets": {"linkedin": ["it"], "adzuna": ["it-jobs"]}
  },
  "data": {
    "default_on": false,
    "title_match": ["data engineer", "data scientist", "machine learning", "ml engineer", "ai engineer", "analytics engineer", "data analyst"],
    "facets": {"linkedin": ["eng", "anls"], "adzuna": ["it-jobs"]}
  },
  "devops": {
    "default_on": false,
    "title_match": ["devops", "sre", "site reliability", "platform engineer", "infrastructure engineer", "cloud engineer"],
    "facets": {"linkedin": ["eng", "it"], "adzuna": ["it-jobs"]}
  },
  "security": {
    "default_on": false,
    "title_match": ["security engineer", "appsec", "application security", "infosec", "security analyst", "cybersecurity"],
    "facets": {"linkedin": ["eng", "it"], "adzuna": ["it-jobs"]}
  },
  "qa": {
    "default_on": false,
    "title_match": ["qa engineer", "quality assurance", "sdet", "test engineer", "test automation", "automation engineer"],
    "facets": {"linkedin": ["qa"], "adzuna": ["it-jobs"]}
  },
  "_deny": ["sales engineer", "solutions engineer", "customer engineer", "pre-sales", "presales", "sales development", "account executive", "recruiter", "talent acquisition"]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_department -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add assets/departments.json tests/test_department.py
git commit -m "feat: add department taxonomy asset"
```

---

### Task 3: `department.py` — classify, matches, defaults, facets

**Files:**
- Create: `scripts/lib/department.py`
- Test: `tests/test_department.py` (extend with behavior tests)

- [ ] **Step 1: Add the failing behavior tests**

Append to `tests/test_department.py` (inside the file, new class):
```python
from lib import department  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_software_title_hits_software_and_engineering(self):
        depts = department.classify("Senior Backend Engineer", ["python"])
        self.assertIn("software", depts)
        self.assertIn("engineering", depts)

    def test_sales_engineer_is_denied(self):
        self.assertEqual(department.classify("Sales Engineer", []), set())

    def test_data_scientist_only_when_no_match_for_data_off(self):
        depts = department.classify("Data Scientist", ["ml"])
        self.assertIn("data", depts)

    def test_non_tech_title_empty(self):
        self.assertEqual(department.classify("Marketing Manager", []), set())

    def test_default_departments(self):
        self.assertEqual(set(department.default_departments()),
                         {"software", "engineering", "technology"})

    def test_matches_respects_selection(self):
        job = {"title": "Data Engineer", "tags": []}
        ok_default, depts = department.matches(job, ["software", "engineering", "technology"])
        ok_data, _ = department.matches(job, ["data"])
        self.assertFalse(ok_default)
        self.assertTrue(ok_data)

    def test_facet_codes_union(self):
        codes = department.facet_codes(["software", "technology"], "linkedin")
        self.assertEqual(set(codes), {"eng", "it"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_department -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.department'`.

- [ ] **Step 3: Implement `department.py`**

`scripts/lib/department.py`:
```python
"""Department taxonomy: classify a job into engineering-family departments and
map departments to per-source native search facets.

The taxonomy lives in assets/departments.json so it is tunable without code
changes. Keys starting with "_" are control entries (e.g. "_deny"), not
departments.
"""
import json
import re

from lib import paths

_TAXONOMY = None


def load_taxonomy(path=None):
    """Load (and cache) the taxonomy dict from assets/departments.json."""
    global _TAXONOMY
    if path is None and _TAXONOMY is not None:
        return _TAXONOMY
    with open(path or paths.asset("departments.json")) as f:
        tax = json.load(f)
    if path is None:
        _TAXONOMY = tax
    return tax


def _departments(tax):
    return {k: v for k, v in tax.items() if not k.startswith("_")}


def default_departments(tax=None):
    tax = tax or load_taxonomy()
    return [k for k, v in _departments(tax).items() if v.get("default_on")]


def _hay(title, tags):
    return (title or "").lower() + " " + " ".join(tags or []).lower()


def _word_hit(needle, hay):
    # Match whole tokens/phrases so "qa" doesn't fire inside "quality".
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                     hay) is not None


def classify(title, tags=None, tax=None):
    """Return the set of department keys whose matchers hit title/tags.

    A global "_deny" list short-circuits the whole job (e.g. "sales engineer").
    """
    tax = tax or load_taxonomy()
    hay = _hay(title, tags)
    for bad in tax.get("_deny", []):
        if _word_hit(bad, hay):
            return set()
    hits = set()
    for dept, cfg in _departments(tax).items():
        if any(_word_hit(m, hay) for m in cfg.get("title_match", [])):
            hits.add(dept)
    return hits


def matches(job, selected, tax=None):
    """(kept?, assigned_departments) for a job against the selected set."""
    depts = classify(job.get("title", ""), job.get("tags"), tax)
    return bool(depts & set(selected)), depts


def facet_codes(selected, source, tax=None):
    """Sorted union of native facet codes for `source` across selected depts."""
    tax = tax or load_taxonomy()
    deps = _departments(tax)
    codes = set()
    for d in selected:
        codes |= set(deps.get(d, {}).get("facets", {}).get(source, []))
    return sorted(codes)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_department -v`
Expected: PASS (all classify + asset tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/department.py tests/test_department.py
git commit -m "feat: add department classifier and facet mapping"
```

---

### Task 4: Skills dictionary asset + `extract_jd_skills`

**Files:**
- Create: `assets/skills_dictionary.json`
- Create: `scripts/lib/ats.py` (dictionary + extraction only in this task)
- Test: `tests/test_ats.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ats.py`:
```python
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from lib import ats  # noqa: E402


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.idx = ats.build_alias_index(ats.load_dictionary())

    def test_canonicalizes_alias(self):
        found = ats.extract_jd_skills("We use k8s and Node.js in prod", self.idx)
        self.assertIn("kubernetes", found)
        self.assertIn("node.js", found)

    def test_word_boundary_no_false_positive(self):
        # "java" must not fire on "javascript"
        found = ats.extract_jd_skills("Strong JavaScript skills", self.idx)
        self.assertIn("javascript", found)
        self.assertNotIn("java", found)

    def test_empty_text(self):
        self.assertEqual(ats.extract_jd_skills("", self.idx), set())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_ats -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.ats'`.

- [ ] **Step 3: Create the dictionary asset**

`assets/skills_dictionary.json` (canonical → aliases; extend freely later):
```json
{
  "python": ["py"],
  "java": [],
  "javascript": ["js"],
  "typescript": ["ts"],
  "go": ["golang"],
  "rust": [],
  "c++": ["cpp"],
  "c#": ["csharp", ".net", "dotnet"],
  "ruby": [],
  "php": [],
  "scala": [],
  "kotlin": [],
  "swift": [],
  "haskell": [],
  "elixir": [],
  "node.js": ["node", "nodejs"],
  "react": ["react.js", "reactjs"],
  "react native": [],
  "angular": ["angular.js", "angularjs"],
  "vue": ["vue.js", "vuejs"],
  "next.js": ["nextjs"],
  "django": [],
  "flask": [],
  "fastapi": [],
  "spring boot": ["spring"],
  "express": ["express.js"],
  "rails": ["ruby on rails"],
  "graphql": [],
  "grpc": [],
  "rest": ["rest api", "restful"],
  "postgresql": ["postgres"],
  "mysql": [],
  "mongodb": ["mongo"],
  "redis": [],
  "dynamodb": [],
  "cassandra": [],
  "elasticsearch": ["elastic search"],
  "kafka": [],
  "rabbitmq": [],
  "snowflake": [],
  "kubernetes": ["k8s"],
  "docker": [],
  "terraform": [],
  "ansible": [],
  "aws": ["amazon web services"],
  "gcp": ["google cloud"],
  "azure": [],
  "ci/cd": ["cicd", "continuous integration"],
  "microservices": ["micro-services"],
  "distributed systems": [],
  "sql": [],
  "nosql": [],
  "machine learning": ["ml"],
  "deep learning": [],
  "pytorch": [],
  "tensorflow": [],
  "pandas": [],
  "spark": ["apache spark"],
  "airflow": [],
  "hadoop": [],
  "linux": [],
  "git": []
}
```

- [ ] **Step 4: Implement the extraction half of `ats.py`**

`scripts/lib/ats.py` (this task adds the top section; later tasks append):
```python
"""Unified local ATS scorer + company-tier tiebreaker.

ATS% = |JD-required skills the candidate HAS| / |JD-required skills|, where
JD-required skills are master-dictionary terms found in the JD text. This is
source-agnostic: it needs only the JD text, which every source provides.
"""
import json
import re

from lib import paths

_DICT = None


def load_dictionary(path=None):
    """Load (and cache) the canonical->aliases skill dictionary."""
    global _DICT
    if path is None and _DICT is not None:
        return _DICT
    with open(path or paths.asset("skills_dictionary.json")) as f:
        data = json.load(f)
    if path is None:
        _DICT = data
    return data


def build_alias_index(dictionary):
    """Map every surface form (canonical + aliases) -> canonical skill."""
    idx = {}
    for canonical, aliases in dictionary.items():
        idx[canonical.lower()] = canonical.lower()
        for a in aliases:
            idx[a.lower()] = canonical.lower()
    return idx


def _present(term, hay):
    # Whole-token match; allows internal . + # (node.js, c#, ci/cd).
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9+#.])",
                     hay) is not None


def extract_jd_skills(text, alias_index):
    """Return the set of canonical skills mentioned in `text`."""
    hay = (text or "").lower()
    found = set()
    # Longest surface forms first so "spring boot" wins over "spring".
    for term in sorted(alias_index, key=len, reverse=True):
        if _present(term, hay):
            found.add(alias_index[term])
    return found
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m unittest tests.test_ats -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add assets/skills_dictionary.json scripts/lib/ats.py tests/test_ats.py
git commit -m "feat: add master skill dictionary and JD skill extraction"
```

---

### Task 5: `score_job` (ATS math + low-signal flag)

**Files:**
- Modify: `scripts/lib/ats.py` (append `score_job`)
- Test: `tests/test_ats.py` (append `TestScore`)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_ats.py`:
```python
class TestScore(unittest.TestCase):
    def setUp(self):
        self.idx = ats.build_alias_index(ats.load_dictionary())
        self.have = ["python", "kafka", "postgres", "aws"]

    def test_partial_match_pct(self):
        job = {"title": "Backend Engineer",
               "tags": ["python", "kafka"],
               "description": "Python, Kafka, Terraform, Snowflake"}
        r = ats.score_job(job, self.have, self.idx)
        # JD = {python, kafka, terraform, snowflake}; have 2 of 4 -> 50%
        self.assertEqual(r["ats_pct"], 50)
        self.assertEqual(r["have_count"], 2)
        self.assertEqual(set(r["gaps"]), {"terraform", "snowflake"})
        self.assertFalse(r["low_signal"])

    def test_low_signal_when_few_jd_skills(self):
        job = {"title": "Engineer", "tags": [], "description": "We use Python."}
        r = ats.score_job(job, self.have, self.idx)
        self.assertTrue(r["low_signal"])
        self.assertEqual(r["ats_pct"], 100)

    def test_empty_jd_scores_zero(self):
        job = {"title": "Engineer", "tags": [], "description": "Great culture."}
        r = ats.score_job(job, self.have, self.idx)
        self.assertEqual(r["ats_pct"], 0)
        self.assertTrue(r["low_signal"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_ats.TestScore -v`
Expected: FAIL — `AttributeError: module 'lib.ats' has no attribute 'score_job'`.

- [ ] **Step 3: Append `score_job` to `ats.py`**

```python
LOW_SIGNAL_MIN = 3  # JD must mention >= this many skills to be high-signal


def score_job(job, have_skills, alias_index):
    """Score one normalized job against the candidate's HAVE skills.

    Returns a dict with ats_pct, matches/gaps lists, counts, low_signal.
    """
    text = " ".join([
        job.get("title", ""),
        " ".join(job.get("tags", []) or []),
        job.get("description", "") or "",
    ])
    jd = extract_jd_skills(text, alias_index)
    have = {alias_index.get(s.lower(), s.lower()) for s in (have_skills or [])}
    matches = jd & have
    gaps = jd - have
    pct = round(len(matches) / len(jd) * 100) if jd else 0
    return {
        "ats_pct": pct,
        "matches": sorted(matches),
        "gaps": sorted(gaps),
        "jd_count": len(jd),
        "have_count": len(matches),
        "gap_count": len(gaps),
        "low_signal": len(jd) < LOW_SIGNAL_MIN,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_ats -v`
Expected: PASS (all extraction + score tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/ats.py tests/test_ats.py
git commit -m "feat: add unified ATS score_job with low-signal flag"
```

---

### Task 6: Move company tiers into `ats.py`

**Files:**
- Modify: `scripts/lib/ats.py` (append tier logic, copied verbatim from `ats_scorer.py`)
- Test: `tests/test_ats.py` (append `TestTier`)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_ats.py`:
```python
class TestTier(unittest.TestCase):
    def test_t1(self):
        self.assertEqual(ats.company_tier("Google India")[0], "T1")

    def test_t2(self):
        self.assertEqual(ats.company_tier("Razorpay")[0], "T2")

    def test_known_large_is_neutral_not_redflag(self):
        self.assertEqual(ats.company_tier("Tata Consultancy Services")[0],
                         "neutral")

    def test_redflag_by_pattern(self):
        self.assertEqual(ats.company_tier("ABC Staffing Solutions")[0],
                         "redflag")

    def test_unknown_neutral(self):
        self.assertEqual(ats.company_tier("Quaxon Labs")[0], "neutral")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_ats.TestTier -v`
Expected: FAIL — `AttributeError: module 'lib.ats' has no attribute 'company_tier'`.

- [ ] **Step 3: Copy the tier block into `ats.py`**

Copy these symbols **verbatim** from `scripts/ats_scorer.py` (lines ~86–182) and append to `scripts/lib/ats.py`: `TIER1_NAMES`, `TIER2_NAMES`, `KNOWN_LARGE_NAMES`, `RED_FLAG_NAMES`, `RED_FLAG_PATTERNS`, `RED_FLAG_SECTORS`, `TIER_RANK`, `TIER_GLYPH`, `_hit`, and `company_tier`. Do not change their logic. (The block is reproduced in `scripts/ats_scorer.py`; read it there to copy exactly so the curated lists stay in sync.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_ats -v`
Expected: PASS (extraction + score + tier tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/ats.py tests/test_ats.py
git commit -m "feat: move company-tier logic into lib.ats"
```

---

### Task 7: `score_jobs.py` — load, normalize, dedup, score, rank, report

**Files:**
- Create: `scripts/score_jobs.py`
- Create: `tests/fixtures/jobs_sample.json`
- Test: `tests/test_score_jobs.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/jobs_sample.json`:
```json
[
  {"title": "Senior Backend Engineer", "company": "Razorpay",
   "location": "Bengaluru", "remote": false, "visa_sponsorship": null,
   "tags": ["python", "kafka"], "salary": "30,00,000",
   "description": "Python, Kafka, PostgreSQL, AWS, Terraform.",
   "url": "https://x/1", "posted": "2026-05-28", "source": "adzuna"},
  {"title": "Senior Backend Engineer", "company": "Razorpay",
   "location": "Bengaluru", "remote": false, "visa_sponsorship": null,
   "tags": ["python", "kafka"], "salary": null,
   "description": "Python, Kafka, PostgreSQL, AWS, Terraform.",
   "url": "https://x/dup", "posted": "2026-05-28", "source": "linkedin"},
  {"title": "Platform Engineer", "company": "Quaxon Staffing Solutions",
   "location": "Remote", "remote": true, "visa_sponsorship": null,
   "tags": ["go"], "salary": null,
   "description": "Go, Kubernetes, Docker, GCP.",
   "url": "https://x/2", "posted": "2026-05-20", "source": "remoteok"},
  {"title": "Engineer", "company": "Tiny Co",
   "location": "Remote", "remote": true, "visa_sponsorship": null,
   "tags": [], "salary": null, "description": "Great culture, free lunch.",
   "url": "https://x/3", "posted": "2026-05-01", "source": "remotive"}
]
```

- [ ] **Step 2: Write the failing test**

`tests/test_score_jobs.py`:
```python
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "score_jobs.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "jobs_sample.json")


class TestScoreJobsCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.profile = os.path.join(self.tmp, "profile.json")
        with open(self.profile, "w") as f:
            json.dump({"name": "T", "skills": ["python", "kafka",
                       "postgresql", "aws", "go", "kubernetes"]}, f)

    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, SCRIPT, FIXTURE, "--profile", self.profile,
             "--out-dir", self.tmp, *extra],
            capture_output=True, text=True)

    def test_dedup_and_report_written(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "jobs_ranked.csv")) as f:
            rows = f.read().splitlines()
        # 4 input rows, one (title,company) dup removed -> 3 data rows + header
        self.assertEqual(len(rows), 4)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "report.md")))

    def test_low_signal_sorts_last(self):
        self.run_cli()
        with open(os.path.join(self.tmp, "jobs_ranked.csv")) as f:
            body = f.read().splitlines()[1:]
        titles = [line.split(",")[6] for line in body]  # col 6 = title
        self.assertEqual(titles[-1].strip('"'), "Engineer")  # the low-signal one
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m unittest tests.test_score_jobs -v`
Expected: FAIL — `score_jobs.py` does not exist (non-zero return / FileNotFound).

- [ ] **Step 4: Implement `score_jobs.py`**

`scripts/score_jobs.py`:
```python
#!/usr/bin/env python3
"""score_jobs.py — unified scorer. Loads one or more normalized job JSON files,
merges + dedups on (title, company), scores each via the master-dictionary ATS,
orders by ATS% then company tier then have-count then recency, and writes a
Markdown report + CSV. Replaces the old ats_scorer.py and rank_jobs.py.

Usage:
  python scripts/score_jobs.py data/jobs.json [data/apify_jobs.json] \
      --profile data/profile.json --top 50 --out-dir data/output
"""
import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ats  # noqa: E402

DEFAULT_OUT_DIR = os.path.join("data", "output")


def load_have_skills(profile_path):
    with open(profile_path) as f:
        prof = json.load(f)

    def norm(items):
        return [str(s).lower().strip() for s in (items or []) if str(s).strip()]

    have = set(norm(prof.get("skills")))
    for exp in (prof.get("experience") or []):
        have |= set(norm(exp.get("skills")))
    for proj in (prof.get("projects") or []):
        have |= set(norm(proj.get("skills")))
    return prof, sorted(have)


def load_jobs(paths):
    jobs = []
    for p in paths:
        with open(p) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key in ("items", "data", "results", "jobs"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                raw = [raw]
        jobs += [j for j in raw if isinstance(j, dict)]
    return jobs


def dedup(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (str(j.get("title", "")).lower(),
               str(j.get("company", "")).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def age_days(posted, today):
    try:
        y, m, d = map(int, str(posted)[:10].split("-"))
        return (today - date(y, m, d)).days
    except Exception:
        return 999


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jobs", nargs="+", help="one or more normalized job JSON files")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    prof, have = load_have_skills(args.profile)
    idx = ats.build_alias_index(ats.load_dictionary())

    jobs = dedup(load_jobs(args.jobs))
    rows = []
    for j in jobs:
        s = ats.score_job(j, have, idx)
        tier_label, tier_rank = ats.company_tier(
            j.get("company", ""), j.get("sector", ""))
        rows.append({**j, **s, "tier": tier_label, "tier_rank": tier_rank,
                     "age_days": age_days(j.get("posted"), today)})

    # Non-low-signal first; then ATS% desc, tier desc, have desc, newest first.
    rows.sort(key=lambda r: (0 if r["low_signal"] else 1, r["ats_pct"],
                             r["tier_rank"], r["have_count"], -r["age_days"]),
              reverse=True)
    rows = rows[:args.top]

    os.makedirs(args.out_dir, exist_ok=True)
    write_md(rows, prof, os.path.join(args.out_dir, "report.md"), len(jobs))
    write_csv(rows, os.path.join(args.out_dir, "jobs_ranked.csv"))
    print(f"scored {len(jobs)} jobs -> {args.out_dir}/report.md, jobs_ranked.csv")
    if rows:
        t = rows[0]
        print(f"top: {t['title']} @ {t['company']} "
              f"({t['ats_pct']}%, {t['tier']})")


def write_md(rows, prof, path, total):
    L = ["# ATS-ranked job report", ""]
    L.append(f"_Profile: {prof.get('name', 'candidate')} — "
             f"{total} jobs scored, showing {len(rows)}._")
    L.append("")
    L.append("| # | ATS % | Tier | Dept | Title | Company | Location | "
             "Remote | Visa | Gaps | Age | Link |")
    L.append("|--:|--:|:--:|---|---|---|---|:-:|:-:|---|--:|---|")
    for i, r in enumerate(rows, 1):
        rem = "✓" if r.get("remote") else ""
        visa = {True: "✓", False: "✗"}.get(r.get("visa_sponsorship"), "?")
        dept = ",".join(sorted(r.get("departments", []))) or "-"
        gaps = ", ".join(r["gaps"][:4]) or "none ✅"
        flag = " ⚠️" if r["low_signal"] else ""
        link = f"[apply]({r['url']})" if r.get("url") else ""
        L.append(f"| {i} | {r['ats_pct']}%{flag} | {r['tier']} | {dept} | "
                 f"{str(r['title'])[:42]} | {str(r['company'])[:20]} | "
                 f"{str(r.get('location',''))[:18]} | {rem} | {visa} | "
                 f"{gaps} | {r['age_days']}d | {link} |")
    L.append("\n_⚠️ = low-signal JD (fewer than 3 detected skills); ranked "
             "below high-signal roles._")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def write_csv(rows, path):
    cols = ["rank", "ats_pct", "low_signal", "tier", "have_count", "gap_count",
            "title", "company", "location", "remote", "visa_sponsorship",
            "posted", "age_days", "matches", "gaps", "url"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["ats_pct"], int(r["low_signal"]), r["tier"],
                        r["have_count"], r["gap_count"], r["title"],
                        r["company"], r.get("location", ""), r.get("remote"),
                        r.get("visa_sponsorship"), r.get("posted", ""),
                        r["age_days"], "; ".join(r["matches"]),
                        "; ".join(r["gaps"]), r.get("url", "")])


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m unittest tests.test_score_jobs -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/score_jobs.py tests/test_score_jobs.py tests/fixtures/jobs_sample.json
git commit -m "feat: add unified score_jobs CLI replacing the two old scorers"
```

---

### Task 8: Refactor `fetch_jobs.py` to department-driven

**Files:**
- Modify: `scripts/fetch_jobs.py`
- Test: `tests/test_fetch_jobs.py`

- [ ] **Step 1: Write the failing test (filter logic only, no network)**

`tests/test_fetch_jobs.py`:
```python
import importlib, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
fj = importlib.import_module("fetch_jobs")


class TestDeptGate(unittest.TestCase):
    def test_keeps_engineering_drops_marketing(self):
        jobs = [
            {"title": "Backend Engineer", "company": "A", "tags": ["python"],
             "location": "India", "remote": False, "description": "",
             "posted": None, "visa_sponsorship": None},
            {"title": "Marketing Manager", "company": "B", "tags": [],
             "location": "India", "remote": False, "description": "",
             "posted": None, "visa_sponsorship": None},
        ]
        kept = fj.filter_jobs(jobs, departments=["software", "engineering",
                              "technology"], location="", remote=False,
                              visa=False, since_days=0)
        titles = [j["title"] for j in kept]
        self.assertIn("Backend Engineer", titles)
        self.assertNotIn("Marketing Manager", titles)

    def test_assigns_departments_field(self):
        jobs = [{"title": "Data Engineer", "company": "A", "tags": [],
                 "location": "", "remote": True, "description": "",
                 "posted": None, "visa_sponsorship": None}]
        kept = fj.filter_jobs(jobs, departments=["data"], location="",
                              remote=False, visa=False, since_days=0)
        self.assertEqual(kept[0]["departments"], ["data"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_fetch_jobs -v`
Expected: FAIL — `AttributeError: module 'fetch_jobs' has no attribute 'filter_jobs'`.

- [ ] **Step 3: Edit `fetch_jobs.py` — add imports and a `filter_jobs` function**

At the top of `scripts/fetch_jobs.py`, after the existing stdlib imports, add:
```python
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lib import department  # noqa: E402
```

Replace the keyword matcher `_matches_kw` (lines ~293–298) with a department-aware filter. Add this function near the other filter helpers:
```python
def filter_jobs(jobs, departments, location, remote, visa, since_days):
    """Dedup + gate jobs by department/location/remote/visa/recency."""
    out, seen = [], set()
    for j in jobs:
        key = (j["title"].lower(), j["company"].lower())
        if key in seen:
            continue
        kept, depts = department.matches(j, departments)
        if not kept:
            continue
        if location and not _matches_loc(j, location):
            continue
        if remote and not j.get("remote"):
            continue
        if visa and j.get("visa_sponsorship") is not True:
            continue
        if not _recent(j, since_days):
            continue
        j = dict(j)
        j["departments"] = sorted(depts)
        seen.add(key)
        out.append(j)
    return out
```

- [ ] **Step 4: Rewire `main()` and Adzuna for departments**

In `main()`:
- Remove the `--keywords` argument. Add:
  ```python
  ap.add_argument("--departments", default=",".join(department.default_departments()),
                  help="comma list from the taxonomy; default = software,engineering,technology")
  ```
- Replace `kw = [...]` with:
  ```python
  depts = [d.strip() for d in args.departments.split(",") if d.strip()]
  ```
- Change source-adapter calls so they no longer receive keywords. Update each `src_*` signature to drop the `kw` parameter (they currently use it only to build a query; without it they fetch broad). For `src_remotive`/`src_jobicy`, fetch the general feed (no `search=`/`tag=`). For `src_adzuna`, replace the `what=` query with category facets:
  ```python
  cats = department.facet_codes(depts, "adzuna")  # e.g. ["it-jobs"]
  category = ("&category=" + cats[0]) if cats else ""
  url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
         f"?app_id={app_id}&app_key={app_key}"
         f"&results_per_page=50{category}&content-type=application/json")
  ```
- Replace the inline filter loop (lines ~371–388) with:
  ```python
  filtered = filter_jobs(jobs, depts, args.location, args.remote,
                         args.visa, args.since_days)
  ```
- Update the example in the module docstring to use `--departments` instead of `--keywords`.

- [ ] **Step 5: Run unit + a live smoke check**

Run: `python -m unittest tests.test_fetch_jobs -v`
Expected: PASS (2 tests).

Run (network; remote boards are keyless): `python scripts/fetch_jobs.py --since-days 30 --sources remoteok --out /tmp/j.json`
Expected: stderr shows `-> remoteok` and a final `N jobs (from M raw) -> /tmp/j.json` line; `/tmp/j.json` is a JSON array of engineering roles, each with a `departments` field. (If the environment has no network, note it and rely on the unit test.)

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_jobs.py tests/test_fetch_jobs.py
git commit -m "feat: fetch jobs by department taxonomy instead of keywords"
```

---

### Task 9: Department-driven `apify_scrape.py` + normalized output

**Files:**
- Modify: `scripts/apify_scrape.py`
- Test: `tests/test_apify_scrape.py`

- [ ] **Step 1: Write the failing test (pure functions, no network)**

`tests/test_apify_scrape.py`:
```python
import importlib, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
ap = importlib.import_module("apify_scrape")


class TestApifyHelpers(unittest.TestCase):
    def test_build_input_uses_dept_facets(self):
        argv = ["x", "--departments", "software,technology",
                "--location", "India", "--rows", "25"]
        payload = ap.build_input(argv)
        self.assertEqual(payload["location"], "India")
        self.assertEqual(payload["rows"], 25)
        self.assertIn("eng", payload["jobFunction"])
        self.assertIn("it", payload["jobFunction"])

    def test_normalize_maps_linkedin_fields(self):
        raw = {"jobTitle": "Backend Engineer", "companyName": "Acme",
               "location": "Remote", "jobUrl": "https://x",
               "publishedAt": "2026-05-20", "description": "Python, Kafka"}
        n = ap.normalize(raw)
        self.assertEqual(n["title"], "Backend Engineer")
        self.assertEqual(n["company"], "Acme")
        self.assertEqual(n["url"], "https://x")
        self.assertEqual(n["posted"], "2026-05-20")
        self.assertEqual(n["source"], "apify")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_apify_scrape -v`
Expected: FAIL — `build_input` has no `jobFunction`; `normalize` missing.

- [ ] **Step 3: Edit `apify_scrape.py`**

Add the import block after the existing imports:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import department  # noqa: E402
```

In `build_input`, after computing `rows`, replace the keyword payload with department facets (keep `--input-file` passthrough untouched):
```python
    departments = flag(argv, "--departments",
                       ",".join(department.default_departments()))
    depts = [d.strip() for d in departments.split(",") if d.strip()]
    payload = {
        "location": flag(argv, "--location", ""),
        "rows": rows,
        "maxItems": rows,
        "jobFunction": department.facet_codes(depts, "linkedin"),
    }
    if "--remote" in argv:
        payload["remote"] = True
    return payload
```

Add a `normalize` function (used so the output matches the schema `score_jobs.py` expects):
```python
def normalize(raw):
    """Map an Apify/LinkedIn row to the shared normalized job schema."""
    return {
        "id": f"apify:{raw.get('id') or raw.get('jobUrl') or raw.get('url') or ''}",
        "source": "apify",
        "title": raw.get("jobTitle") or raw.get("title") or "",
        "company": raw.get("companyName") or raw.get("company") or "",
        "location": raw.get("location") or "",
        "remote": bool(raw.get("remote")) if "remote" in raw else None,
        "visa_sponsorship": None,
        "tags": raw.get("tags") or [],
        "salary": raw.get("salary"),
        "description": raw.get("description") or "",
        "url": raw.get("jobUrl") or raw.get("url") or "",
        "posted": (raw.get("publishedAt") or raw.get("published_at") or "")[:10] or None,
        "sector": raw.get("sector", ""),
    }
```

In `main()`, after `items = run_actor(...)` and the list-coercion, normalize before writing:
```python
    items = [normalize(it) if isinstance(it, dict) else it for it in items]
```
Update the closing `print(f"Next: ...")` hint to:
```python
    print(f"Next: python scripts/score_jobs.py {out} data/jobs.json "
          f"--profile data/profile.json")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_apify_scrape -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/apify_scrape.py tests/test_apify_scrape.py
git commit -m "feat: drive apify input by department facets and normalize output"
```

---

### Task 10: Back up and remove the old scorers

**Files:**
- Create: `scripts/_legacy/ats_scorer.py`, `scripts/_legacy/rank_jobs.py`
- Delete: `scripts/ats_scorer.py`, `scripts/rank_jobs.py`

- [ ] **Step 1: Copy to backup, then remove from the main path**

```bash
mkdir -p scripts/_legacy
git mv scripts/ats_scorer.py scripts/_legacy/ats_scorer.py
git mv scripts/rank_jobs.py scripts/_legacy/rank_jobs.py
```

- [ ] **Step 2: Add a README marker in the backup dir**

`scripts/_legacy/README.md`:
```markdown
# Legacy scorers (superseded)

`ats_scorer.py` and `rank_jobs.py` were replaced by `scripts/score_jobs.py`
(backed by `scripts/lib/ats.py`) on 2026-05-30. Kept here as a backup only —
not part of the live flow. See
`docs/superpowers/specs/2026-05-30-department-driven-job-hunt-design.md`.
```

- [ ] **Step 3: Verify nothing live imports them**

Run: `grep -rn "ats_scorer\|rank_jobs" scripts SKILL.md README.md references | grep -v _legacy`
Expected: no matches (the only references are inside `scripts/_legacy/` or this plan).

- [ ] **Step 4: Run the whole test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (all tasks' tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/_legacy/
git commit -m "chore: retire ats_scorer and rank_jobs, keep backups under _legacy"
```

---

### Task 11: Update `SKILL.md` and `README.md`

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: Update the SKILL.md workflow**

In `SKILL.md`, edit the workflow so:
- Step 3 (fetch) uses departments, not keywords:
  ```bash
  python scripts/fetch_jobs.py \
      --departments software,engineering,technology --since-days 30 \
      --adzuna-country in --adzuna-id "$ADZUNA_ID" --adzuna-key "$ADZUNA_KEY" \
      --out data/jobs.json
  ```
  with a note: "Default departments are software,engineering,technology; add data/devops/security/qa to widen. One run sweeps India + remote + visa together."
- Step 6 (rank) is replaced by the unified scorer:
  ```bash
  python scripts/score_jobs.py data/jobs.json data/apify_jobs.json \
      --profile data/profile.json --top 50 --out-dir data/output
  ```
- Remove references to `rank_jobs.py`; point "Reference files" scoring note at `references/scoring.md` (updated next).
- In the Apify step, change the actor-input description from keywords to `--departments` and note output is normalized automatically.

- [ ] **Step 2: Update `references/scoring.md`**

Replace the six-component table with the unified ATS description:
```markdown
# Scoring methodology

`scripts/score_jobs.py` (backed by `scripts/lib/ats.py`) gives every job a 0–100
**ATS match**: the share of skills a JD asks for that the candidate already has.

    ATS% = |JD skills ∩ your skills| / |JD skills|

JD skills are master-dictionary terms (`assets/skills_dictionary.json`) found in
the JD text. Ordering is: ATS% → company tier (T1 big tech > T2 renowned
startups > neutral > ⚠️ likely <100-dev shop) → number of matched skills →
recency. JDs mentioning fewer than 3 skills are flagged low-signal and ranked
below high-signal roles. Departments are filtered at fetch time, not here
(`assets/departments.json`).
```

- [ ] **Step 3: Update `README.md`**

Update the usage/flow section to show `fetch_jobs.py --departments …` then
`score_jobs.py …`, and remove `rank_jobs.py`/`ats_scorer.py` mentions (point at
`score_jobs.py`). Keep the Apify and company-tier sections; note the scorer is
now unified and source-agnostic.

- [ ] **Step 4: Verify docs are consistent**

Run: `grep -rn "keywords\|rank_jobs\|ats_scorer" SKILL.md README.md references | grep -v _legacy`
Expected: no live references to the removed flags/scripts (a historical mention in prose is fine, but commands should not use them).

- [ ] **Step 5: Commit**

```bash
git add SKILL.md README.md references/scoring.md
git commit -m "docs: document department-driven fetch and unified scorer"
```

---

## Self-review notes

- **Spec coverage:** department-only fetch (Tasks 7, 9), taxonomy multi-bucket with the three defaults (Tasks 2–3), unified local master-dictionary ATS (Tasks 4–5), low-signal guard (Task 5), company tiers preserved (Task 6), all-three-buckets merge+dedup (Tasks 7–8), Approach-A shared libs + kept entry points (Tasks 1, 3–9), old scorers absorbed+deleted+backed up (Tasks 6, 10), docs (Task 11). All spec sections map to a task.
- **Assets vs code:** taxonomy and dictionary live in `assets/*.json` so they are tunable without code edits, per the spec.
- **Determinism:** `score_jobs.py` reads "today" from the system clock for age, but the CLI tests assert ordering/dedup/structure (not absolute ages), so they stay stable over time.
- **No new runtime deps:** everything is stdlib; tests use `unittest`.
```
