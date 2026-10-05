"""Specs for the hourly LinkedIn -> website pipeline (scripts/live/)."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from live import linkedin, roles, salary, salary_lookup as sl, store, yoe  # noqa: E402
from live.run import apply_salaries, detail_reason, due, role_reason, search_window_hours  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class TestYoe(unittest.TestCase):
    CASES = [
        ("We need 1-3 years of experience in Java", 1),
        ("0–2 years of experience", 0),
        ("1-3+ years experience", 1),
        ("2+ years of backend experience", 2),
        ("Minimum 3 years required", 3),
        ("at least two years of relevant industry experience", 2),
        ("5+ years overall, 2+ years in Go", 5),  # headline bar wins
        ("Experience: 2-4 years", 2),
        ("five or more years of experience", 5),
        ("Exp - 1 yr", 1),
        ("4 years of professional software development experience", 4),
        ("Freshers can apply", 0),
        ("6 months of hands-on experience", 0),
        ("Our company has 25 years of history", None),
        ("Great culture, competitive pay", None),
    ]

    def test_description_cases(self):
        for text, want in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(yoe.parse_yoe(text), want)

    def test_title_fallback_only_when_jd_silent(self):
        self.assertEqual(yoe.parse_yoe("", "SDE 1"), 0)
        self.assertEqual(yoe.parse_yoe("", "Junior Developer"), 0)
        self.assertIsNone(yoe.parse_yoe("", "SDE II"))
        self.assertIsNone(yoe.parse_yoe("", "Software Engineer"))
        self.assertEqual(yoe.parse_yoe("3+ years of experience", "Junior Developer"), 3)
        # a requirement stated only in the title still counts
        self.assertEqual(yoe.parse_yoe("Build AI agents.", "AI Engineer || 7+ Yrs || Pan India"), 7)
        self.assertEqual(yoe.parse_yoe("", "Backend Developer (2-4 years)"), 2)

    def test_classify(self):
        self.assertEqual(yoe.classify(None), "not_stated")
        self.assertEqual(yoe.classify(2), "eligible")
        self.assertEqual(yoe.classify(3), "too_senior")


class TestSalary(unittest.TestCase):
    CASES = [
        ("CTC: ₹12-18 LPA", (12, 18)),
        ("Salary 8 to 12 lakhs per annum", (8, 12)),
        ("package up to 15 lakhs", (15, 15)),
        ("₹1,200,000.00/yr - ₹1,800,000.00/yr", (12, 18)),
        ("₹50,000 - ₹80,000 per month", (6, 9.6)),
        ("INR 10,00,000 - 15,00,000", (10, 15)),
        ("Budget: 25 LPA", (25, 25)),
        ("₹80K/month", (9.6, 9.6)),
        ("Rs. 6 lpa", (6, 6)),
        ("12L - 18L", (12, 18)),
        ("1.2 Cr CTC", (120, 120)),
        ("We serve 10 lakh users daily", None),  # lakh without pay context
        ("$120,000/yr", None),                    # non-INR ignored
        ("Great perks", None),
    ]

    def test_parse(self):
        for text, want in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(salary.parse_salary(text), want)

    def test_bucket_by_midpoint(self):
        self.assertEqual(salary.bucket(5, 9), "0-10")
        self.assertEqual(salary.bucket(8, 12), "10-20")
        self.assertEqual(salary.bucket(15, 30), "20+")
        self.assertEqual(salary.bucket(20, 20), "20+")

def _job(jid, title="Software Engineer", company="Acme", loc="Pune, Maharashtra, India",
         hours_ago=1):
    return {"id": jid, "title": title, "company": company, "location": loc,
            "posted_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


class TestStore(unittest.TestCase):
    def test_dedup_by_id_and_repost(self):
        st = store.empty_state()
        idx = store.known(st)
        self.assertTrue(store.add(st, _job("1"), idx))
        self.assertFalse(store.add(st, _job("1"), idx))                  # same ID
        self.assertFalse(store.add(st, _job("2", title="software  engineer"), idx))  # repost
        self.assertTrue(store.add(st, _job("3", loc="Hyderabad, India"), idx))      # other city
        self.assertEqual([j["id"] for j in st["jobs"]], ["1", "3"])

    def test_skipped_ids_count_as_known(self):
        st = store.empty_state()
        st["skipped"]["9"] = NOW.isoformat()
        self.assertFalse(store.add(st, _job("9")))

    def test_expire_after_24h(self):
        st = store.empty_state()
        for jid, h in (("new", 1), ("edge", 23.9), ("old", 25)):
            store.add(st, _job(jid, company=jid, hours_ago=h))
        st["skipped"] = {"s_old": (NOW - timedelta(hours=30)).isoformat(),
                         "s_new": (NOW - timedelta(hours=2)).isoformat()}
        self.assertEqual(store.expire(st, 24, NOW), 1)
        self.assertEqual([j["id"] for j in st["jobs"]], ["new", "edge"])  # newest first
        self.assertEqual(list(st["skipped"]), ["s_new"])

    def test_window_covers_missed_runs(self):
        cfg = {"window_hours": 3, "max_age_hours": 24}
        ago = lambda h: {"last_scrape_at": (NOW - timedelta(hours=h)).isoformat()}  # noqa: E731
        self.assertEqual(search_window_hours({}, cfg, NOW), 3)           # first run
        self.assertEqual(search_window_hours(ago(1), cfg, NOW), 3)       # on time
        self.assertEqual(search_window_hours(ago(4), cfg, NOW), 5)       # GitHub skipped runs
        self.assertEqual(search_window_hours(ago(40), cfg, NOW), 24)     # capped at max age

    def test_due(self):
        self.assertTrue(due({"last_scrape_at": None}, 1, NOW))
        self.assertFalse(due({"last_scrape_at": (NOW - timedelta(minutes=30)).isoformat()}, 1, NOW))
        self.assertTrue(due({"last_scrape_at": (NOW - timedelta(minutes=57)).isoformat()}, 1, NOW))


SEARCH_HTML = """
<li><div class="base-card relative" data-entity-urn="urn:li:jobPosting:4474285326" data-row="1">
  <img class="artdeco-entity-image" data-delayed-url="https://media.licdn.com/logo?e=1&amp;v=beta">
  <h3 class="base-search-card__title">
        Software Engineer &amp; Builder
  </h3>
  <h4 class="base-search-card__subtitle"><a href="https://in.linkedin.com/company/acme-labs?trk=x">  Acme Labs  </a></h4>
  <span class="job-search-card__location">Bengaluru, Karnataka, India</span>
  <span class="job-search-card__salary-info">₹12,00,000 - ₹18,00,000</span>
  <time class="job-search-card__listdate--new" datetime="2026-10-05">2 hours ago</time>
</div></li>
<li><div class="base-card relative" data-entity-urn="urn:li:jobPosting:4475806826" data-row="2">
  <h3 class="base-search-card__title">SDE 1</h3>
  <h4 class="base-search-card__subtitle">Beta</h4>
  <span class="job-search-card__location">Pune, Maharashtra, India</span>
  <time class="job-search-card__listdate--new" datetime="2026-10-05">7 minutes ago</time>
</div></li>
"""

DETAIL_HTML = """
<span class="num-applicants__caption topcard__flavor--metadata">  58 applicants </span>
<div class="description__text description__text--rich">
 <div class="show-more-less-html__markup relative">
   <p>Build things.</p><ul><li>1-3 years of experience</li></ul>
 </div>
</div>
<li><h3 class="description__job-criteria-subheader">Seniority level</h3>
  <span class="description__job-criteria-text">  Entry level </span></li>
<li><h3 class="description__job-criteria-subheader">Employment type</h3>
  <span class="description__job-criteria-text">Full-time</span></li>
"""


class TestLinkedInParsing(unittest.TestCase):
    def test_search_cards(self):
        cards = linkedin.parse_search(SEARCH_HTML, NOW)
        self.assertEqual([c["id"] for c in cards], ["4474285326", "4475806826"])
        c = cards[0]
        self.assertEqual(c["title"], "Software Engineer & Builder")
        self.assertEqual(c["company"], "Acme Labs")
        self.assertEqual(c["company_slug"], "acme-labs")
        self.assertEqual(cards[1]["company_slug"], "")
        self.assertEqual(c["location"], "Bengaluru, Karnataka, India")
        self.assertEqual(c["posted_at"], "2026-10-05T10:00:00+00:00")
        self.assertEqual(c["logo"], "https://media.licdn.com/logo?e=1&v=beta")
        self.assertEqual(salary.parse_salary(c["salary_text"]), (12, 18))
        self.assertEqual(cards[1]["posted_at"], "2026-10-05T11:53:00+00:00")

    def test_empty_page(self):
        self.assertEqual(linkedin.parse_search("<!DOCTYPE html>"), [])
        self.assertEqual(linkedin.parse_detail(""), {})

    def test_detail(self):
        d = linkedin.parse_detail(DETAIL_HTML)
        self.assertIn("1-3 years of experience", d["description"])
        self.assertEqual(d["seniority"], "Entry level")
        self.assertEqual(d["employment_type"], "Full-time")
        self.assertEqual(d["applicants"], "58 applicants")
        self.assertEqual(yoe.parse_yoe(d["description"]), 1)

    def test_search_url(self):
        url = linkedin.search_url("software engineer", "India", 10800, "2,3", "F", 20)
        self.assertIn("f_TPR=r10800", url)
        self.assertIn("f_E=2%2C3", url)
        self.assertIn("start=20", url)


class TestRoles(unittest.TestCase):
    CASES = [
        ("Software Engineer", "swe", "l1"), ("SDE II", "swe", "l2"),
        ("Software Engineer III", "swe", "l3"), ("ASDE", "swe", "l1"),
        ("Associate Software Developer Engineer", "swe", "l1"),
        ("Member of Technical Staff", "swe", "l1"), ("Backend Engineer", "swe", "l1"),
        ("Software Engineer – Android", "mobile", "l1"),
        ("Software Engineer, Data Platform", "data", "l1"),
        ("Frontend Engineer", "frontend", "l1"), ("Full Stack Developer", "fullstack", "l1"),
        ("QA Automation Engineer", "qa", "l1"), ("DevOps Engineer", "devops", "l1"),
        ("Salesforce Data Cloud Engineer", "erp", "l1"),
        ("SDE Intern", "swe", "intern"), ("Graduate Engineer Trainee", "swe", "intern"),
    ]
    NOT_SOFTWARE = ["Accountant", "Civil Engineer", "Electrical Engineer", "MBBS Doctor",
                    "Business Development Executive", "SAP ABAP Trainer/Faculty",
                    "Product Owner - Payments", "Sales Engineer", "Graphic Designer"]

    def test_families_and_levels(self):
        for title, fam, lvl in self.CASES:
            with self.subTest(title=title):
                self.assertEqual((roles.family(title), roles.level(title)), (fam, lvl))

    def test_non_software_titles(self):
        for title in self.NOT_SOFTWARE:
            self.assertIsNone(roles.family(title), title)

    def test_internships(self):
        for t in ("React Developer Intern | Entry Level | Fresher", "SDE Internship", "Apprentice - IT"):
            self.assertTrue(roles.is_internship(t), t)
        self.assertTrue(roles.is_internship("Software Engineer", "Internship", "Full-time"))
        for t in ("Graduate Engineer Trainee", "Software Engineer", "Internal Tools Engineer"):
            self.assertFalse(roles.is_internship(t), t)

    def test_config_role_and_employment_filters(self):
        cfg = {"exclude_role_families": ["qa", "ml"],
               "exclude_employment_types": ["Part-time", "Volunteer"]}
        self.assertEqual(role_reason("QA Engineer", cfg), "excluded_role")
        self.assertEqual(role_reason("Junior AI/ML Engineer", cfg), "excluded_role")
        self.assertEqual(role_reason("Coding & AI Mentor", cfg), "not_software")
        self.assertEqual(role_reason("Accountant", cfg), "not_software")
        self.assertEqual(role_reason("SDE Intern", cfg), "internship")
        self.assertIsNone(role_reason("Backend Engineer", cfg))
        self.assertIsNone(role_reason("QA Engineer", {}))                     # nothing excluded
        self.assertEqual(detail_reason({"employment_type": "Part-time"}, cfg), "employment_type")
        self.assertEqual(detail_reason({"seniority": "Internship"}, cfg), "internship")
        self.assertIsNone(detail_reason({"employment_type": "Full-time"}, cfg))

    def test_agencies(self):
        self.assertTrue(roles.is_agency("TeamLease Services"))
        self.assertTrue(roles.is_agency("ABC Staffing Solutions"))
        self.assertFalse(roles.is_agency("Razorpay"))


EDGES = (10, 20)
LCFG = {"batch_size": 2, "max_lookups_per_run": 10, "max_lookups_per_day": 240,
        "max_lookups_per_month": 7200, "timeout_sec": 20}


def _sjob(jid, title="Software Engineer", company="Razorpay", slug="razorpay",
          section="eligible", sal=None):
    j = _job(jid, title=title, company=company)
    j.update(company_slug=slug, section=section,
             salary=sal or {"source": "none", "reason": "pending", "bucket": "none"})
    return j


def _found(lo, hi, **kw):
    return {"status": "found", "min_lpa": lo, "max_lpa": hi, "basis": "base",
            "confidence": "medium", "sources": [{"title": "ambitionbox.com"}],
            "expires": (NOW + timedelta(days=30)).isoformat(), **kw}


class TestSalaryResolution(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(sl.job_key(_sjob("1"))[0], "razorpay|swe|l1")
        self.assertEqual(sl.job_key(_sjob("1", title="Frontend Engineer II"))[0], "razorpay|frontend|l2")
        # display-name variants share one key through the LinkedIn slug
        self.assertEqual(sl.job_key(_sjob("1", company="Razorpay Software Pvt Ltd"))[0], "razorpay|swe|l1")
        self.assertEqual(sl.job_key(_sjob("1", title="SDE Intern")), (None, "internship"))
        self.assertEqual(sl.job_key(_sjob("1", title="Accountant")), (None, "non-software title"))
        self.assertEqual(sl.job_key(_sjob("1", company="TeamLease", slug="teamlease")),
                         (None, "staffing agency"))

    def test_resolution_order(self):
        cache = sl.empty_cache()
        cache["entries"]["razorpay|swe|l1"] = _found(14, 22)
        job = _sjob("1")
        self.assertEqual(sl.resolve(job, cache, {}, EDGES)["source"], "web")
        r = sl.resolve(job, cache, {"razorpay|*|*": {"min_lpa": 30, "max_lpa": 40}}, EDGES)
        self.assertEqual((r["source"], r["bucket"]), ("override", "20+"))
        # frontend not looked up yet -> company's SWE range as an approximation
        r = sl.resolve(_sjob("2", title="Frontend Engineer"), cache, {}, EDGES)
        self.assertEqual((r["source"], r["bucket"]), ("approx", "10-20"))
        # nothing known for another company -> pending
        r = sl.resolve(_sjob("3", company="Acme", slug="acme"), cache, {}, EDGES)
        self.assertEqual((r["source"], r["reason"]), ("none", "pending"))
        cache["entries"]["acme|swe|l1"] = {"status": "not_found", "expires": cache["entries"]["razorpay|swe|l1"]["expires"]}
        r = sl.resolve(_sjob("3", company="Acme", slug="acme"), cache, {}, EDGES)
        self.assertEqual(r["reason"], "no public salary data")

    def test_pending_priority_and_skips(self):
        jobs = [_sjob("a", company="Small", slug="small", section="not_stated"),
                _sjob("b", company="Big", slug="big"), _sjob("c", company="Big", slug="big"),
                _sjob("d", company="Mid", slug="mid"),
                _sjob("e", title="SDE Intern"),
                _sjob("f", company="Listed", slug="listed",
                      sal={"source": "listed", "min_lpa": 5, "max_lpa": 7, "bucket": "0-10"})]
        keys = [k for k, _ in sl.pending_keys(jobs, sl.empty_cache(), {})]
        self.assertEqual(keys, ["big|swe|l1", "mid|swe|l1", "small|swe|l1"])

    def test_prune_and_listed_feed_cache(self):
        cache = sl.empty_cache()
        cache["entries"]["old|swe|l1"] = _found(1, 2, expires=(NOW - timedelta(days=1)).isoformat())
        self.assertEqual(sl.prune(cache, NOW), 1)
        sl.record_listed(cache, "acme|swe|l1", 8, 12, NOW, {})
        self.assertEqual(cache["entries"]["acme|swe|l1"]["basis"], "posted")


CLAUDE_ANSWER = [
    {"item": 1, "min_lpa": 14, "max_lpa": 22, "basis": "base", "year": 2026,
     "confidence": "medium", "sources": ["https://www.ambitionbox.com/salaries/razorpay", "not a url"]},
    {"item": 2, "min_lpa": None, "max_lpa": None, "sources": []},
]


def _fake_claude(result, is_error=False, denials=None, exit_code=0):
    """Executable that mimics `claude -p ... --output-format json` and logs its argv."""
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "claude")
    payload = json.dumps({"type": "result", "is_error": is_error, "result": result,
                          "permission_denials": denials or []})
    with open(path, "w") as f:
        f.write("#!/usr/bin/env python3\nimport sys, json\n"
                f"open({os.path.join(d, 'argv.json')!r}, 'w').write(json.dumps(sys.argv))\n"
                f"print({payload!r})\nsys.exit({exit_code})\n")
    os.chmod(path, 0o755)
    return path, os.path.join(d, "argv.json")


class TestClaudeLookup(unittest.TestCase):
    def _items(self):
        return [("razorpay|swe|l1", _sjob("1")), ("acme|swe|l1", _sjob("2", company="Acme", slug="acme"))]

    def test_parse_and_validate(self):
        exe, argv_path = _fake_claude("Here you go:\n```json\n" + json.dumps(CLAUDE_ANSWER) + "\n```")
        out = sl.ask_claude(self._items(), {"claude_bin": exe})
        argv = json.load(open(argv_path))
        # only web tools, pre-approved, nothing else allowed
        self.assertEqual(argv[argv.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "WebSearch,WebFetch")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("--strict-mcp-config", argv)                # no connectors/MCP tools
        r = out["razorpay|swe|l1"]
        self.assertEqual((r["status"], r["min_lpa"], r["max_lpa"], r["basis"]), ("found", 14.0, 22.0, "base"))
        self.assertEqual([x["title"] for x in r["sources"]], ["ambitionbox.com"])  # junk dropped
        self.assertEqual(out["acme|swe|l1"]["status"], "not_found")

    def test_untrusted_sources_mean_low_confidence(self):
        ans = [dict(CLAUDE_ANSWER[0], sources=["https://fita.in/blog/salary"])]
        exe, _ = _fake_claude(json.dumps(ans))
        r = sl.ask_claude(self._items()[:1], {"claude_bin": exe})["razorpay|swe|l1"]
        self.assertEqual((r["status"], r["confidence"]), ("found", "low"))

    def test_answer_without_sources_is_rejected(self):
        ans = [dict(CLAUDE_ANSWER[0], sources=[])]
        exe, _ = _fake_claude(json.dumps(ans))
        self.assertEqual(sl.ask_claude(self._items()[:1], {"claude_bin": exe})["razorpay|swe|l1"]["status"],
                         "not_found")

    def test_error_kinds(self):
        exe, _ = _fake_claude("Claude AI usage limit reached|1791300000", is_error=True)
        with self.assertRaises(sl.QuotaExceeded):
            sl.ask_claude(self._items(), {"claude_bin": exe})
        exe, _ = _fake_claude("Invalid API key · Please run /login", is_error=True, exit_code=1)
        with self.assertRaises(sl.BadRequest):
            sl.ask_claude(self._items(), {"claude_bin": exe})
        exe, _ = _fake_claude("denied", denials=[{"tool_name": "WebSearch"}])
        with self.assertRaises(sl.BadRequest):
            sl.ask_claude(self._items(), {"claude_bin": exe})
        with self.assertRaises(sl.BadRequest):
            sl.ask_claude(self._items(), {"claude_bin": "/nonexistent/claude"})

    def test_run_lookups_budgets(self):
        jobs = [_sjob(str(i), company=f"C{i}", slug=f"c{i}") for i in range(7)]
        cache = sl.empty_cache()
        calls = []

        def ask(items, cfg):
            calls.append(len(items))
            return {k: {"status": "not_found"} for k, _ in items}

        stats = sl.run_lookups(jobs, cache, {}, {**LCFG, "max_lookups_per_run": 4}, NOW, lambda m: None, ask=ask)
        self.assertEqual((calls, stats["lookups"]), ([2, 2], 4))       # per-run cap
        self.assertEqual((cache["meta"]["lookups_today"], cache["meta"]["lookups_month"]), (4, 4))

        def limited(items, cfg):
            raise sl.QuotaExceeded("usage limit")
        stats = sl.run_lookups(jobs, cache, {}, LCFG, NOW, lambda m: None, ask=limited)
        self.assertEqual(stats["lookups"], 0)
        self.assertEqual(cache["meta"]["lookups_today"], 4)          # day not burned

        cache["meta"]["lookups_today"] = 240
        stats = sl.run_lookups(jobs, cache, {}, LCFG, NOW, lambda m: None, ask=ask)
        self.assertEqual(stats["lookups"], 0)                         # daily cap
        stats = sl.run_lookups(jobs, cache, {}, LCFG, NOW + timedelta(days=1), lambda m: None, ask=ask)
        self.assertGreater(stats["lookups"], 0)                       # new day

    def test_deadline_stops_lookups(self):
        import time as _t
        calls = []
        stats = sl.run_lookups([_sjob(str(i), company=f"C{i}", slug=f"c{i}") for i in range(4)],
                               sl.empty_cache(), {}, LCFG, NOW, lambda m: None,
                               ask=lambda items, cfg: calls.append(1) or {},
                               deadline=_t.monotonic() + 5)  # less than one batch timeout left
        self.assertEqual((calls, stats["lookups"]), ([], 0))

    def test_old_cache_meta_format(self):
        # cache written by the Gemini version: same day, but different counter names
        cache = {"meta": {"day": "2026-10-05", "month": "2026-10", "searches_today": 3,
                          "searches_month": 3}, "entries": {}}
        stats = sl.run_lookups([_sjob("1")], cache, {}, LCFG, NOW, lambda m: None,
                               ask=lambda items, cfg: {k: {"status": "not_found"} for k, _ in items})
        self.assertEqual(stats["lookups"], 1)
        self.assertEqual(cache["meta"], {"day": "2026-10-05", "month": "2026-10",
                                         "lookups_today": 1, "lookups_month": 1})

    def test_salary_crash_does_not_block_publishing(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            state = os.path.join(d, "state.json")
            job = _sjob("1")
            job["posted_at"] = datetime.now(timezone.utc).isoformat()  # must not expire
            store.save({**store.empty_state(), "jobs": [job]}, state)
            bad_cache = os.path.join(d, "cache.json")
            os.mkdir(bad_cache)  # a directory where the cache file should be -> save fails
            out = os.path.join(d, "out.json")
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/live/run.py"),
                                "--no-scrape", "--state", state, "--out", out,
                                "--salary-cache", bad_cache], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("salary step failed", r.stderr)
            self.assertEqual(len(json.load(open(out))["jobs"]), 1)

    def test_apply_salaries_end_to_end(self):
        import tempfile
        exe, _ = _fake_claude(json.dumps(CLAUDE_ANSWER))
        st = store.empty_state()
        # Razorpay has more postings, so it is looked up first (item 1 of the fake reply)
        st["jobs"] = [_sjob("1"), _sjob("5", title="Backend Engineer"),
                      _sjob("2", company="Acme", slug="acme"), _sjob("3", title="SDE Intern"),
                      _sjob("4", company="Posted", slug="posted",
                            sal={"source": "listed", "min_lpa": 6, "max_lpa": 9, "bucket": "0-10"})]
        with tempfile.TemporaryDirectory() as d:
            cache_path = os.path.join(d, "c.json")
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "x"
            try:
                apply_salaries(st, {"salary_lookup": {**LCFG, "claude_bin": exe},
                                    "salary_buckets_lpa": [10, 20]},
                               cache_path, os.path.join(d, "none.json"), NOW, lambda m: None)
            finally:
                del os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
            saved = json.load(open(cache_path))
        src = {j["id"]: (j["salary"]["source"], j["salary"]["bucket"]) for j in st["jobs"]}
        self.assertEqual(src, {"1": ("web", "10-20"), "5": ("web", "10-20"), "2": ("none", "none"),
                               "3": ("none", "none"), "4": ("listed", "0-10")})
        self.assertEqual(saved["entries"]["posted|swe|l1"]["basis"], "posted")

if __name__ == "__main__":
    unittest.main()
