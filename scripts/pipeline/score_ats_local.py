#!/usr/bin/env python3
"""
score_ats_local.py — Deterministic, zero-inference scorer for the browser path.

Drop-in alternative to run_ollama_local.py for when Ollama is unavailable (or
when you want a fast, auditable first pass over a large run). Reads the same
<run-dir>/ollama_input.json and writes the same <run-dir>/scores_ollama.jsonl,
so build_queue.py consumes the output unchanged.

  python3 scripts/pipeline/score_ats_local.py [--run-dir PATH]

Scoring is the dictionary ATS from scripts/lib/ats.py:

    score = |JD skills the candidate HAS| / |all JD skills| * 100

then three post-hoc adjustments that mirror run_ollama_local.py:

  1. low-signal cap  — a JD mentioning fewer than LOW_SIGNAL_MIN dictionary
     skills is capped at LOW_SIGNAL_CAP. Without this a JD whose only detected
     skill is "python" scores 100 and floods the top of the queue. score_jobs.py
     achieves the same by sorting low-signal roles last; build_queue.py sorts on
     score alone, so the guard has to live in the score here.
  2. tier1 bonus     — +profile["tier1_bonus"] for profile["tier1_companies"].
  3. seniority cap   — titles matching profile["seniority_cap_pattern"] are
     capped at profile["seniority_cap"] (+ the tier1 bonus if it applied).

min_yoe comes from ats.extract_min_yoe (regex over the JD; highest stated floor
wins). It is reported, never used to change the score — build_queue.py applies
the YoE gate.

Honest limits vs the LLM scorer: no hard-gap reasoning (a Salesforce role whose
JD happens to name Java/SQL still scores on overlap), no required-vs-preferred
weighting, and no reading of intent — only literal dictionary hits. Treat the
number as coverage, not judgement.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lib import ats  # noqa: E402

LOW_SIGNAL_MIN = 3
LOW_SIGNAL_CAP = 40


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=None,
                   help="Run directory containing ollama_input.json (default: cwd)")
    p.add_argument("--profile", default=None,
                   help="Candidate profile with HAVE skills (default: <root>/data/profile.json)")
    return p.parse_args()


def _find_project_root(start_dir):
    cur = os.path.abspath(start_dir)
    for _ in range(10):
        if os.path.exists(os.path.join(cur, "candidate_profile.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _have_skills(profile_path):
    """HAVE = skills[] + every experience[].skills[] + every projects[].skills[]."""
    with open(profile_path) as f:
        p = json.load(f)
    have = set(p.get("skills", []))
    for block in ("experience", "projects"):
        for row in p.get(block, []) or []:
            have.update(row.get("skills", []) or [])
    return {s.lower() for s in have}


def _summary(jd, limit=160):
    text = re.sub(r"\s+", " ", (jd or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def main():
    args    = _parse_args()
    run_dir = os.path.abspath(args.run_dir or os.getcwd())
    in_path = os.path.join(run_dir, "ollama_input.json")
    if not os.path.exists(in_path):
        print(f"ERROR: {in_path} not found.", file=sys.stderr)
        sys.exit(1)

    root = _find_project_root(run_dir)
    if not root:
        print("ERROR: candidate_profile.json not found above the run dir.", file=sys.stderr)
        sys.exit(1)

    profile      = json.load(open(os.path.join(root, "candidate_profile.json")))
    prof_path    = args.profile or os.path.join(root, "data", "profile.json")
    have         = _have_skills(prof_path)
    alias_index  = ats.build_alias_index(ats.load_dictionary())

    seniority_cap = profile.get("seniority_cap", 55)
    tier1_bonus   = profile.get("tier1_bonus", 8)
    CAP_RE = (re.compile(profile["seniority_cap_pattern"], re.I)
              if profile.get("seniority_cap_pattern") else re.compile(r"(?!)"))
    TIER1_RE = (re.compile("|".join(profile.get("tier1_companies", [])), re.I)
                if profile.get("tier1_companies") else re.compile(r"(?!)"))

    jobs = json.load(open(in_path))
    out_path = os.path.join(run_dir, "scores_ollama.jsonl")

    n_low = n_tier1 = n_capped = 0
    with open(out_path, "w") as out:
        for jid, j in jobs.items():
            jd    = j.get("jd", "") or ""
            title = (j.get("title", "") or "").strip()
            comp  = (j.get("company", "") or "").strip()

            s     = ats.score_job({"title": title, "description": jd}, have, alias_index)
            score = s["ats_pct"]
            notes = []

            if s["jd_count"] < LOW_SIGNAL_MIN:
                score = min(score, LOW_SIGNAL_CAP)
                notes.append(f"low_signal:{s['jd_count']}_skills")
                n_low += 1

            tier1 = bool(comp and TIER1_RE.search(comp))
            if tier1:
                score = min(100, score + tier1_bonus)
                notes.append(f"tier1:+{tier1_bonus}")
                n_tier1 += 1

            if CAP_RE.search(title):
                ceiling = seniority_cap + (tier1_bonus if tier1 else 0)
                if score > ceiling:
                    score = ceiling
                    n_capped += 1
                notes.append(f"seniority_cap:{ceiling}")

            out.write(json.dumps({
                "id":             str(jid),
                "score":          int(score),
                "min_yoe":        ats.extract_min_yoe(jd),
                "matched_skills": s["matches"],
                "gap_skills":     s["gaps"],
                "jd_summary":     _summary(jd),
                "reasoning":      f"dictionary ATS {s['have_count']}/{s['jd_count']} JD skills"
                                  + (" [" + "; ".join(notes) + "]" if notes else ""),
                "title":          title,
                "company":        comp,
                "location":       j.get("location", ""),
                "listedAt":       j.get("listedAt"),
                "applies":        j.get("applies"),
                "staffCount":     j.get("staffCount"),
                "tier1":          tier1,
                "url":            f"https://www.linkedin.com/jobs/view/{jid}",
                "fetched":        len(jd) > 100,
                "scorer":         "dictionary_ats",
            }) + "\n")

    print(f"scored {len(jobs)} jobs -> {out_path}")
    print(f"  low-signal capped at {LOW_SIGNAL_CAP}: {n_low}")
    print(f"  tier1 bonus applied:                  {n_tier1}")
    print(f"  seniority-capped titles:              {n_capped}")


if __name__ == "__main__":
    main()
