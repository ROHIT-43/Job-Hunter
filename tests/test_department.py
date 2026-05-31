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


if __name__ == "__main__":
    unittest.main()
