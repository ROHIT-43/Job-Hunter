#!/usr/bin/env python3
"""
runner.py — Thin orchestrator called by the CronCreate prompt every 4 hours.

Runs fetch_and_filter.py, then prints the new_jobs_path for Claude to pick up
and run LLM scoring + tailoring on.

Usage (called by Claude via CronCreate):
    python scripts/pipeline/runner.py

Or manually:
    python scripts/pipeline/runner.py --no-fetch   # reuse last run's raw data
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..", "..")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--hours", type=int, default=4,
                    help="Time window in hours (default 4, pass 24 for full-day sweep)")
    args = ap.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%Hh")
    run_dir = os.path.join(_ROOT, "data", "pipeline", "runs", run_id)

    python = sys.executable if sys.executable else "python3"
    cmd = [
        python,
        os.path.join(_HERE, "fetch_and_filter.py"),
        "--run-id", run_id,
        "--out-dir", run_dir,
        "--hours", str(args.hours),
    ]
    if args.no_fetch:
        cmd.append("--no-fetch")

    print(f"=== Pipeline run {run_id} ===")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"ERROR: fetch_and_filter.py exited {result.returncode}", file=sys.stderr)
        sys.exit(1)

    # Parse summary from the last SUMMARY: line of fetch_and_filter output
    new_jobs_path = os.path.join(run_dir, "jobs_new.json")
    if not os.path.exists(new_jobs_path):
        print("No new jobs file found — pipeline may have failed.", file=sys.stderr)
        sys.exit(1)

    with open(new_jobs_path) as f:
        new_jobs = json.load(f)

    print(f"\n{'='*60}")
    print(f"Run complete: {run_id}")
    print(f"New jobs to score: {len(new_jobs)}")
    print(f"New jobs file: {new_jobs_path}")
    print(f"{'='*60}")

    if not new_jobs:
        print("No new jobs this cycle — nothing to score or tailor.")
        return

    # Print instructions for Claude's next step (LLM scoring + tailoring)
    print(f"""
NEXT STEPS FOR CLAUDE:
1. Read {new_jobs_path}
2. Score each job with LLM (Haiku agents, parallel) against:
   - Resume: {os.path.join(_ROOT, 'data/resume/resume-builder.tex')}
   - Profile: {os.path.join(_ROOT, 'data/profile.json')}
   - Bullet bank: {os.path.join(_ROOT, 'data/resume/bullet_bank.md')}
   Weights: Required 40% | Experience 25% | Preferred 20% | Presentation 15%
3. Filter: keep score >= 75
4. For score >= 85: tailor resume (4-fix approach), compile PDF via tectonic
5. Append results to: {os.path.join(_ROOT, 'data/pipeline/APPLY_QUEUE.md')}
   Format per job:
     ### [SCORE] Role — Company
     **Apply:** <url>
     **Posted:** <date> | **Location:** <location>
     **JD:** <run_dir>/jobs/<id>/jd.txt
     **Resume:** <path or N/A>
     **Strengths:** ... | **Gaps:** ...
     - [ ] Applied
""")


if __name__ == "__main__":
    main()
