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
