"""Specs for the LinkedIn post hunt (scripts/live/posts.py, li_posts.py, posts_ai.py)."""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from live import li_posts, posts, posts_ai, store  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def activity_id(dt):
    """Inverse of li_posts.posted_at: an activity ID created at `dt`."""
    return str(int(dt.timestamp() * 1000) << 22)


def rsc_stream(posts_):
    """A minimal React Server Components stream shaped like LinkedIn's post search.

    posts_: [(activity_id, text, author, headline)]. Each card references its post
    text in a separate row (as LinkedIn does); lines are separated by <br> elements.
    """
    lines, cards = [], []
    for k, (aid, text, author, headline) in enumerate(posts_):
        trow = f"b{k:x}"
        parts = []
        for i, ln in enumerate(text.split("\n")):
            if i:
                parts.append(["$", "br", None, {}])
            parts.append([None, ln])
        lines.append(f"{trow}:" + json.dumps(["$", "$L37", None, {
            "viewTrackingSpecs": {"viewName": "feed-commentary"}, "children": parts}]))
        cards.append(["$", "$L37", None, {
            "componentKey": f"update-card-k{k}", "updateUrn": f"urn:li:activity:{aid}",
            "children": ["$", "div", None, {"children": [["$", "$L37", None, {
                "viewTrackingSpecs": {"viewName": "feed-full-update"},
                "children": ["Feed post", headline, "•",
                             ["$", "$L37", None, {"viewTrackingSpecs": {"viewName": "feed-actor"},
                                                  "children": [author, "• 3rd+"]}],
                             f"$L{trow}"]}]]}]}])
    return "\n".join(['a1:I["$1",[],"default"]',
                      "a0:" + json.dumps(["$", "div", None, {"children": cards}])] + lines)


class TestParsing(unittest.TestCase):
    def test_activity_time_roundtrip(self):
        self.assertEqual(li_posts.posted_at(activity_id(NOW)), NOW)

    def test_parse_cards_from_stream(self):
        a, b = activity_id(NOW - timedelta(hours=1)), activity_id(NOW - timedelta(hours=2))
        got = li_posts.parse_results(rsc_stream([
            (a, "We are hiring an SDE-1 in Pune\nApply: https://x.co/j", "Asha R", "HR at Acme"),
            (b, "Hiring backend engineers, mail cv@acme.in", "Ravi K", "Engineering Manager"),
        ]))
        self.assertEqual([p["id"] for p in got], [a, b])
        self.assertEqual(got[0]["text"], "We are hiring an SDE-1 in Pune\nApply: https://x.co/j")
        self.assertEqual((got[0]["author"], got[0]["headline"]), ("Asha R", "HR at Acme"))
        self.assertEqual(got[1]["posted_at"], (NOW - timedelta(hours=2)).isoformat())
        self.assertEqual(li_posts.parse_results("not a stream"), [])

    def test_real_linkedin_sample_if_present(self):
        path = os.path.join(ROOT, "data", "li_response_0.txt")  # local capture, git-ignored
        if not os.path.exists(path):
            self.skipTest("no captured LinkedIn response")
        got = li_posts.parse_results(open(path).read())
        self.assertGreaterEqual(len(got), 1)
        self.assertTrue(all(p["author"] and p["text"] for p in got))

    def test_search_body(self):
        body = json.loads(li_posts.search_body("hiring sde", 50, "sid"))
        p = body["clientArguments"]["payload"]
        self.assertEqual((p["keywords"], p["startIndex"], p["count"], p["sortBy"]),
                         ("hiring sde", 50, li_posts.PAGE_SIZE, ["date_posted"]))
        self.assertEqual(body["paginationRequest"]["requestedArguments"]["payload"], p)


class FakeSession:
    """Serves pages of posts; page i holds posts aged `pages[i]` hours."""
    def __init__(self, pages):
        self.pages, self.requests, self.blocked_total = pages, 0, 0

    def get(self, url, api=True, data=None):
        start = json.loads(data)["clientArguments"]["payload"]["startIndex"]
        n = start // li_posts.PAGE_SIZE
        self.requests += 1
        page = self.pages[n] if n < len(self.pages) else []
        return rsc_stream([(activity_id(NOW - timedelta(hours=h, seconds=start + i)),
                            f"hiring sde post {start}-{i}", "X", "HR") for i, h in enumerate(page)])


class TestSearchPaging(unittest.TestCase):
    def test_pages_until_two_stale_pages(self):
        since = NOW - timedelta(hours=3)
        # page 2 is out of order (a stale page between fresh ones) — must not stop there
        s = FakeSession([[1, 1], [2, 2], [5, 5], [2.5, 2.5], [6, 6], [7, 7], [1, 1]])
        got, pages, capped = li_posts.search(s, "hiring sde", since)
        self.assertEqual(len(got), 6)          # pages 0, 1, 3 (in window)
        self.assertEqual(pages, 6)             # stopped after pages 4 and 5 were both stale
        self.assertFalse(capped)

    def test_page_cap_reported(self):
        s = FakeSession([[1]] * 10)
        got, pages, capped = li_posts.search(s, "k", NOW - timedelta(hours=3), max_pages=3)
        self.assertEqual((pages, capped), (3, True))

    def test_empty_page_ends_search(self):
        got, pages, capped = li_posts.search(FakeSession([[1, 1]]), "k", NOW - timedelta(hours=3))
        self.assertEqual((len(got), pages, capped), (2, 2, False))


class TestPrefilter(unittest.TestCase):
    def test_prefilter(self):
        self.assertTrue(posts_ai.prefilter("We're hiring SDE-1! Send your CV to hr@x.in"))
        self.assertTrue(posts_ai.prefilter("My team is hiring a backend engineer, apply here"))
        self.assertFalse(posts_ai.prefilter("I am looking for a job as a Java developer #OpenToWork hiring"))
        self.assertFalse(posts_ai.prefilter("Great conference today about leadership"))
        self.assertFalse(posts_ai.prefilter("We are hiring accountants in Delhi"))
        india = posts.wanted_places({"countries": ["India"]})
        self.assertTrue(posts_ai.prefilter("Hiring SDE-1 in Bengaluru, apply now", india))
        self.assertTrue(posts_ai.prefilter("Hiring backend engineer | Remote (India)", india))
        self.assertFalse(posts_ai.prefilter("Hiring backend engineer in Austin, TX", india))
        self.assertFalse(posts_ai.prefilter("Hiring backend engineer in London, UK", india))
        self.assertTrue(posts_ai.prefilter("Hiring SDE-1, apply at https://x.co", india))   # no place: Claude decides
        self.assertTrue(posts_ai.prefilter("Hiring Flutter developer in Pune, US clients", india))
        self.assertTrue(posts_ai.prefilter("We are hiring a .NET developer, send your CV"))
        self.assertFalse(posts_ai.prefilter("Hiring go-getters for our sales team, apply now"))


CFG = {"title_exclude": ["senior", "lead"], "title_keep": [], "software_only": True,
       "exclude_role_families": ["qa", "ml"], "exclude_internships": True,
       "exclude_employment_types": ["Part-time"], "yoe_max": 2,
       "salary_buckets_lpa": [10, 20]}


def rec(**over):
    base = {"genuine": True, "reason": "", "company": "Acme", "via_recruiter": False,
            "poster_role": "hr", "country": "India", "location": "Bangalore", "work_mode": "onsite",
            "apply_emails": ["hr@acme.in"], "apply_links": ["https://acme.in/jobs/1"], "roles": []}
    base.update(over)
    return base


def role(title, ymin=None, emp="full-time"):
    return {"title": title, "yoe_min": ymin, "yoe_max": None, "employment_type": emp, "skills": ["Go"]}


class TestRoleFilters(unittest.TestCase):
    def test_your_example_keeps_sde1_drops_sde2(self):
        post = {"id": "1", "text": "Hiring SDE-1 & SDE-2 …", "author": "Dilruba N", "headline": "CEO",
                "author_url": "", "url": "https://l/1", "posted_at": NOW.isoformat(), "keywords": ["hiring sde"]}
        r = rec(roles=[role("SDE-1", 1.5), role("SDE-2", 4), role("Senior Backend Engineer"),
                       role("QA Engineer", 1), role("SDE Intern", 0, "internship"),
                       role("Backend Developer", None, "part-time"), role("Frontend Developer")])
        entries, why = posts.role_entries(post, r, CFG, {"show_contact_email": False}, NOW)
        self.assertEqual([(e["title"], e["section"]) for e in entries],
                         [("SDE-1", "eligible"), ("Frontend Developer", "not_stated")])
        self.assertEqual(sorted(why), sorted(["too_senior", "title", "excluded_role", "internship",
                                              "employment_type"]))
        e = entries[0]
        self.assertEqual(e["apply_emails"], [])          # hidden on the public site by default
        self.assertTrue(e["has_email"])
        self.assertEqual(e["kind"], "post")
        self.assertEqual(e["poster"]["name"], "Dilruba N")

    def test_country(self):
        self.assertTrue(posts.in_country(rec(country="India"), {}))
        self.assertTrue(posts.in_country(rec(country=None, location="Harlur, Bangalore"), {}))
        self.assertTrue(posts.in_country(rec(country=None, location="Remote (India)"), {}))
        self.assertFalse(posts.in_country(rec(country="United States", location="Austin"), {}))
        self.assertFalse(posts.in_country(rec(country=None, location="Latin America, Ecuador"), {}))
        self.assertFalse(posts.in_country(rec(country=None, location="Remote"), {}))
        self.assertTrue(posts.in_country(rec(country=None, location=None), {}))    # no signal: kept, flagged
        self.assertFalse(posts.in_country(rec(country="Indiana, US", location=None), {}))

    def test_company_score_is_sticky(self):
        st = store.empty_state()
        self.assertEqual(posts.company_score(st, "Acme  Labs", 70), 70)
        self.assertEqual(posts.company_score(st, "acme labs", 40), 70)   # first score wins
        self.assertEqual(posts.company_score(st, "Via recruiter", 10), 10)
        post = {"id": "9", "text": "Hiring SDE-1", "author": "A", "headline": "", "author_url": "",
                "url": "u", "posted_at": NOW.isoformat()}
        e, _ = posts.role_entries(post, rec(company="Acme Labs", company_score=20, country=None,
                                            location=None, roles=[role("SDE-1", 1)]),
                                  CFG, {}, NOW, st)
        self.assertEqual((e[0]["company_score"], e[0]["location_unclear"]), (70, True))

    def test_keyword_window(self):
        st = {"last_scrape_at": (NOW - timedelta(hours=1)).isoformat(),
              "keyword_scraped_at": {"a": (NOW - timedelta(hours=7)).isoformat()}}
        pc = {"window_hours": 3, "max_age_hours": 24}
        self.assertEqual(posts.window_start(st, pc, NOW, "a"), NOW - timedelta(hours=8))   # cut short before
        self.assertEqual(posts.window_start(st, pc, NOW, "new"), NOW - timedelta(hours=24))  # newly added
        self.assertEqual(posts.window_start({}, pc, NOW, "a"), NOW - timedelta(hours=3))     # first run

    def test_window(self):
        st = {"last_scrape_at": (NOW - timedelta(hours=5)).isoformat()}
        self.assertEqual(posts.window_start({}, {"window_hours": 3}, NOW), NOW - timedelta(hours=3))
        self.assertEqual(posts.window_start(st, {"window_hours": 3}, NOW), NOW - timedelta(hours=6))


class TestClassifyPending(unittest.TestCase):
    def _pending(self, texts):
        return {pid: {"id": pid, "text": t, "author": "X", "headline": "", "author_url": "",
                      "url": f"https://l/{pid}", "keywords": ["hiring sde"],
                      "posted_at": (NOW - timedelta(hours=i)).isoformat()}
                for i, (pid, t) in enumerate(texts.items())}

    def test_pipeline_with_fake_claude(self):
        st = store.empty_state()
        st["pending"] = self._pending({
            "a": "We're hiring SDE-1 (1+ yrs) in Pune, apply https://acme.in/j",
            "b": "Comment INTERESTED for 500 jobs list! hiring sde",
            "c": "Hiring backend engineer in Austin TX, apply now"})
        answers = {"a": rec(roles=[role("SDE-1", 1)]), "b": rec(genuine=False, roles=[]),
                   "c": rec(country="United States", location="Austin, TX",
                          roles=[role("Backend Engineer", 1)])}
        orig = posts_ai.classify
        posts_ai.classify = lambda batch, cfg: {p["id"]: answers[p["id"]] for p in batch}
        try:
            stats = posts.classify_pending(st, CFG, {"batch_size": 2, "parallel_claude": 2,
                                                     "timeout_sec": 1}, NOW,
                                           deadline=time.monotonic() + 60, log=lambda m: None)
        finally:
            posts_ai.classify = orig
        self.assertEqual([j["title"] for j in st["jobs"]], ["SDE-1"])
        self.assertEqual(stats["genuine"], 1)
        self.assertEqual(stats["dropped"], {"not_genuine": 1, "country": 1})
        self.assertEqual(st["pending"], {})
        self.assertEqual(set(st["skipped"]), {"b", "c"})   # never re-checked

    def test_unanswered_posts_stay_pending(self):
        st = store.empty_state()
        st["pending"] = self._pending({"a": "hiring sde"})
        orig = posts_ai.classify
        posts_ai.classify = lambda batch, cfg: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            posts.classify_pending(st, CFG, {"timeout_sec": 1}, NOW,
                                   deadline=time.monotonic() + 60, log=lambda m: None)
        finally:
            posts_ai.classify = orig
        self.assertIn("a", st["pending"])                  # retried next run, not lost


if __name__ == "__main__":
    unittest.main()
