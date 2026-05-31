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
