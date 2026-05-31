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
