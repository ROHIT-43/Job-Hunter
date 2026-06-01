#!/usr/bin/env python3
"""
fetch_and_filter.py — Stage 1 of the 4-hour pipeline.

1. Triggers the Apify task (linkedin-jobs-scraper-task)
2. Waits for completion (polls every 15s, max 20 min)
3. Downloads all results
4. Normalizes field names to the shared schema
5. Pre-filters (title / seniority / YoE / company size)
6. Dedups against seen_jobs.json
7. Writes per-run output files + returns new jobs for scoring

Usage:
    python scripts/pipeline/fetch_and_filter.py \
        --run-id 2026-06-01_10h \
        --out-dir data/pipeline/runs/2026-06-01_10h

Returns exit code 0 always. Prints a JSON summary to stdout on the last line:
    {"new_jobs": N, "filtered": M, "total_fetched": K, "run_dir": "..."}
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── repo root on path ────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..", "..")
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from pipeline.pre_filter import filter_jobs  # noqa: E402
from pipeline import dedup                   # noqa: E402

APIFY_BASE = "https://api.apify.com/v2"
TASK_ID = "cXgCZqRwfqnOOVojV"
POLL_INTERVAL = 15   # seconds between status checks
MAX_WAIT = 1200      # 20 minutes max


# ── helpers ──────────────────────────────────────────────────────────────────

def load_token() -> str:
    for path in (
        os.path.join(os.getcwd(), ".env"),
        os.path.join(_ROOT, ".env"),
    ):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("APIFY_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("APIFY_TOKEN", "")


def _get(url: str, token: str):
    req = urllib.request.Request(
        url if "token=" in url else f"{url}{'&' if '?' in url else '?'}token={token}"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _post(url: str, token: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{url}{'&' if '?' in url else '?'}token={token}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def normalize(raw: dict) -> dict:
    """Map actor output fields to shared schema."""
    desc = raw.get("descriptionText") or raw.get("description") or ""
    industries = raw.get("industries") or []
    return {
        "id": f"li:{raw.get('id') or raw.get('refId') or ''}",
        "source": "linkedin",
        "title": raw.get("title") or raw.get("jobTitle") or "",
        "company": raw.get("companyName") or raw.get("company") or "",
        "companyEmployeesCount": raw.get("companyEmployeesCount"),
        "location": raw.get("location") or "",
        "remote": raw.get("workRemoteAllowed"),
        "visa_sponsorship": None,
        "tags": raw.get("jobFunction") or [],
        "salary": raw.get("salary"),
        "description": desc,
        "url": raw.get("link") or raw.get("applyUrl") or "",
        "posted": (raw.get("postedAt") or "")[:10] or None,
        "seniority": raw.get("seniorityLevel") or "",
        "employmentType": raw.get("employmentType") or "",
        "sector": industries[0] if industries else "",
        "companyLinkedinUrl": raw.get("companyLinkedinUrl") or "",
        "applicantsCount": raw.get("applicantsCount"),
    }


# ── main stages ──────────────────────────────────────────────────────────────

def run_apify_task(token: str):
    """Trigger the task and return (run_id, dataset_id)."""
    resp = _post(f"{APIFY_BASE}/actor-tasks/{TASK_ID}/runs", token, {})
    data = resp["data"]
    return data["id"], data["defaultDatasetId"]


def wait_for_run(run_id: str, token: str) -> str:
    """Poll until terminal status. Returns final status string."""
    terminal = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
    deadline = time.monotonic() + MAX_WAIT
    while time.monotonic() < deadline:
        resp = _get(f"{APIFY_BASE}/actor-runs/{run_id}", token)
        status = resp["data"]["status"]
        count = resp["data"].get("stats", {}).get("outputItemsCount", "?")
        print(f"  [{status}] {count} items so far…", flush=True)
        if status in terminal:
            return status
        time.sleep(POLL_INTERVAL)
    return "TIMED-OUT"


def download_dataset(dataset_id: str, token: str) -> list[dict]:
    url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}&limit=2000"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def dynamic_count_check(hours: int = 4) -> int:
    """WebFetch LinkedIn search pages to get current job count for the time window.

    Returns total count across all search URLs + 10% buffer, capped at 1000.
    Falls back to 650 if LinkedIn blocks the request.
    """
    import re
    tpr = hours * 3600
    search_urls = [
        f"https://in.linkedin.com/jobs/search?keywords=Software+Engineer&location=India&geoId=102713980&f_TPR=r{tpr}&f_JT=F&f_E=4%2C3",
        f"https://in.linkedin.com/jobs/search?keywords=Software+Development+Engineer&location=India&geoId=102713980&f_TPR=r{tpr}&f_JT=F&f_E=4%2C3",
        f"https://in.linkedin.com/jobs/search?keywords=MTS&location=India&geoId=102713980&f_TPR=r{tpr}&f_JT=F&f_E=3%2C4",
    ]
    total = 0
    for url in search_urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                text = r.read().decode("utf-8", "replace")
            # LinkedIn embeds count as: "123 Software Engineer jobs" or "1,234 jobs"
            m = re.search(r'"jobCount"\s*:\s*(\d+)', text)
            if not m:
                m = re.search(r'([\d,]+)\s+(?:Software\+?Engineer|Software\+?Development|MTS)\s+[Jj]obs?', text)
            if not m:
                m = re.search(r'([\d,]+)\s+[Jj]obs?\s+(?:in|for)', text)
            if m:
                n = int(m.group(1).replace(",", ""))
                print(f"  LinkedIn count for {url.split('keywords=')[1].split('&')[0]}: {n}")
                total += n
        except Exception as e:
            kw = url.split('keywords=')[1].split('&')[0].replace('+', ' ')
            print(f"  LinkedIn blocked ({kw}): {type(e).__name__} — will use safe minimum")
    # Safe minimums if LinkedIn blocks most requests
    safe_minimum = {4: 200, 24: 650}.get(hours, 200)
    if total < 50:
        print(f"  LinkedIn returned suspiciously low count ({total}) — using safe minimum {safe_minimum}")
        return safe_minimum
    count = min(int(total * 1.1), 1000)
    print(f"  Total LinkedIn count: {total} → Apify count set to: {count}")
    return count


def update_task_count(token: str, count: int, hours: int = 4) -> None:
    """Update the Apify task's count and URL time-filter to match the window."""
    import re as _re
    import json as _json
    tpr = hours * 3600
    task_data = _get(f"{APIFY_BASE}/actor-tasks/{TASK_ID}", token)
    current_input = task_data["data"].get("input", {})
    updated_urls = [
        _re.sub(r"f_TPR=r\d+", f"f_TPR=r{tpr}", url)
        for url in current_input.get("urls", [])
    ]
    updated_input = {**current_input, "count": count, "urls": updated_urls}
    body = _json.dumps({"input": updated_input}).encode()
    req = urllib.request.Request(
        f"{APIFY_BASE}/actor-tasks/{TASK_ID}?token={token}",
        data=body, method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    print(f"  Apify task updated: count={count}, f_TPR=r{tpr} ({hours}h window)")


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y-%m-%d_%Hh"))
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--hours", type=int, default=4,
                    help="Time window in hours for LinkedIn filter (default: 4, use 24 for full-day sweep)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Skip Apify fetch; read jobs_raw.json from --out-dir")
    args = ap.parse_args()

    run_dir = args.out_dir or os.path.join(_ROOT, "data", "pipeline", "runs", args.run_id)
    os.makedirs(run_dir, exist_ok=True)

    token = load_token()
    if not token:
        print("ERROR: APIFY_TOKEN not found", file=sys.stderr)
        sys.exit(1)

    # ── Stage 1: Fetch ────────────────────────────────────────────────────────
    raw_path = os.path.join(run_dir, "jobs_raw.json")
    if args.no_fetch and os.path.exists(raw_path):
        print("Skipping fetch — loading existing jobs_raw.json")
        with open(raw_path) as f:
            raw_items = json.load(f)
    else:
        # Dynamic count check — WebFetch LinkedIn to get real job count, update task
        print(f"Checking LinkedIn job counts ({args.hours}h window)…")
        live_count = dynamic_count_check(args.hours)
        update_task_count(token, live_count, args.hours)

        print(f"Starting Apify task {TASK_ID}…")
        run_id, dataset_id = run_apify_task(token)
        print(f"  Run: {run_id}  Dataset: {dataset_id}")
        status = wait_for_run(run_id, token)
        print(f"  Final status: {status}")
        if status != "SUCCEEDED":
            print(f"ERROR: Apify run ended with {status}", file=sys.stderr)
            sys.exit(1)
        raw_items = download_dataset(dataset_id, token)
        with open(raw_path, "w") as f:
            json.dump(raw_items, f, indent=2)
        print(f"  Fetched {len(raw_items)} raw items → {raw_path}")

    # ── Stage 2: Normalize ────────────────────────────────────────────────────
    jobs = [normalize(r) for r in raw_items if isinstance(r, dict)]

    # ── Stage 3: Pre-filter ───────────────────────────────────────────────────
    kept, dropped = filter_jobs(jobs)
    filtered_path = os.path.join(run_dir, "jobs_filtered.json")
    dropped_path = os.path.join(run_dir, "jobs_dropped.json")
    with open(filtered_path, "w") as f:
        json.dump(kept, f, indent=2)
    with open(dropped_path, "w") as f:
        json.dump(dropped, f, indent=2)
    print(f"  Pre-filter: {len(kept)} kept, {len(dropped)} dropped")

    # ── Stage 4: Dedup ────────────────────────────────────────────────────────
    new_jobs = dedup.filter_new(kept)
    dedup.mark_seen(kept, status="fetched")  # mark all kept as seen
    print(f"  Dedup: {len(new_jobs)} new (of {len(kept)} filtered)")

    # ── Stage 5: Write per-job JD files ──────────────────────────────────────
    jobs_dir = os.path.join(run_dir, "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    for j in new_jobs:
        jid = dedup.job_id(j).replace(":", "_").replace("/", "_")
        jdir = os.path.join(jobs_dir, jid)
        os.makedirs(jdir, exist_ok=True)
        jd_path = os.path.join(jdir, "jd.txt")
        with open(jd_path, "w") as f:
            f.write(f"{j.get('title','')} — {j.get('company','')}\n")
            f.write(f"Location: {j.get('location','')}\n")
            f.write(f"Seniority: {j.get('seniority','')}\n")
            f.write(f"Employees: {j.get('companyEmployeesCount','?')}\n")
            f.write(f"Apply: {j.get('url','')}\n")
            f.write(f"Posted: {j.get('posted','')}\n\n")
            f.write(j.get("description", ""))
        # store paths on the dict — written into jobs_new.json below
        j["_job_dir"] = os.path.abspath(jdir)
        j["_jd_path"] = os.path.abspath(jd_path)

    # ── Write jobs_new.json AFTER JD files so _job_dir/_jd_path are included ──
    new_path = os.path.join(run_dir, "jobs_new.json")
    with open(new_path, "w") as f:
        json.dump(new_jobs, f, indent=2)

    # ── Summary (last line = JSON for runner to parse) ────────────────────────
    summary = {
        "run_id": args.run_id,
        "run_dir": run_dir,
        "new_jobs_path": new_path,
        "total_fetched": len(raw_items),
        "filtered_out": len(dropped),
        "new_jobs": len(new_jobs),
    }
    print(f"\nSUMMARY: {json.dumps(summary)}")


if __name__ == "__main__":
    main()
