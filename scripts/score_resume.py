#!/usr/bin/env python3
"""score_resume.py — score a single JD (plain-text file) against the candidate
profile, the same way score_jobs.py scores a posting. Prints the ATS% plus the
matched and missing dictionary skills, so we can gate resume tailoring on a
100% honest match.

Usage: python scripts/score_resume.py <jd.txt> --profile data/profile.json
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ats  # noqa: E402


def have_skills(profile_path):
    prof = json.load(open(profile_path))
    norm = lambda xs: [str(s).lower().strip() for s in (xs or []) if str(s).strip()]
    have = set(norm(prof.get("skills")))
    for e in prof.get("experience") or []:
        have |= set(norm(e.get("skills")))
    for p in prof.get("projects") or []:
        have |= set(norm(p.get("skills")))
    return sorted(have)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jd")
    ap.add_argument("--profile", required=True)
    args = ap.parse_args()
    have = have_skills(args.profile)
    idx = ats.build_alias_index(ats.load_dictionary())
    jd = open(args.jd).read()
    job = {"title": "", "description": jd, "tags": []}
    s = ats.score_job(job, have, idx)
    out = {"ats_pct": s["ats_pct"], "low_signal": s["low_signal"],
           "have": s["matches"], "missing": s["gaps"],
           "min_yoe": ats.extract_min_yoe(jd)}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
