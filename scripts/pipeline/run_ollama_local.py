#!/usr/bin/env python3
"""
Two-step Ollama scorer — profile-driven, no hardcoded candidate data.

  python3 scripts/pipeline/run_ollama_local.py [--run-dir PATH]

Default run-dir is the current working directory.

Single-step SCORE (full JD, no character cap):
  Holistic 0-100 scoring with built-in hard-gap and YoE checks.
  No triage pre-filter — avoids false positives from boilerplate-heavy JD intros.

Reads:  <run-dir>/ollama_input.json   {id: {jd, title, company, staffCount, ...}}
        candidate_profile.json        (searched upward from run-dir)

Writes: <run-dir>/scores_ollama.jsonl  resumable — skips already-scored IDs

Ollama must be running locally:  ollama serve
Model default: qwen2.5-coder:14b  (set ollama_model in candidate_profile.json)
"""

import argparse
import json
import os
import re
import sys
import urllib.request

# Regex fallback for min_yoe — broad patterns, order matters (most specific first).
# Deliberately not requiring the word "experience" after "years" so phrases like
# "5+ years of backend engineering experience" and "4-6 years of programming experience"
# are both caught regardless of what comes between "years" and "experience".
_WORD_TO_NUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
                "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
_WORD_NUM    = "|".join(_WORD_TO_NUM)
_YOE_PATTERNS = [
    re.compile(r'minimum\s+(?:of\s+)?(\d+)\s+years?', re.I),
    re.compile(r'at\s+least\s+(\d+)\s+years?', re.I),
    re.compile(r'(\d+)\s*[-–]\s*\d+\s*\+?\s*years?', re.I),   # "4-6 years", "12-14+ years"
    re.compile(r'(\d+)\s+to\s+\d+\s+years?', re.I),            # "3 to 5 years"
    re.compile(r'(\d+)\s*\+\s*years?\s+of\s', re.I),           # "5+ years of ..." (not "30+ years, our history")
    re.compile(rf'({_WORD_NUM})\s+or\s+more\s+years?', re.I),  # "five or more years"
    re.compile(rf'({_WORD_NUM})\s*\+\s*years?', re.I),         # "five+ years"
]

def _regex_min_yoe(text):
    """Extract the minimum YoE from JD text via regex; returns None if nothing found."""
    hits = []
    for pat in _YOE_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1).lower()
            hits.append(_WORD_TO_NUM.get(raw, int(raw)) if not raw.isdigit() else int(raw))
    return min(hits) if hits else None


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=None, help="Run directory containing ollama_input.json (default: cwd)")
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


def _load_profile(run_dir):
    root = _find_project_root(run_dir)
    if not root:
        print("ERROR: candidate_profile.json not found (searched up from run-dir).", file=sys.stderr)
        print("  Copy assets/candidate_profile.example.json to the repo root and fill in your details.", file=sys.stderr)
        sys.exit(1)
    print(f"Profile: {os.path.join(root, 'candidate_profile.json')}", file=sys.stderr)
    return json.load(open(os.path.join(root, "candidate_profile.json")))


def _build_config(p):
    model   = p.get("ollama_model", "qwen2.5-coder:14b")
    url     = p.get("ollama_url",   "http://localhost:11434")
    cap     = p.get("seniority_cap", 55)
    cap_pat = re.compile(
        p.get("seniority_cap_pattern", r"\b(lead|principal|staff|architect|director|manager|head|chief)\b"),
        re.I,
    )
    bonus    = p.get("tier1_bonus", 8)
    tier1_re = re.compile("|".join(p.get("tier1_companies", [])), re.I) if p.get("tier1_companies") else None
    min_yoe  = p.get("min_yoe_gate", 3)
    return dict(model=model, url=url, cap=cap, cap_pat=cap_pat, bonus=bonus,
                tier1_re=tier1_re, min_yoe=min_yoe)


def _build_score_prompt(p):
    name      = p["name"]
    summary   = p.get("summary", f"~{p.get('years_experience',3)} YoE SWE")
    strengths = "\n".join(f"- {s}" for s in p.get("strengths", []))
    gaps      = "\n".join(f"- {g}" for g in p.get("hard_gaps", []))
    yoe       = p.get("years_experience", 3)
    cap       = p.get("seniority_cap", 55)
    gate      = p.get("min_yoe_gate", 3)
    return f"""You are a senior technical recruiter screening LinkedIn job postings for a specific candidate. Return ONLY a JSON object, no prose, no markdown.

CANDIDATE: {name} — {summary}
STRENGTHS:
{strengths}

HARD GAPS (candidate cannot credibly apply where these are the PRIMARY job function):
{gaps}

HOW TO SCORE (think like a hiring manager who has the CV in front of them):

Step 0 — YoE gate (check this FIRST before anything else):
  Scan the ENTIRE JD for any experience requirement. Extract the LOWER bound.
  Numbers can be digits OR words: "five or more years" → 5, "four+ years" → 4.
    "4-6 years of programming experience" → 4, "5+ years of backend" → 5,
    "minimum 4 years" → 4, "at least 6 years" → 6, "five or more years of experience" → 5.
  If min_yoe extracted > {gate} → return immediately:
    {{"title": "<title>", "score": 0, "min_yoe": <extracted>, "matched_skills": [], "gap_skills": [], "discard_reason": "yoe_gt{gate}", "reasoning": "Discarded: JD requires <extracted>+ YoE, candidate has ~{yoe} YoE."}}
  Do NOT proceed to steps 1-6 if this fires.

Step 1 — What is the PRIMARY job function (80% of the role's time)?
  Be precise: "Java production support + incident triage" is different from "Java backend product development".

Step 2 — Hard gap check:
  If the PRIMARY job function matches a HARD GAP above → score ≤ 45. Stop. Company name is irrelevant.

Step 3 — Required skill coverage (most important step):
  FIRST: Separate all JD skills into two buckets:
    REQUIRED — skills listed as "required", "must have", "must-have", or without any qualifier,
               AND where the JD does NOT use soft language to introduce them.
    PREFERRED — skills the JD labels "nice to have", "good to have", "preferred", "bonus", "a plus",
                "desirable", OR introduces with soft language REGARDLESS of section header:
                "familiarity with X", "exposure to X", "knowledge of X", "understanding of X",
                "ideally", "experience with X is a plus".
                EXAMPLE: "Familiarity with WebRTC" → PREFERRED even if in a "Must-Have" section.
  ONLY count REQUIRED skills as gaps. Missing PREFERRED skills do NOT lower the score — they are
  informational only. List them in gap_skills but treat them as neutral.
  For each REQUIRED skill, check if it appears LITERALLY in the candidate's STRENGTHS list above.
  Do NOT infer — "has Java" does not mean "has Splunk" even if both appear in the JD.
  Also consider synonyms / variants (e.g. "AWS" vs "Amazon Web Services", "K8s" vs "Kubernetes").
  - 0-2 REQUIRED skills missing → base 75-90 (strong match)
  - 2-3 REQUIRED skills missing → base 60-74 (decent, flag gaps)
  - 3-4 REQUIRED skills missing → MAX score 65
  - 5+ REQUIRED skills missing  → MAX score 50

Step 4 — Seniority fit (candidate: ~{yoe} YoE, targeting SDE-II / mid-level):
  IMPORTANT: Use the JOB TITLE (given above) for seniority — NOT metadata fields like
  "Seniority level:" or "Experience level:" found inside the JD body (those are LinkedIn's
  internal classification, not the actual role level and are often wrong).
  - Junior/Intern/Fresher/Entry-level/Trainee in JOB TITLE → max 55 (overqualified)
  - SDE-I / Associate in JOB TITLE                         → max 60
  - SDE-II / Software Engineer / Senior in JOB TITLE       → PREFERRED, no penalty
  - Lead / Principal / Staff / Architect / Director / Manager / Head / Chief in JOB TITLE →
      MAX score = {cap} BEFORE any bonus. No exceptions.
  - 5+ YoE required explicitly → cap 60; 7+ YoE → cap 45
  - Senior / Sr in title alone is fine — score on merit (NOT capped)

Step 5 — Company size bonus (tiebreaker only, AFTER caps):
  - MNC (>1000 employees) → +5, but NEVER raises score past the Step 3 cap.

Step 6 — Sanity check: would a real hiring manager call this candidate for this exact role? If not → score < 60.

SCORE GUIDE: 90-100=near-perfect | 75-89=strong | 60-74=decent | 45-59=marginal | <45=wrong role

Return ONLY (when Step 0 does NOT fire):
{{"title": "<job title>", "score": <int 0-100>, "min_yoe": <lower-bound YoE extracted per Step 0 rule; null if absent>, "matched_skills": [<strings>], "gap_skills": [<strings>], "discard_reason": null, "reasoning": "<one sentence: PRIMARY role function and why this score>"}}
"""


def _ollama_call(url, model, system_prompt, user_content):
    body = {
        "model":  model,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    }
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    return json.loads(resp.get("message", {}).get("content", "{}"))


def _full_score(cfg, score_prompt, title, jd, company="", staff_count=None):
    mnc_note = " (MNC >1000)" if staff_count and staff_count > 1000 else ""
    user_msg = (
        f"JOB TITLE (use for TITLE CAP rules): {title}\n"
        f"COMPANY: {company}\n"
        f"STAFF_COUNT: {staff_count or 'unknown'}{mnc_note}\n\n"
        f"JD:\n{jd}"
    )
    parsed = _ollama_call(cfg["url"], cfg["model"], score_prompt, user_msg)
    out_title      = parsed.get("title", title)
    discard_reason = parsed.get("discard_reason")

    # Regex fallback: if LLM missed min_yoe, extract from full JD text
    if parsed.get("min_yoe") is None:
        parsed["min_yoe"] = _regex_min_yoe(jd)

    # Post-gate: LLM or regex found min_yoe > gate — discard even if LLM didn't fire Step 0
    gate = cfg["min_yoe"]
    if not discard_reason and parsed.get("min_yoe") and parsed["min_yoe"] > gate:
        discard_reason = f"yoe_gt{gate}"
        parsed["reasoning"] = f"Discarded: JD requires {parsed['min_yoe']}+ YoE (regex), candidate has ~{cfg.get('yoe', 3)} YoE."

    # LLM fired Step 0 YoE gate — return discard immediately, no scoring
    if discard_reason:
        return {
            "title":          out_title,
            "score":          0,
            "min_yoe":        parsed.get("min_yoe"),
            "matched_skills": [],
            "gap_skills":     [],
            "discard_reason": discard_reason,
            "reasoning":      parsed.get("reasoning", f"Discarded: {discard_reason}"),
            "tier1":          False,
        }

    score = max(0, min(100, int(parsed.get("score", 0))))
    tier1 = bool(cfg["tier1_re"] and cfg["tier1_re"].search(company or ""))
    if tier1:
        score = min(100, score + cfg["bonus"])
    # Hard post-hoc seniority cap — enforced regardless of LLM output
    if cfg["cap_pat"].search(out_title or title):
        score = min(score, cfg["cap"] + (cfg["bonus"] if tier1 else 0))
    return {
        "title":          out_title,
        "score":          score,
        "min_yoe":        parsed.get("min_yoe"),
        "matched_skills": parsed.get("matched_skills", []),
        "gap_skills":     parsed.get("gap_skills", []),
        "discard_reason": None,
        "reasoning":      parsed.get("reasoning", ""),
        "tier1":          tier1,
    }


def main():
    args    = _parse_args()
    run_dir = os.path.abspath(args.run_dir or os.getcwd())

    in_path  = os.path.join(run_dir, "ollama_input.json")
    out_path = os.path.join(run_dir, "scores_ollama.jsonl")

    if not os.path.exists(in_path):
        print(f"ERROR: {in_path} not found. Run the JD fetcher first.", file=sys.stderr)
        sys.exit(1)

    profile      = _load_profile(run_dir)
    cfg          = _build_config(profile)
    score_prompt = _build_score_prompt(profile)

    data = json.load(open(in_path))

    done_ids = set()
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line)["id"])

    todo = [(jid, rec) for jid, rec in data.items() if jid not in done_ids]
    print(f"{len(done_ids)} already done, {len(todo)} to process", file=sys.stderr)

    n_discard = n_keep = 0

    with open(out_path, "a") as out:
        for i, (jid, rec) in enumerate(todo):
            jd_raw      = rec.get("jd", "")
            jd_text     = jd_raw.get("jd", "") if isinstance(jd_raw, dict) else jd_raw
            staff_count = (jd_raw.get("staffCount") if isinstance(jd_raw, dict) else None) or rec.get("staffCount")
            title       = rec.get("title", "")
            company     = rec.get("company", "")

            try:
                # Regex pre-gate: skip Ollama entirely if YoE is clearly too high
                regex_yoe = _regex_min_yoe(jd_text)
                gate      = cfg["min_yoe"]
                if regex_yoe and regex_yoe > gate:
                    s = {
                        "title":          title,
                        "score":          0,
                        "min_yoe":        regex_yoe,
                        "matched_skills": [],
                        "gap_skills":     [],
                        "discard_reason": f"yoe_gt{gate}",
                        "reasoning":      f"Discarded: JD requires {regex_yoe}+ YoE (regex), candidate has ~{gate} YoE.",
                        "tier1":          False,
                    }
                else:
                    s = _full_score(cfg, score_prompt, title, jd_text, company, staff_count)
                row = {"id": jid, "company": company, "staffCount": staff_count, **s}
                if row.get("discard_reason"):
                    n_discard += 1
                    label = f"DISCARD({row['discard_reason']},min_yoe={row.get('min_yoe')})"
                else:
                    n_keep += 1
                    label = f"score={row['score']}"

            except Exception as e:
                # Not written: a timeout/Ollama hiccup must be retried on the next run,
                # not recorded as a scored 0 that the resume logic then skips forever.
                print(f"[{i+1}/{len(todo)}] {jid} {company!r} → ERR:{e} (will retry)", file=sys.stderr)
                continue

            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"[{i+1}/{len(todo)}] {jid} {company!r} → {label}", file=sys.stderr)

    print(
        f"\ndone — discarded={n_discard} kept={n_keep}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
