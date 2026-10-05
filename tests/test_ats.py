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


class TestMinYoe(unittest.TestCase):
    def test_plus(self):
        self.assertEqual(ats.extract_min_yoe("5+ years of backend"), 5)

    def test_plain(self):
        self.assertEqual(ats.extract_min_yoe("3 years experience required"), 3)

    def test_range_lower_bound(self):
        self.assertEqual(ats.extract_min_yoe("3-5 years"), 3)
        self.assertEqual(ats.extract_min_yoe("3 to 5 yrs"), 3)

    def test_at_least_and_minimum(self):
        self.assertEqual(ats.extract_min_yoe("at least 4 years"), 4)
        self.assertEqual(ats.extract_min_yoe("minimum of 2 years"), 2)

    def test_multiple_takes_max_floor(self):
        self.assertEqual(
            ats.extract_min_yoe("8+ years overall, 2+ years with Kafka"), 8)

    def test_none_when_absent(self):
        self.assertIsNone(ats.extract_min_yoe("Bachelor's degree preferred"))

    def test_ignores_absurd(self):
        self.assertIsNone(ats.extract_min_yoe("100 years of heritage"))


class TestWeighted(unittest.TestCase):
    def setUp(self):
        self.idx = ats.build_alias_index(ats.load_dictionary())

    def test_required_preferred_split(self):
        r = ats.weighted_score(
            required=["python", "kafka", "aws"],
            preferred=["terraform", "snowflake"],
            have_skills=["python", "kafka", "terraform"],
            alias_index=self.idx)
        # (1*2 + 0.3*1) / (1*3 + 0.3*2) = 2.3/3.6 = 63.9 -> 64
        self.assertEqual(r["ats_pct"], 64)
        self.assertEqual(r["missing_required"], ["aws"])
        self.assertEqual(r["matched_required"], ["kafka", "python"])
        self.assertEqual(r["matched_preferred"], ["terraform"])

    def test_all_required_no_preferred(self):
        r = ats.weighted_score(["python", "go"], [], ["python", "go"], self.idx)
        self.assertEqual(r["ats_pct"], 100)

    def test_empty_labels_zero(self):
        r = ats.weighted_score([], [], ["python"], self.idx)
        self.assertEqual(r["ats_pct"], 0)

    def test_alias_canonicalized(self):
        # "k8s" required, candidate has "kubernetes" -> matched
        r = ats.weighted_score(["k8s"], [], ["kubernetes"], self.idx)
        self.assertEqual(r["ats_pct"], 100)
        self.assertEqual(r["missing_required"], [])

    def test_skill_in_both_counts_as_required(self):
        r = ats.weighted_score(["python"], ["python"], [], self.idx)
        # python is required only; total weight = 1.0, got 0 -> 0%
        self.assertEqual(r["required_count"], 1)
        self.assertEqual(r["preferred_count"], 0)


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

    def test_whole_word_names(self):
        # substring matching once tiered Motorola/Coca-Cola via "ola", Sapient via "sap"
        for name in ("Motorola Solutions", "Coca-Cola", "Credit Saison",
                     "Metamorphosis Labs", "Disney Star"):
            self.assertEqual(ats.company_tier(name)[0], "neutral", name)
        self.assertEqual(ats.company_tier("Volkswagen Group")[0], "T2")
        self.assertEqual(ats.company_tier("CommerceIQ")[0], "T2")

    def test_unknown_neutral(self):
        self.assertEqual(ats.company_tier("Quaxon Labs")[0], "neutral")


if __name__ == "__main__":
    unittest.main()
