#!/usr/bin/env python3
"""
Create a new pipeline run directory and print the 5-step workflow.

  python3 scripts/new_run.py [--window 2h] [--label v1]

Examples:
  python3 scripts/new_run.py              # defaults: 2h window, v1
  python3 scripts/new_run.py --window 24h
  python3 scripts/new_run.py --window 4h --label v2
"""

import argparse
import datetime
import os
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--window", default="2h",  help="Time window label, e.g. 2h, 4h, 24h (default: 2h)")
    p.add_argument("--label",  default="v1",  help="Suffix label to distinguish re-runs (default: v1)")
    args = p.parse_args()

    # ── Locate repo root ───────────────────────────────────────────────────────
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)   # scripts/ → repo root
    if not os.path.exists(os.path.join(root, "candidate_profile.json")):
        print(
            "WARNING: candidate_profile.json not found at repo root.\n"
            "  Copy assets/candidate_profile.example.json → candidate_profile.json and fill in your details.\n",
            file=sys.stderr,
        )

    # ── Build run dir name ─────────────────────────────────────────────────────
    ist     = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist)
    ts      = now_ist.strftime("%Y-%m-%d_%H%M")
    run_name = f"{ts}_{args.window}_{args.label}"
    run_dir  = os.path.join(root, "data", "pipeline", "browser_runs", run_name)

    os.makedirs(run_dir, exist_ok=True)
    print(f"Created: {run_dir}\n")

    # ── Window seconds for the scraper ────────────────────────────────────────
    window_str = args.window.lower()
    if window_str.endswith("h"):
        window_secs = int(float(window_str[:-1]) * 3600)
    elif window_str.endswith("m"):
        window_secs = int(window_str[:-1]) * 60
    elif window_str.endswith("d"):
        window_secs = int(window_str[:-1]) * 86400
    else:
        window_secs = 7200

    repo = os.path.relpath(root)
    rel  = os.path.relpath(run_dir)

    # ── Print step-by-step workflow ───────────────────────────────────────────
    print("=" * 68)
    print(f"  Run: {run_name}")
    print(f"  Dir: {rel}/")
    print("=" * 68)
    print()
    print("STEP 1 — Scrape LinkedIn")
    print(f"  • Open scripts/browser/scrape_linkedin_browser.js")
    print(f"  • Set WINDOW_SECONDS = {window_secs}  ({args.window} window)")
    print(f"  • Paste into authenticated LinkedIn browser tab")
    print(f"  • Wait for auto-download → save as:  {rel}/to_score.json")
    print()
    print("STEP 2 — Pre-fetch filter")
    print(f"  python3 {repo}/scripts/pipeline/filter_jobs.py \\")
    print(f"      --run-dir {rel}/")
    print(f"  Output: {rel}/to_fetch.json")
    print()
    print("STEP 3 — Fetch full JDs")
    print(f"  • In the same LinkedIn tab, inject to_fetch.json:")
    print(f"      // Option A — paste JSON directly:")
    print(f"      window.__TO_SCORE = <paste contents of to_fetch.json>")
    print(f"      // Option B — if running a local server:")
    print(f"      const d = await fetch('http://localhost:8000/to_fetch.json').then(r=>r.json());")
    print(f"      window.__TO_SCORE = d;")
    print(f"  • Paste scripts/browser/fetch_jds_browser.js")
    print(f"  • Wait for auto-download → save as:  {rel}/ollama_input.json")
    print()
    print("STEP 4 — Score with Ollama (must be running: ollama serve)")
    print(f"  python3 {repo}/scripts/pipeline/run_ollama_local.py \\")
    print(f"      --run-dir {rel}/")
    print()
    print("STEP 5 — Build queue")
    print(f"  python3 {repo}/scripts/pipeline/build_queue.py \\")
    print(f"      --run-dir {rel}/")
    print(f"  Output: data/pipeline/BROWSER_QUEUE.md  (prepended)")
    print()
    print("=" * 68)
    print()


if __name__ == "__main__":
    main()
