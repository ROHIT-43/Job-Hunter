#!/usr/bin/env python3
"""posts.py — Hourly LinkedIn *post* hunt -> site/data/posts.json.

  python3 scripts/live/posts.py [--force] [--state FILE] [--out FILE] [--debug-dir DIR]

1. Search posts (logged in with a throwaway account's cookies, env LINKEDIN_LI_AT /
   LINKEDIN_JSESSIONID) for each keyword in live_config.json "posts", newest first,
   back to the previous run (+1h margin, at least window_hours, at most 24h).
2. Free regex prefilter, then Claude decides which are genuine hiring posts and
   extracts roles (YoE per role, location, how to apply).
3. The same filters as jobs (title_exclude, software_only, exclude_role_families,
   internships, employment types, yoe_max) apply to every extracted role.
4. Kept roles are published like jobs (24h rolling, deduped). If the cookie stops
   working, the run records it (the site shows a banner) and exits cleanly so the
   jobs part of the site keeps updating.
"""
import argparse
import re
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from live import claude_cli, li_posts, posts_ai, roles, salary, store, yoe  # noqa: E402
from live.run import detail_reason, load_config, role_reason  # noqa: E402
from pipeline.pre_filter import title_ok  # noqa: E402

DEFAULT_CONFIG = os.path.join(ROOT, "live_config.json")
DEFAULT_OUT = os.path.join(ROOT, "site", "data", "posts.json")


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def window_start(state, pcfg, now, keyword=None):
    """Back to the previous scrape + 1h, at least window_hours, at most max_age_hours.

    With `keyword`: back to when THAT keyword was last searched in full, so a keyword
    cut short by the time limit (or newly added) is caught up next run.
    """
    hours = float(pcfg.get("window_hours", 3))
    max_age = float(pcfg.get("max_age_hours", 24))
    last = state.get("last_scrape_at")
    if keyword is not None:
        kw_last = state.get("keyword_scraped_at", {}).get(keyword)
        if not kw_last and last:  # new keyword on a running site: fill the whole 24h
            return now - timedelta(hours=max_age)
        last = kw_last
    if last:
        hours = max(hours, (now - datetime.fromisoformat(last)).total_seconds() / 3600 + 1)
    return now - timedelta(hours=min(hours, max_age))


_INDIA_PLACES = (
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "mumbai", "navi mumbai",
    "delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad", "kochi",
    "cochin", "jaipur", "indore", "chandigarh", "coimbatore", "trivandrum", "thiruvananthapuram",
    "mysore", "mysuru", "nagpur", "bhubaneswar", "vadodara", "surat", "lucknow", "mangalore",
    "visakhapatnam", "vizag", "bhopal", "nashik", "goa", "mohali")


def wanted_places(pcfg):
    wanted = [c.lower() for c in pcfg.get("countries", ["India"])]
    return wanted + (list(_INDIA_PLACES) if "india" in wanted else [])


def in_country(rec, pcfg):
    """Keep jobs in a wanted country (named, or inferred by Claude from the company /
    poster), and posts with no location signal at all (shown as "location not stated").
    Jobs placed in another country are dropped.
    """
    place = f"{rec.get('country') or ''} {rec.get('location') or ''}".lower()
    if not place.strip():
        return True
    places = wanted_places(pcfg)
    return any(re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", place) for p in places)


def company_score(state, company, score):
    """One score per company across runs, so the same company always ranks the same."""
    if not company or company == "Via recruiter":
        return score
    scores = state.setdefault("company_scores", {})
    key = " ".join(company.lower().split())
    if key not in scores and score is not None:
        scores[key] = score
    return scores.get(key, score)


def role_entries(post, rec, cfg, pcfg, now, state=None):
    """Published entries for one genuine post — one per role that passes the filters."""
    out, why = [], []
    for i, r in enumerate(rec["roles"]):
        title = r["title"]
        if not title_ok(title, cfg.get("title_exclude"), cfg.get("title_keep"))[0]:
            why.append("title")
            continue
        reason = role_reason(title, cfg)
        if reason:
            why.append(reason)
            continue
        emp = {"full-time": "Full-time", "internship": "Internship", "contract": "Contract",
               "part-time": "Part-time"}.get(r["employment_type"] or "", "")
        if detail_reason({"employment_type": emp, "seniority": emp}, cfg):
            why.append("employment_type")
            continue
        ymin = r["yoe_min"]
        if ymin is None:
            ymin = yoe.parse_yoe("", title)
        section = yoe.classify(None if ymin is None else ymin, cfg.get("yoe_max", 2))
        if section == "too_senior":
            why.append("too_senior")
            continue
        listed = salary.parse_salary(post["text"])
        edges = tuple(cfg.get("salary_buckets_lpa", [10, 20]))
        company = rec["company"] or ("Via recruiter" if rec["via_recruiter"] else post["author"])
        score = rec.get("company_score")
        if state is not None and rec["company"]:
            score = company_score(state, rec["company"], score)
        snippet = " ".join(post["text"].split())
        out.append({
            "id": f"post-{post['id']}-{i}",
            "post_id": post["id"],
            "kind": "post",
            "title": title,
            "company": company,
            "location": rec["location"] or (rec["country"] or ""),
            "location_unclear": not (rec["location"] or rec["country"]),
            "location_inferred": bool(rec.get("country_inferred")),
            "company_score": score,
            "work_mode": rec["work_mode"],
            "url": post["url"],
            "apply_links": rec["apply_links"],
            "apply_emails": rec["apply_emails"] if pcfg.get("show_contact_email") else [],
            "has_email": bool(rec["apply_emails"]),
            "poster": {"name": post["author"], "headline": post["headline"],
                       "url": post["author_url"], "role": rec["poster_role"]},
            "via_recruiter": rec["via_recruiter"],
            "posted_at": post["posted_at"],
            "first_seen_at": now.isoformat(),
            "yoe_min": ymin,
            "section": section,
            "family": roles.family(title),
            "skills": r["skills"],
            "keywords": sorted(post.get("keywords", [])),
            "employment_type": emp,
            "salary": ({"source": "listed", "min_lpa": listed[0], "max_lpa": listed[1],
                        "bucket": salary.bucket(*listed, edges)} if listed
                       else {"source": "none", "reason": "post", "bucket": "none"}),
            "snippet": snippet[:500] + ("…" if len(snippet) > 500 else ""),
        })
    return out, why


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--state", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="debug: only the first N keywords")
    ap.add_argument("--debug-dir", default=None,
                    help="save the first raw search response per keyword (for checking the parser)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    pcfg = cfg.get("posts", {})
    if args.limit:
        pcfg["keywords"] = pcfg["keywords"][:args.limit]
    log = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731
    now = _now()
    start = time.monotonic()
    budget = pcfg.get("max_runtime_minutes", 30) * 60

    url = (cfg.get("site_url") or "").rstrip("/") + "/data/posts.json" if cfg.get("site_url") else None
    state = store.load(args.state or args.out, url=url)
    state.setdefault("pending", {})
    log(f"posts: previous state {len(state['jobs'])} roles (last scrape {state.get('last_scrape_at')})")

    stats = {"scraped": False}
    if not pcfg.get("enabled", True):
        state["status"] = {"ok": True, "message": "disabled in live_config.json"}
    else:
        try:
            stats = hunt(state, cfg, pcfg, now, start, budget, args, log)
            state["status"] = {"ok": True, "message": "", "at": now.isoformat()}
        except li_posts.AuthError as e:
            log(f"! LinkedIn login needed: {e}")
            state["status"] = {"ok": False, "message": "LinkedIn session expired — refresh the "
                               "LINKEDIN_LI_AT / LINKEDIN_JSESSIONID secrets", "at": now.isoformat()}
        except li_posts.SearchUnavailable as e:
            log(f"! post search unavailable: {e}")
            state["status"] = {"ok": False, "message": "LinkedIn post search changed — code update needed",
                               "at": now.isoformat()}
        except Exception as e:  # noqa: BLE001 — never lose the state over one bad run
            log(f"! posts run failed: {type(e).__name__}: {e}")
            state["status"] = {"ok": False, "message": f"last run failed ({type(e).__name__}) — will retry",
                               "at": now.isoformat()}

    expired = store.expire(state, pcfg.get("max_age_hours", 24), now)
    cutoff = now - timedelta(hours=pcfg.get("max_age_hours", 24))
    state["pending"] = {k: v for k, v in state["pending"].items()
                        if datetime.fromisoformat(v["posted_at"]) >= cutoff}
    # config filters also apply to roles kept from earlier runs
    state["jobs"] = [j for j in state["jobs"]
                     if title_ok(j["title"], cfg.get("title_exclude"), cfg.get("title_keep"))[0]
                     and not role_reason(j["title"], cfg)
                     and (j.get("yoe_min") is None or j["yoe_min"] <= cfg.get("yoe_max", 2))]
    scores = state.get("company_scores", {})
    if len(scores) > 5000:  # keep the file small: forget companies not on the site now
        live_cos = {" ".join((j.get("company") or "").lower().split()) for j in state["jobs"]}
        state["company_scores"] = {k: v for k, v in scores.items() if k in live_cos}
    state["generated_at"] = now.isoformat()
    state["stats"] = {**stats, "expired": expired, "total": len(state["jobs"]),
                      "pending_classification": len(state["pending"])}
    store.save(state, args.out)
    log(f"posts: wrote {len(state['jobs'])} roles -> {args.out}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("\n### LinkedIn posts\n\n| metric | value |\n|---|---|\n")
            for k, v in {**state["stats"], "status": state["status"].get("message") or "ok"}.items():
                f.write(f"| {k} | {v} |\n")


def hunt(state, cfg, pcfg, now, start, budget, args, log):
    if not args.force and state.get("last_scrape_at"):
        since_last = (now - datetime.fromisoformat(state["last_scrape_at"])).total_seconds()
        if since_last < cfg.get("interval_hours", 1) * 3600 - 300:
            log("posts: not due yet — skipping search")
            return {"scraped": False}

    session = li_posts.Session(os.environ.get("LINKEDIN_LI_AT", ""),
                               os.environ.get("LINKEDIN_JSESSIONID", ""),
                               delay=pcfg.get("request_delay_sec", 2.5))
    done = state.setdefault("keyword_scraped_at", {})
    for kw in list(done):
        if kw not in pcfg["keywords"]:
            del done[kw]
    # keywords searched longest ago first, so one cut short last run is not starved
    keywords = sorted(pcfg["keywords"], key=lambda k: done.get(k) or "")
    log(f"posts: searching {len(keywords)} keywords, default window since "
        f"{window_start(state, pcfg, now).isoformat()}")

    debug = {} if args.debug_dir else None
    found, coverage = {}, []
    search_deadline = start + 0.5 * budget
    for kw in keywords:
        since = window_start(state, pcfg, now, kw)
        try:
            got, pages, capped = li_posts.search(session, kw, since,
                                                 pcfg.get("max_pages_per_keyword", 40),
                                                 search_deadline, debug)
        except li_posts.Blocked as e:
            log(f"  ! throttled, stopping search: {e}")
            break
        new = 0
        for p in got:
            if p["id"] in found:
                found[p["id"]]["keywords"].add(kw)
            else:
                p["keywords"] = {kw}
                found[p["id"]] = p
                new += 1
        coverage.append({"keyword": kw, "found": len(got), "pages": pages, "capped": capped})
        if not (capped and time.monotonic() >= search_deadline):
            done[kw] = now.isoformat()  # searched in full (or as far as LinkedIn pages)
        log(f"  {kw!r:36} {len(got):4} in window {new:4} new {pages:3} pages"
            + ("  [page cap / time limit]" if capped else ""))
    if debug is not None:
        os.makedirs(args.debug_dir, exist_ok=True)
        for kw, body in debug.items():
            with open(os.path.join(args.debug_dir, kw.replace(" ", "_") + ".json"), "w") as f:
                f.write(body)
        log(f"  raw responses saved to {args.debug_dir}")

    known = {j["post_id"] for j in state["jobs"]} | set(state["skipped"])
    fresh = [p for p in found.values() if p["id"] not in known and p["id"] not in state["pending"]]
    prefiltered = 0
    for p in fresh:
        if posts_ai.prefilter(p["text"], wanted_places(pcfg)):
            state["pending"][p["id"]] = {**p, "keywords": sorted(p["keywords"])}
        else:
            prefiltered += 1
            state["skipped"][p["id"]] = p["posted_at"]
    log(f"posts: {len(found)} in window, {len(fresh)} new, {prefiltered} dropped by prefilter, "
        f"{len(state['pending'])} to check with Claude")

    stats = classify_pending(state, cfg, pcfg, now, start + budget, log)
    state["last_scrape_at"] = now.isoformat()
    return {"scraped": True, "requests": session.requests, "throttled": session.blocked_total,
            "in_window": len(found), "new": len(fresh), "prefiltered": prefiltered,
            "keywords": len(coverage), "capped_keywords": sum(c["capped"] for c in coverage),
            **stats}


def classify_pending(state, cfg, pcfg, now, deadline, log):
    ccfg = {"model": pcfg.get("model", "sonnet"), "timeout_sec": pcfg.get("timeout_sec", 240),
            "claude_bin": pcfg.get("claude_bin", "claude")}
    pending = sorted(state["pending"].values(), key=lambda p: p["posted_at"], reverse=True)
    batch = pcfg.get("batch_size", 10)
    batches = [pending[i:i + batch] for i in range(0, len(pending), batch)]
    genuine = added = 0
    dropped = {}
    index = store.known(state)

    def work(posts):
        if time.monotonic() + ccfg["timeout_sec"] > deadline:
            return posts, None, "time"
        try:
            return posts, posts_ai.classify(posts, ccfg), None
        except claude_cli.QuotaExceeded:
            return posts, None, "quota"
        except Exception as e:  # noqa: BLE001 — retry these posts next run
            return posts, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=pcfg.get("parallel_claude", 4)) as ex:
        for posts, results, err in ex.map(work, batches):
            if err:
                log(f"  batch of {len(posts)} left pending ({err})")
                continue
            for p in posts:
                rec = results.get(p["id"])
                if rec is None:
                    continue  # unanswered: stays pending
                del state["pending"][p["id"]]
                if not rec["genuine"] or not in_country(rec, pcfg):
                    dropped["not_genuine" if not rec["genuine"] else "country"] = \
                        dropped.get("not_genuine" if not rec["genuine"] else "country", 0) + 1
                    state["skipped"][p["id"]] = p["posted_at"]
                    continue
                genuine += 1
                entries, why = role_entries(p, rec, cfg, pcfg, now, state)
                for w in why:
                    dropped[w] = dropped.get(w, 0) + 1
                kept = [e for e in entries if store.add(state, e, index)]
                added += len(kept)
                if not kept:
                    state["skipped"][p["id"]] = p["posted_at"]
    log(f"posts: {genuine} genuine, {added} roles added, dropped {dropped}, "
        f"{len(state['pending'])} still pending")
    return {"genuine": genuine, "added": added, "dropped": dropped}


if __name__ == "__main__":
    main()
