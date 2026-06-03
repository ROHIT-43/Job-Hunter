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
