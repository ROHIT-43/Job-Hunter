#!/usr/bin/env python3
"""
apify_scrape.py — Pull structured job listings from an Apify actor and write
them, normalized, to a JSON file that scripts/score_jobs.py can consume.

This is the "results pulled in" route described in references/apify.md. Apify
hosts maintained actors that return structured job data from LinkedIn / Naukri /
Indeed without you running a scraper yourself. It is pay-per-result, so it runs
ONLY when you provide a token and a row cap.

TOKEN — never hardcode it
-------------------------
The Apify API token is read from the environment, NEVER from the command line
or source. Resolution order:

  1. APIFY_TOKEN environment variable
  2. a `.env` file (KEY=VALUE lines) in the current dir or repo root

Get a token at https://console.apify.com/account/integrations and either:

    export APIFY_TOKEN=apify_api_xxx          # shell
    # ── or ──
    cp .env.example .env && edit .env         # then APIFY_TOKEN=apify_api_xxx

`.env` is git-ignored, so the token never lands in the repo.

USAGE
-----
    python scripts/apify_scrape.py \
        --actor curious_coder/linkedin-jobs-scraper \
        --keywords "backend engineer python rust" \
        --location India --rows 50 \
        --out data/linkedin_export.json

    # Full control over the actor input (schemas vary per actor):
    python scripts/apify_scrape.py --actor memo23/naukri-scraper \
        --input-file data/actor_input.json --out data/naukri.json

Actor input field names differ between actors — start from the actor's input
schema on Apify. `--keywords/--location/--rows/--remote` build a generic input;
use `--input-file` when an actor needs different fields.
"""
import json, os, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import department  # noqa: E402

APIFY_BASE = "https://api.apify.com/v2"
DEFAULT_OUT = os.path.join("data", "linkedin_export.json")
# Sensible default actor; override with --actor (availability changes — verify).
DEFAULT_ACTOR = "curious_coder/linkedin-jobs-scraper"


def load_dotenv():
    """Load KEY=VALUE pairs from a `.env` in CWD or repo root into os.environ.

    Existing environment variables win; .env only fills the gaps.
    """
    here = os.getcwd()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (os.path.join(here, ".env"), os.path.join(repo_root, ".env")):
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        return path
    return None


def get_token():
    src = load_dotenv()
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        print("ERROR: no Apify token found.\n"
              "  Set APIFY_TOKEN in your environment, or copy .env.example to "
              ".env and fill it in.\n"
              "  Get a token at https://console.apify.com/account/integrations",
              file=sys.stderr)
        sys.exit(2)
    if src:
        print(f"Loaded token from {src}")
    return token


def flag(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def build_input(argv):
    """Build a generic actor input from flags, or load --input-file verbatim."""
    input_file = flag(argv, "--input-file")
    if input_file:
        with open(input_file) as fh:
            return json.load(fh)
    rows = int(flag(argv, "--rows", "50"))
    departments = flag(argv, "--departments",
                       ",".join(department.default_departments()))
    depts = [d.strip() for d in departments.split(",") if d.strip()]
    payload = {
        "location": flag(argv, "--location", ""),
        "rows": rows,
        "maxItems": rows,
        "jobFunction": department.facet_codes(depts, "linkedin"),
    }
    if "--remote" in argv:
        payload["remote"] = True
    return payload


def normalize(raw):
    """Map an Apify/LinkedIn row to the shared normalized job schema so it can
    be fed to score_jobs.py alongside fetch_jobs.py output."""
    return {
        "id": f"apify:{raw.get('id') or raw.get('jobUrl') or raw.get('url') or ''}",
        "source": "apify",
        "title": raw.get("jobTitle") or raw.get("title") or "",
        "company": raw.get("companyName") or raw.get("company") or "",
        "location": raw.get("location") or "",
        "remote": bool(raw.get("remote")) if "remote" in raw else None,
        "visa_sponsorship": None,
        "tags": raw.get("tags") or [],
        "salary": raw.get("salary"),
        "description": raw.get("description") or "",
        "url": raw.get("jobUrl") or raw.get("url") or "",
        "posted": (raw.get("publishedAt") or raw.get("published_at") or "")[:10] or None,
        "sector": raw.get("sector", ""),
    }


def run_actor(actor, token, actor_input, timeout):
    """Run an actor synchronously and return its dataset items (a list).

    Uses the run-sync-get-dataset-items endpoint, which runs the actor and
    streams back the dataset in one call. Actor id uses `~` in the API path.
    """
    actor_path = actor.replace("/", "~")
    url = (f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
           f"?token={token}")
    body = json.dumps(actor_input).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        print(f"ERROR: Apify returned HTTP {e.code}.\n  {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: could not reach Apify ({e.reason}). Network egress "
              f"must be enabled.", file=sys.stderr)
        sys.exit(1)


def main():
    argv = sys.argv
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        sys.exit(0)

    token = get_token()
    actor = flag(argv, "--actor", DEFAULT_ACTOR)
    out = flag(argv, "--out", DEFAULT_OUT)
    timeout = int(flag(argv, "--timeout", "600"))
    actor_input = build_input(argv)

    rows = actor_input.get("rows") or actor_input.get("maxItems") or "?"
    print(f"Running actor '{actor}' (cap ~{rows} rows)…")
    t0 = time.monotonic()
    items = run_actor(actor, token, actor_input, timeout)
    if not isinstance(items, list):
        items = [items]
    elapsed = time.monotonic() - t0

    # Normalize to the shared schema so score_jobs.py can read it directly.
    items = [normalize(it) if isinstance(it, dict) else it for it in items]

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w") as fh:
        json.dump(items, fh, indent=2)

    print(f"Pulled {len(items)} job records in {elapsed:.0f}s → {out}")
    if items:
        first = items[0]
        name = first.get("company") or "?" if isinstance(first, dict) else "?"
        title = first.get("title") or "?" if isinstance(first, dict) else "?"
        print(f"  e.g. {title} @ {name}")
    print(f"Next: python scripts/score_jobs.py {out} data/jobs.json "
          f"--profile data/profile.json")


if __name__ == "__main__":
    main()
