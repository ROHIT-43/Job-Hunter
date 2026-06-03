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
