#!/usr/bin/env python3
"""
mark_applied.py — Scan APPLY_QUEUE.md (and BROWSER_QUEUE.md) for jobs the user
has ticked as applied (`- [x] Applied`), record them as status="applied" in
seen_jobs.json (so dedup permanently filters them out of future runs), and strike
them from the queue file.

Applied jobs are matched by LinkedIn job ID extracted from the Apply URL, so the
same posting can never resurface across runs even if its URL params differ.

Usage:
    python3 scripts/pipeline/mark_applied.py
    python3 scripts/pipeline/mark_applied.py --queue data/pipeline/BROWSER_QUEUE.md
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from pipeline import dedup  # noqa: E402

DEFAULT_QUEUES = [
    os.path.join(_ROOT, "data", "pipeline", "APPLY_QUEUE.md"),
    os.path.join(_ROOT, "data", "pipeline", "BROWSER_QUEUE.md"),
]

# LinkedIn job ID: 9-10+ digit run inside the apply URL
_JOBID_RE = re.compile(r"(\d{9,})")


def extract_job_id(url: str):
    """Pull the LinkedIn numeric job ID from an apply URL."""
    m = _JOBID_RE.search(url or "")
    return f"li:{m.group(1)}" if m else None


def parse_blocks(text):
    """Split the queue into (header, body) job blocks delimited by '### '.

    Returns a list of dicts: {raw, title, apply_url, job_id, applied}.
    """
    blocks = []
    # Each job block starts with '### [' and runs until the next '### ' or '---'
    parts = re.split(r"(?=^### )", text, flags=re.MULTILINE)
    for part in parts:
        if not part.startswith("### "):
            continue
        title_m = re.match(r"### (.+)", part)
        apply_m = re.search(r"\*\*Apply:\*\*\s*(\S+)", part)
        applied = bool(re.search(r"-\s*\[[xX]\]\s*Applied", part))
        url = apply_m.group(1) if apply_m else ""
        blocks.append({
            "raw": part,
            "title": title_m.group(1).strip() if title_m else "",
            "apply_url": url,
            "job_id": extract_job_id(url),
            "applied": applied,
        })
    return blocks


def process_queue(queue_path):
    if not os.path.exists(queue_path):
        return [], 0
    with open(queue_path) as f:
        text = f.read()

    blocks = parse_blocks(text)
    applied = [b for b in blocks if b["applied"] and b["job_id"]]

    if not applied:
        return [], len(blocks)

    # Record each applied job in the dedup store as status="applied"
    for b in applied:
        dedup.update_status(b["job_id"], "applied")
        # If the job was never in the store (e.g. browser-run job), add it
        store = dedup._load()
        if b["job_id"] not in store:
            store[b["job_id"]] = {
                "title": b["title"], "company": "", "status": "applied",
                "url": b["apply_url"], "first_seen": "",
            }
            dedup._save(store)

    # Strike applied blocks from the queue (replace block with a one-line tombstone)
    new_text = text
    for b in applied:
        tombstone = f"### ~~{b['title']}~~ ✅ APPLIED ({b['job_id']})\n\n"
        new_text = new_text.replace(b["raw"], tombstone)

    with open(queue_path, "w") as f:
        f.write(new_text)

    return applied, len(blocks)


def main():
    argv = sys.argv
    queues = DEFAULT_QUEUES
    if "--queue" in argv:
        queues = [argv[argv.index("--queue") + 1]]

    total_applied = 0
    for q in queues:
        applied, total = process_queue(q)
        name = os.path.basename(q)
        if not os.path.exists(q):
            continue
        print(f"{name}: {len(applied)} applied / {total} total blocks")
        for b in applied:
            print(f"  ✅ {b['job_id']}  {b['title'][:55]}")
        total_applied += len(applied)

    print(f"\nTotal marked applied (filtered from future runs): {total_applied}")
    print(f"Dedup store stats: {dedup.stats()}")


if __name__ == "__main__":
    main()
