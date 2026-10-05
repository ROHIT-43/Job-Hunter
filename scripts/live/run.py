#!/usr/bin/env python3
"""run.py — One hourly pass: LinkedIn (guest) -> 0-2 YoE filter -> salary -> site/data/jobs.json.

  python3 scripts/live/run.py                 # scrape (respects interval_hours) + publish
  python3 scripts/live/run.py --force         # scrape even if the last run was recent
  python3 scripts/live/run.py --no-scrape     # only expire old jobs and rewrite the file

Previous state comes from --state (local file) if it exists, else the published
site (<site_url>/data/jobs.json). The salary cache (--salary-cache) is persisted by
the workflow on the repo's `data` branch; lookups run only when CLAUDE_CODE_OAUTH_TOKEN
(or SALARY_LOOKUP_LOCAL=1, to use your local `claude` login) is set.
Knobs live in live_config.json at the repo root.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from live import linkedin, roles, salary, salary_lookup, store, yoe  # noqa: E402
from pipeline.pre_filter import title_ok     # noqa: E402

DEFAULT_CONFIG = os.path.join(ROOT, "live_config.json")
DEFAULT_OUT = os.path.join(ROOT, "site", "data", "jobs.json")
DEFAULT_SALARY_CACHE = os.path.join(ROOT, "data", "live", "salary_cache.json")
DEFAULT_OVERRIDES = os.path.join(ROOT, "salary_overrides.json")


def load_config(path):
    with open(path) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def due(state, interval_hours, now):
    last = state.get("last_scrape_at")
    if not last:
        return True
    # 5-minute slack so a slightly early cron tick still counts as due
    return now - datetime.fromisoformat(last) >= timedelta(hours=interval_hours, minutes=-5)


def search_window_hours(state, cfg, now):
    """How far back to search: at least window_hours, and always back past the last
    scrape (+1h margin) so runs GitHub delays or skips leave no gap. Capped at max_age."""
    hours = float(cfg["window_hours"])
    last = state.get("last_scrape_at")
    if last:
        since = (now - datetime.fromisoformat(last)).total_seconds() / 3600
        hours = max(hours, since + 1)
    return min(hours, float(cfg.get("max_age_hours", 24)))


def collect_cards(client, cfg, now, stop_at, log):
    """Search every keyword across `location`, re-splitting by city only when a search
    is cut off. Returns ({id: card}, per-search coverage, stopped_early?)."""
    window = int(cfg["window_hours"] * 3600)
    max_pages = cfg.get("max_pages_per_search", 100)
    cutoff = cfg.get("cutoff_results", 950)
    cards, coverage = {}, []

    def run(kw, loc):
        try:
            found, pages, capped = linkedin.search(
                client, kw, loc, window, cfg.get("experience_levels", ""),
                cfg.get("job_types", ""), max_pages, now, stop_at)
        except linkedin.Blocked:
            return kw, loc, [], 0, True
        # LinkedIn ends a capped search with empty pages, so "ran out of pages"
        # alone misses it; a result count near the cap means it was cut off too.
        return kw, loc, found, pages, capped or len(found) >= cutoff

    def sweep(tasks):
        capped_kws = set()
        with ThreadPoolExecutor(max_workers=cfg.get("search_workers", 2)) as ex:
            for kw, loc, found, pages, capped in ex.map(lambda t: run(*t), tasks):
                new = 0
                for c in found:
                    if c["id"] in cards:
                        cards[c["id"]]["keywords"].add(kw)
                    else:
                        c["keywords"] = {kw}
                        cards[c["id"]] = c
                        new += 1
                coverage.append({"keyword": kw, "location": loc, "found": len(found),
                                 "new": new, "pages": pages, "capped": capped})
                log(f"  {kw!r:28} {loc[:26]:26} {len(found):4} found {new:4} new {pages:3} pages"
                    + ("  [cut off]" if capped else ""))
                if capped:
                    capped_kws.add(kw)
        return capped_kws

    capped = sweep([(kw, cfg["location"]) for kw in cfg["keywords"]])
    if capped and not client.stopped and time.monotonic() < stop_at:
        log(f"re-splitting {len(capped)} cut-off keyword(s) by city: {sorted(capped)}")
        sweep([(kw, loc) for kw in cfg["keywords"] if kw in capped
               for loc in cfg.get("split_locations", [])])
    return cards, coverage, client.stopped or time.monotonic() >= stop_at


def listed_salary(texts, edges):
    """Salary stated in the posting (card, detail page or JD text), or None."""
    for text in texts:
        got = salary.parse_salary(text)
        if got:
            return {"source": "listed", "min_lpa": got[0], "max_lpa": got[1],
                    "bucket": salary.bucket(*got, edges)}
    return None


def role_reason(title, cfg):
    """Why a title is filtered out by role (config-driven), or None to keep it."""
    fam = roles.family(title)
    if cfg.get("software_only", True) and not fam:
        return "not_software"
    if fam and fam in cfg.get("exclude_role_families", []):
        return "excluded_role"
    if cfg.get("exclude_internships", True) and roles.is_internship(title):
        return "internship"
    return None


def detail_reason(job, cfg):
    """Why a fetched job is filtered out by LinkedIn's criteria, or None to keep it."""
    if cfg.get("exclude_internships", True) and roles.is_internship(
            "", job.get("seniority"), job.get("employment_type")):
        return "internship"
    excluded = {t.lower() for t in cfg.get("exclude_employment_types", [])}
    if (job.get("employment_type") or "").lower() in excluded:
        return "employment_type"
    return None


def build_job(card, detail, cfg, now):
    """Published record for one card + detail, or None if it asks for too much experience."""
    desc = detail.get("description", "")
    yoe_min = yoe.parse_yoe(desc, card["title"])
    section = yoe.classify(yoe_min, cfg.get("yoe_max", 2))
    if section == "too_senior":
        return None
    edges = tuple(cfg.get("salary_buckets_lpa", [10, 20]))
    snippet = " ".join(desc.split())
    return {
        "id": card["id"],
        "title": card["title"],
        "company": card["company"],
        "company_slug": card.get("company_slug", ""),
        "location": card["location"],
        "url": linkedin.job_url(card["id"]),
        "logo": card.get("logo", ""),
        "posted_at": card.get("posted_at") or now.isoformat(),
        "first_seen_at": now.isoformat(),
        "yoe_min": yoe_min,
        "section": section,
        "family": roles.family(card["title"]),
        "level": roles.level(card["title"]),
        "keywords": sorted(card["keywords"]),
        "seniority": detail.get("seniority", ""),
        "employment_type": detail.get("employment_type", ""),
        "applicants": detail.get("applicants", ""),
        "salary": listed_salary((card.get("salary_text"), detail.get("salary_text"), desc), edges)
                  or {"source": "none", "reason": "pending", "bucket": "none"},
        "snippet": snippet[:280] + ("…" if len(snippet) > 280 else ""),
    }


def apply_salaries(state, cfg, cache_path, overrides_path, now, log, deadline=None):
    """Feed listed salaries into the cache, run Claude web lookups, then (re)resolve every job."""
    lcfg = cfg.get("salary_lookup", {})
    edges = tuple(cfg.get("salary_buckets_lpa", [10, 20]))
    cache = salary_lookup.load_cache(cache_path)
    overrides = salary_lookup.load_overrides(overrides_path)
    pruned = salary_lookup.prune(cache, now)

    for j in state["jobs"]:
        if j["salary"].get("source") == "listed":
            key, _ = salary_lookup.job_key(j)
            salary_lookup.record_listed(cache, key, j["salary"]["min_lpa"],
                                        j["salary"]["max_lpa"], now, lcfg)

    logged_in = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("SALARY_LOOKUP_LOCAL")
    stats = {"lookups": 0, "lookups_found": 0}
    if logged_in and lcfg.get("enabled", True):
        stats = salary_lookup.run_lookups(state["jobs"], cache, overrides, lcfg, now, log,
                                          deadline=deadline)
    else:
        log("salary lookups: skipped (CLAUDE_CODE_OAUTH_TOKEN not set; "
            "locally set SALARY_LOOKUP_LOCAL=1 to use your own claude login)")

    for j in state["jobs"]:
        if j["salary"].get("source") != "listed":
            j["salary"] = salary_lookup.resolve(j, cache, overrides, edges)
    salary_lookup.save_cache(cache, cache_path)
    sources = Counter(j["salary"]["source"] for j in state["jobs"])
    log(f"salaries: {dict(sources)} (cache: {len(cache['entries'])} entries, {pruned} expired)")
    return {**stats, "salary_sources": dict(sources), "salary_cache_entries": len(cache["entries"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--state", default=None,
                    help="previous jobs.json to build on (default: --out if it exists, else the live site)")
    ap.add_argument("--force", action="store_true", help="scrape even if not due yet")
    ap.add_argument("--no-scrape", action="store_true", help="only expire + rewrite")
    ap.add_argument("--reset", action="store_true",
                    help="ignore the previous job list and start from scratch (salary cache is kept)")
    ap.add_argument("--salary-cache", default=DEFAULT_SALARY_CACHE,
                    help="salary lookup cache (the workflow keeps it on the `data` branch)")
    ap.add_argument("--overrides", default=DEFAULT_OVERRIDES)
    ap.add_argument("--limit", type=int, default=0,
                    help="debug: only the first N keywords (and N split cities)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.limit:
        cfg["keywords"] = cfg["keywords"][:args.limit]
        cfg["split_locations"] = cfg.get("split_locations", [])[:args.limit]
    log = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731
    now = _now()
    run_start = time.monotonic()

    state_url = (cfg.get("site_url") or "").rstrip("/") + "/data/jobs.json" if cfg.get("site_url") else None
    state = store.empty_state() if args.reset else store.load(args.state or args.out, url=state_url)
    if args.reset:
        log("reset: starting with an empty job list")
    log(f"previous state: {len(state['jobs'])} jobs (last scrape {state.get('last_scrape_at')})")

    stats = {"scraped": False}
    if not args.no_scrape and (args.force or due(state, cfg["interval_hours"], now)):
        client = linkedin.Client(cfg.get("request_delay_sec", 1.2),
                                 cfg.get("max_blocked_responses", 8))
        cfg["window_hours"] = round(search_window_hours(state, cfg, now), 2)
        budget = cfg.get("max_runtime_minutes", 50) * 60
        start = run_start
        log(f"searching {len(cfg['keywords'])} keywords in {cfg['location']}, "
            f"last {cfg['window_hours']}h…")
        cards, coverage, blocked = collect_cards(client, cfg, now, start + 0.45 * budget, log)

        ids, keys = store.known(state)
        dropped = Counter()
        todo = []
        for c in cards.values():
            if c["id"] in ids or store.repost_key(c) in keys:
                continue
            if not title_ok(c["title"], cfg.get("title_exclude"), cfg.get("title_keep"))[0]:
                dropped["title"] += 1
            elif role_reason(c["title"], cfg):
                dropped[role_reason(c["title"], cfg)] += 1
            else:
                todo.append(c)
                continue
            state["skipped"][c["id"]] = c.get("posted_at") or now.isoformat()
        log(f"{len(cards)} unique cards, {len(todo)} new to fetch, {dropped['title']} dropped by "
            f"title, {dropped['not_software']} not software roles, {dropped['excluded_role']} "
            f"excluded role types, {dropped['internship']} internships")

        added = too_senior = failed = 0
        index = (ids, keys)

        def fetch(card):
            if time.monotonic() >= start + 0.65 * budget:
                return card, None
            try:
                return card, linkedin.job_detail(client, card["id"])
            except linkedin.Blocked:
                return card, None

        log(f"fetching {len(todo)} job descriptions…")
        with ThreadPoolExecutor(max_workers=cfg.get("detail_workers", 3)) as ex:
            for n, (card, detail) in enumerate(ex.map(fetch, todo), 1):
                if n % 100 == 0 or n == len(todo):
                    log(f"  {n}/{len(todo)} fetched — {added} added so far "
                        f"({int(time.monotonic() - start) // 60} min elapsed)")
                if not detail:
                    failed += 1  # not recorded -> retried on the next run (if still in window)
                    continue
                job = build_job(card, detail, cfg, now)
                if job is None:
                    too_senior += 1
                elif detail_reason(job, cfg):
                    dropped[detail_reason(job, cfg)] += 1  # e.g. LinkedIn says Part-time/Internship
                    job = None
                elif store.add(state, job, index):
                    added += 1
                if job is None:
                    state["skipped"][card["id"]] = card.get("posted_at") or now.isoformat()
        log(f"added {added}, too senior {too_senior}, detail failed {failed}")

        state["last_scrape_at"] = now.isoformat()
        stats = {"scraped": True, "stopped_early": blocked,
                 "requests": client.requests, "blocked_responses": client.blocked_total,
                 "cards": len(cards), "new_fetched": len(todo), "added": added,
                 "too_senior": too_senior, "title_dropped": dropped["title"],
                 "not_software": dropped["not_software"], "excluded_role": dropped["excluded_role"],
                 "internships": dropped["internship"], "employment_type": dropped["employment_type"],
                 "detail_failed": failed, "searches": len(coverage),
                 "capped_searches": sum(c["capped"] for c in coverage)}
    else:
        log("not due yet — skipping scrape" if not args.no_scrape else "scrape disabled")

    expired = store.expire(state, cfg.get("max_age_hours", 24), now)
    # the filters also apply to jobs kept from earlier runs, so config edits take effect
    state["jobs"] = [j for j in state["jobs"]
                     if title_ok(j["title"], cfg.get("title_exclude"), cfg.get("title_keep"))[0]]
    state["jobs"] = [j for j in state["jobs"]
                     if not role_reason(j["title"], cfg) and not detail_reason(j, cfg)]
    # a minimum stated in the title ("AI Engineer || 7+ Yrs") also applies to kept jobs
    state["jobs"] = [j for j in state["jobs"]
                     if (yoe.parse_yoe("", j["title"]) or 0) <= cfg.get("yoe_max", 2)]

    try:
        stats.update(apply_salaries(state, cfg, args.salary_cache, args.overrides, now, log,
                                    deadline=run_start + cfg.get("max_runtime_minutes", 50) * 60))
    except Exception as e:  # noqa: BLE001 — salaries are best-effort; never block publishing jobs
        log(f"! salary step failed, publishing jobs without new salaries: {type(e).__name__}: {e}")
        stats["salary_error"] = f"{type(e).__name__}: {e}"
    state["generated_at"] = now.isoformat()
    state["config"] = {"window_hours": cfg["window_hours"], "max_age_hours": cfg.get("max_age_hours", 24),
                       "yoe_max": cfg.get("yoe_max", 2),
                       "salary_buckets_lpa": cfg.get("salary_buckets_lpa", [10, 20])}
    state["stats"] = {**stats, "expired": expired, "total": len(state["jobs"])}
    store.save(state, args.out)
    log(f"wrote {len(state['jobs'])} jobs -> {args.out} ({expired} expired)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("### Hourly jobs run\n\n| metric | value |\n|---|---|\n")
            for k, v in state["stats"].items():
                f.write(f"| {k} | {v} |\n")


if __name__ == "__main__":
    main()
