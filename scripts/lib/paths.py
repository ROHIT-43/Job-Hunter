"""Locate bundled assets relative to the repo root.

lib/paths.py lives at <repo>/scripts/lib/paths.py, so the repo root is three
directories up. All bundled data (departments.json, skills_dictionary.json)
lives under <repo>/assets/.
"""
import os

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")


def asset(name):
    """Absolute path to a bundled asset file under assets/."""
    return os.path.join(ASSETS_DIR, name)
