#!/usr/bin/env python3
"""
config.py — Load data/pipeline/hunt_config.json (run knobs) with safe defaults.

Single source of run parameters for every path (browser / apify / keyless).
Missing file, missing keys, or null values all fall back to DEFAULTS.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..", "..")
DEFAULT_PATH = os.path.join(_ROOT, "data", "pipeline", "hunt_config.json")

DEFAULTS = {
    "window_hours": 24,
    "target_titles": [
        "Software Engineer",
        "Software Development Engineer",
        "Member of Technical Staff",
    ],
    "geo_id": "102713980",
    "experience_filters": ["3", "4"],
    "yoe_threshold": 3,
    "score_threshold": 70,
    "dictionary": "assets/skills_dictionary.json",
    "redflag_path": "data/pipeline/redflag_companies.json",
    "seen_path": "data/pipeline/seen_jobs.json",
    "apify_actor": "curious_coder/linkedin-jobs-scraper",
}


def load_config(path: str = None) -> dict:
    """Return run knobs, layering a user hunt_config.json over DEFAULTS.

    None/missing values fall back to defaults; a missing or corrupt file yields
    pure defaults so the skill always runs.
    """
    cfg = dict(DEFAULTS)
    p = path or DEFAULT_PATH
    if os.path.exists(p):
        try:
            with open(p) as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if v is not None})
        except (ValueError, OSError):
            pass
    return cfg
