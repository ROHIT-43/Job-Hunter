#!/usr/bin/env python3
"""
Queue builder — gate, group, and write BROWSER_QUEUE.md. Updates seen_jobs.

  python3 scripts/pipeline/build_queue.py [--run-dir PATH]

Default run-dir is the current working directory.

Gate: score >= score_threshold  AND  min_yoe <= gate  AND  company not in
      avoid list  AND  title not in role_skip patterns

score_threshold comes from data/pipeline/hunt_config.json (default 70).
Set it to 0 to queue every scored role and let the YoE gate be the only
score-independent exclusion. --min-score overrides it for a single run.

Output: two sections prepended to BROWSER_QUEUE.md
  1. DIRECT COMPANY ROLES — grouped by company, sorted by best score
  2. VIA STAFFING / PLATFORMS — middleman/staffing agencies, separate section

Also updates seen_jobs.json with all scored IDs from this run.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from collections import defaultdict

try:                                  # run as a script: scripts/pipeline is on sys.path
    from config import load_config
except ImportError:                   # imported as pipeline.build_queue
    from .config import load_config


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=None, help="Run directory containing scores_ollama.jsonl (default: cwd)")
    p.add_argument("--min-score", type=int, default=None,
                   help="Score gate for this run; overrides hunt_config score_threshold (default 70)")
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


def _infer_window(run_dir_name):
    for part in run_dir_name.split("_"):
        if re.match(r"^\d+[hd]$", part):
            return part
    return "Nh"


def _rel_time(ts):
    if not ts:
        return None
    try:
        # LinkedIn: epoch milliseconds (int or numeric string)
        ts_sec = int(ts) / 1000
    except (ValueError, TypeError):
        # Google/Amazon/Microsoft: ISO-8601 string
        import datetime as _dt
        try:
            dt = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            ts_sec = dt.timestamp()
        except (ValueError, TypeError):
            return None
    diff_h = (time.time() - ts_sec) / 3600
    if diff_h < 1:
        return f"{int(diff_h*60)}m ago"
    if diff_h < 24:
        return f"{int(diff_h)}h ago"
    return f"{int(diff_h/24)}d ago"


def main():
    args    = _parse_args()
    run_dir = os.path.abspath(args.run_dir or os.getcwd())

    scores_path = os.path.join(run_dir, "scores_ollama.jsonl")
    if not os.path.exists(scores_path):
        print(f"ERROR: {scores_path} not found. Run run_ollama_local.py first.", file=sys.stderr)
        sys.exit(1)

    root = _find_project_root(run_dir)
    if not root:
        print("ERROR: candidate_profile.json not found.", file=sys.stderr)
        sys.exit(1)

    profile = json.load(open(os.path.join(root, "candidate_profile.json")))

    cfg       = load_config()
    min_score = args.min_score if args.min_score is not None else cfg["score_threshold"]

    seen_path  = os.path.join(root, profile.get("seen_jobs_file",       "data/pipeline/seen_jobs.json"))
    queue_path = os.path.join(root, profile.get("queue_file",           "data/pipeline/BROWSER_QUEUE.md"))
    avoid_path = os.path.join(root, profile.get("avoid_companies_file", "data/pipeline/companies_avoid.txt"))

    MIDDLEMAN = (
        re.compile("|".join(profile.get("middleman_companies", [])), re.I)
        if profile.get("middleman_companies") else re.compile(r"(?!)", re.I)
    )
    ROLE_SKIP = (
        re.compile("|".join(profile.get("role_skip_patterns", [])), re.I)
        if profile.get("role_skip_patterns") else re.compile(r"(?!)", re.I)
    )

    TITLE_ALLOW = (
        re.compile("|".join(profile.get("title_allow_patterns", [])), re.I)
        if profile.get("title_allow_patterns") else None      # None = allow everything
    )

    min_yoe_gate = profile.get("min_yoe_gate", 3)
    tier1_bonus  = profile.get("tier1_bonus",  8)

    # ── Load scores — dedup by ID (last entry wins) ───────────────────────────
    scores_by_id = {}
    with open(scores_path) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                scores_by_id[r["id"]] = r

    # Only keep scores in this run's ollama_input.json (prevents bleed-over when
    # the JSONL is copied from a previous run dir).
    input_path = os.path.join(run_dir, "ollama_input.json")
    if os.path.exists(input_path):
        run_ids = set(json.load(open(input_path)).keys())
        scores  = [r for r in scores_by_id.values() if r["id"] in run_ids]
    else:
        scores = list(scores_by_id.values())

    # ── Location + title + listedAt from scrape (ground truth for titles) ─────
    loc_map   = {}
    title_map = {}
    listed_map = {}
    scrape_path = os.path.join(run_dir, "to_score.json")
    if os.path.exists(scrape_path):
        for r in json.load(open(scrape_path)):
            raw = r.get("location", "")
            loc = re.sub(r",?\s*India\s*(\(.*\))?$", "", raw).strip()
            loc = re.sub(r"\(.*\)$", "", loc).strip().rstrip(",").strip()
            loc_map[r["id"]]  = loc or "India"
            t = re.sub(r"[\xa0\s]+$", "", r.get("title", "") or "").strip()
            if t:
                title_map[r["id"]] = t
            if r.get("listedAt"):
                listed_map[r["id"]] = r["listedAt"]

    # listedAt + applies + url from ollama_input.json (more accurate — from full JD)
    applies_map = {}
    url_map     = {}
    if os.path.exists(input_path):
        for jid, rec in json.load(open(input_path)).items():
            if rec.get("listedAt"):
                listed_map[jid] = rec["listedAt"]
            if rec.get("applies") is not None:
                applies_map[jid] = rec["applies"]
            if rec.get("url"):
                url_map[jid] = rec["url"]

    # ── companies_avoid ───────────────────────────────────────────────────────
    avoid = set()
    if os.path.exists(avoid_path):
        with open(avoid_path) as f:
            avoid = {l.strip().lower() for l in f if l.strip()}

    # ── Gate ──────────────────────────────────────────────────────────────────
    qualified = [
        r for r in scores
        if r["score"] >= min_score
        and (r.get("min_yoe") is None or r["min_yoe"] <= min_yoe_gate)
        and r.get("company", "").lower() not in avoid
        and not ROLE_SKIP.search(r.get("title", ""))
        and (TITLE_ALLOW is None or TITLE_ALLOW.search(r.get("title", "")))
    ]
    qualified.sort(key=lambda r: -r["score"])

    direct     = [r for r in qualified if not MIDDLEMAN.search(r.get("company", ""))]
    via_agency = [r for r in qualified if     MIDDLEMAN.search(r.get("company", ""))]

    by_company    = defaultdict(list)
    for r in direct:
        by_company[r["company"]].append(r)
    company_order = sorted(by_company, key=lambda c: -max(r["score"] for r in by_company[c]))

    # ── IST timestamp (use ollama_input.json mtime = when JD fetch completed) ─
    ist      = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    if os.path.exists(input_path):
        fetch_ts = datetime.datetime.fromtimestamp(os.path.getmtime(input_path), tz=ist)
    else:
        fetch_ts = datetime.datetime.now(ist)
    ts     = fetch_ts.strftime("%Y-%m-%d %H:%M IST")
    window = _infer_window(os.path.basename(run_dir))
    label  = f"Ollama 2-step triage+score, tier1 +{tier1_bonus}, <={min_yoe_gate}yr"

    n_direct = len(direct)
    n_agency = len(via_agency)
    n_cos    = len(by_company)

    lines = [
        f"## {window} run — {ts} ({label}) — {n_cos} companies ({n_direct} roles) + {n_agency} agency\n",
        f"**Funnel:** scrape → triage+scored {len(scores)} → {len(qualified)} eligible "
        f"(score≥{min_score}, min_yoe≤{min_yoe_gate}, role-filtered)\n",
    ]

    lines.append("\n### 🏢 Direct Company Roles\n")
    for company in company_order:
        roles     = sorted(by_company[company], key=lambda r: -r["score"])
        best      = roles[0]
        tier      = " ⭐" if best.get("tier1") else ""
        max_score = best["score"]
        strengths = ", ".join(best.get("matched_skills", [])) or "—"
        gaps      = ", ".join(best.get("gap_skills", []))     or "—"
        min_yoe   = best.get("min_yoe")
        reasoning = re.sub(r'\s*\[seniority_cap:[^\]]+\]', '', best.get("reasoning", ""))

        lines.append(f"\n#### [{max_score}]{tier} {company} — {len(roles)} role{'s' if len(roles)>1 else ''}")
        for r in roles:
            jid      = r["id"]
            title    = title_map.get(jid) or r.get("title") or "?"
            score    = r["score"]
            loc      = loc_map.get(jid, "India")
            url      = url_map.get(jid) or f"https://www.linkedin.com/jobs/view/{jid}/"
            posted   = _rel_time(listed_map.get(jid))
            applies  = applies_map.get(jid)
            time_tag = f" [{posted}]"         if posted  else ""
            app_tag  = f" [{applies} clicked apply]" if applies else ""
            lines.append(f"- [{score}] {title} @ {loc} → {url}{time_tag}{app_tag}")
        lines.append(f"**Strengths:** {strengths}  |  **Gaps:** {gaps}  |  **min_yoe:** {min_yoe}")
        lines.append(f"> {reasoning}")
        lines.append("- [ ] Applied\n")

    if via_agency:
        lines.append("\n---\n")
        lines.append(f"### 🔗 Via Staffing / Platforms — {n_agency} listings\n")
        lines.append("_These are 3rd-party postings — actual employer unknown._\n")

        agency_by_co = defaultdict(list)
        for r in via_agency:
            agency_by_co[r["company"]].append(r)
        agency_order = sorted(agency_by_co, key=lambda c: -max(r["score"] for r in agency_by_co[c]))

        for company in agency_order:
            roles = sorted(agency_by_co[company], key=lambda r: -r["score"])
            lines.append(f"\n**{company}**")
            for r in roles:
                jid      = r["id"]
                title    = title_map.get(jid) or r.get("title") or "?"
                score    = r["score"]
                loc      = loc_map.get(jid, "India")
                url      = url_map.get(jid) or f"https://www.linkedin.com/jobs/view/{jid}/"
                posted   = _rel_time(listed_map.get(jid))
                applies  = applies_map.get(jid)
                time_tag = f" [{posted}]"         if posted  else ""
                app_tag  = f" [{applies} clicked apply]" if applies else ""
                lines.append(f"- [{score}] {title} @ {loc} → {url}{time_tag}{app_tag}")

    new_section = "\n".join(lines)

    # ── Prepend to BROWSER_QUEUE.md ───────────────────────────────────────────
    os.makedirs(os.path.dirname(queue_path), exist_ok=True)
    existing = ""
    if os.path.exists(queue_path):
        with open(queue_path) as f:
            existing = f.read()
    with open(queue_path, "w") as f:
        f.write(new_section + ("\n\n" if existing else "") + existing)
    print(f"Written {n_cos} company groups ({n_direct} direct + {n_agency} agency) → {queue_path}")

    # ── Per-run copies, so each scrape keeps its own openings ────────────────
    run_queue = os.path.join(run_dir, "QUEUE.md")
    with open(run_queue, "w") as f:
        f.write(new_section)
    run_matches = os.path.join(run_dir, "matches.json")
    with open(run_matches, "w") as f:
        json.dump(qualified, f, indent=1)
    print(f"Run copies: {run_queue}")
    print(f"            {run_matches}  ({len(qualified)} openings)")

    # ── Update seen_jobs ──────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(seen_path), exist_ok=True)
    seen   = json.load(open(seen_path)) if os.path.exists(seen_path) else {}
    before = len(seen)
    for r in scores:
        jid = str(r['id'])
        key = f"li:{jid}" if jid.isdigit() else jid
        if key not in seen:
            seen[key] = 1
    after = len(seen)
    with open(seen_path, "w") as f:
        json.dump(seen, f)
    print(f"seen_jobs: {before} → {after} (+{after-before} new)")

    print(f"\nTop direct companies:")
    for c in company_order[:10]:
        best = max(by_company[c], key=lambda r: r["score"])
        print(f"  [{best['score']}]{'⭐' if best.get('tier1') else ' '} {c} ({len(by_company[c])} roles)")


if __name__ == "__main__":
    main()
