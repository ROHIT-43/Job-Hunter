#!/usr/bin/env python3
"""
yoe_split.py — Years-of-experience triage for the shared backbone.

parse_min_yoe() is a digit-only fallback heuristic. The authoritative min_yoe is
set by the model during scoring (it reads the full JD, resolves word-numbers like
"six years", and applies the header-wins rule for self-contradicting JDs). When a
match already carries min_yoe, the splitter honors it.

A role whose stated minimum exceeds the candidate's threshold (default 3 yrs) goes
to the Stretch section; everything else (incl. no explicit minimum) stays Primary.
"""
import re

_YOE_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:[-–]|to)?\s*(\d{1,2})?\s*\+?\s*years?", re.IGNORECASE)


def parse_min_yoe(text: str):
    """Lowest stated minimum YoE (digit forms only), or None if no numeric mention."""
    if not text:
        return None
    mins = [int(m.group(1)) for m in _YOE_RE.finditer(text)]
    return min(mins) if mins else None


def classify(min_yoe, threshold: int = 3) -> str:
    """'stretch' when an explicit minimum exceeds threshold, else 'primary'."""
    if min_yoe is not None and min_yoe > threshold:
        return "stretch"
    return "primary"


def split_matches(matches, threshold: int = 3, text_key: str = "jd_summary"):
    """Tag each match with min_yoe + stretch, and return (primary, stretch) lists.

    Honors a preset match['min_yoe']; otherwise falls back to parsing text_key.
    """
    primary, stretch = [], []
    for m in matches:
        mn = m.get("min_yoe")
        if mn is None:
            mn = parse_min_yoe(m.get(text_key, ""))
        m["min_yoe"] = mn
        is_stretch = classify(mn, threshold) == "stretch"
        m["stretch"] = is_stretch
        (stretch if is_stretch else primary).append(m)
    return primary, stretch
