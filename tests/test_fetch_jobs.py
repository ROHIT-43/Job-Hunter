import importlib, os, sys, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
fj = importlib.import_module("fetch_jobs")


def _google_html(job_row, total=1, page_size=20):
    """Minimal AF_initDataCallback page mimicking Google's careers SSR blob."""
    import json
    ds1 = json.dumps([[job_row], None, total, page_size])
    return (
        "<html><script>AF_initDataCallback({key: 'ds:0', hash: '1', data:[]});"
        f"AF_initDataCallback({{key: 'ds:1', hash: '2', data:{ds1}}});"
        "</script></html>"
    )


class TestGoogleCareersAdapter(unittest.TestCase):
    def test_parses_job_row_at_confirmed_indices(self):
        # Indices matter here: 0=id,1=title,2=url,3=responsibilities,
        # 4=quals,7=company,9=locations,12=posted-epoch pair.
        row = ["123", "Software Engineer III", "https://x/apply",
               [None, "<ul><li>Do things</li></ul>"],
               [None, "<h3>Quals</h3>"],
               "tenant/path", None, "Google", "en-US",
               [["Bengaluru, Karnataka, India", ["addr"], "Bengaluru",
                 "560038", "KA", "IN"]],
               [None, "<p>about</p>"], [2, 3, 4], [1783082530, 276000000]]
        html = _google_html(row)
        with mock.patch.object(fj, "_get", return_value=html):
            jobs = fj.src_google_careers(max_pages=1)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["title"], "Software Engineer III")
        self.assertEqual(j["company"], "Google")
        self.assertIn("Bengaluru", j["location"])
        self.assertIn("Do things", j["description"])
        self.assertTrue(j["posted"].startswith("2026-07-03"))

    def test_zero_results_page_does_not_crash(self):
        # Google renders `data:[null,null,0,20]` (no jobs array) on no-match.
        html = ("<html><script>AF_initDataCallback({key: 'ds:1', hash: '2', "
                "data:[null,null,0,20]});</script></html>")
        with mock.patch.object(fj, "_get", return_value=html):
            jobs = fj.src_google_careers(max_pages=1)
        self.assertEqual(jobs, [])


class TestAmazonJobsAdapter(unittest.TestCase):
    def test_normalizes_country_code_to_full_name(self):
        # normalized_location ends in a 3-letter code; the pipeline's
        # --location substring match needs the full country name.
        payload = {"hits": 1, "jobs": [{
            "id_icims": "999", "title": "SDE II, Test Team",
            "company_name": "ADCI - Karnataka",
            "normalized_location": "Bengaluru, Karnataka, IND",
            "job_path": "/en/jobs/999/sde-ii",
            "description": "Build things.", "basic_qualifications": "3+ yrs",
            "posted_date": "July  2, 2026",
        }]}
        with mock.patch.object(fj, "_get_json", return_value=payload):
            jobs = fj.src_amazon_jobs(["software-development"], max_pages=1)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertTrue(j["location"].endswith("India"))
        self.assertNotIn("IND", j["location"])
        self.assertEqual(j["url"], "https://www.amazon.jobs/en/jobs/999/sde-ii")
        self.assertTrue(j["posted"].startswith("2026-07-02"))

    def test_stops_pagination_when_hits_exhausted(self):
        payload = {"hits": 1, "jobs": [{"id_icims": "1", "title": "SDE",
                    "company_name": "A", "normalized_location": "X, IND",
                    "job_path": "/1"}]}
        with mock.patch.object(fj, "_get_json", return_value=payload) as m:
            fj.src_amazon_jobs(["software-development"], max_pages=5,
                               result_limit=1)
        self.assertEqual(m.call_count, 1)


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
