#!/usr/bin/env python3
"""
fetch_apify_results.py — Download, normalize, and merge two Apify LinkedIn
datasets (SWE + MTS) into a single jobs JSON file ready for score_jobs.py.

Usage:
    python scripts/fetch_apify_results.py \
        --swe-dataset OH1HdybjHtarGv6vY \
        --mts-dataset sOsbh1pMAhj24PNQr \
        --out data/output/batch400/jobs_raw.json
"""
import json, os, sys, urllib.request

APIFY_BASE = "https://api.apify.com/v2"


def load_token():
    for path in (".env", os.path.join(os.path.dirname(__file__), "..", ".env")):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("APIFY_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("APIFY_TOKEN", "")


def fetch_dataset(dataset_id, token, limit=2000):
    url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}&limit={limit}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def normalize(raw, source_tag="linkedin"):
    desc = raw.get("descriptionText") or raw.get("description") or ""
    return {
        "id": f"apify:{raw.get('id') or raw.get('refId') or raw.get('link', '')[-20:]}",
        "source": source_tag,
        "title": raw.get("title") or raw.get("jobTitle") or "",
        "company": raw.get("companyName") or raw.get("company") or "",
        "location": raw.get("location") or "",
        "remote": raw.get("workRemoteAllowed"),
        "visa_sponsorship": None,
        "tags": raw.get("jobFunction") or [],
        "salary": raw.get("salary"),
        "description": desc,
        "url": raw.get("link") or raw.get("applyUrl") or "",
        "posted": (raw.get("postedAt") or "")[:10] or None,
        "seniority": raw.get("seniorityLevel") or "",
        "employment_type": raw.get("employmentType") or "",
        "sector": (raw.get("industries") or [""])[0] if isinstance(raw.get("industries"), list) else "",
    }


def main():
    argv = sys.argv
    def flag(name, default=None):
        return argv[argv.index(name)+1] if name in argv and argv.index(name)+1 < len(argv) else default

    token = load_token()
    if not token:
        print("ERROR: APIFY_TOKEN not found", file=sys.stderr); sys.exit(1)

    swe_ds = flag("--swe-dataset", "OH1HdybjHtarGv6vY")
    mts_ds = flag("--mts-dataset", "sOsbh1pMAhj24PNQr")
    out = flag("--out", "data/output/batch400/jobs_raw.json")
    limit = int(flag("--limit", "2000"))

    all_jobs = []
    seen_ids = set()

    for ds_id, tag in [(swe_ds, "linkedin-swe"), (mts_ds, "linkedin-mts")]:
        print(f"Fetching dataset {ds_id} ({tag})…")
        items = fetch_dataset(ds_id, token, limit)
        print(f"  → {len(items)} raw items")
        for raw in items:
            job = normalize(raw, tag)
            # Dedup on URL
            key = job["url"] or job["id"]
            if key and key not in seen_ids:
                seen_ids.add(key)
                all_jobs.append(job)

    print(f"Total unique jobs: {len(all_jobs)}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump(all_jobs, f, indent=2)
    print(f"Written → {out}")
    print(f"Next: python scripts/score_jobs.py {out} --profile data/profile.json")


if __name__ == "__main__":
    main()
