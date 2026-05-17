#!/usr/bin/env python3
"""
search_urls.py — Build ready-to-click, pre-filtered search URLs for job portals.

Most Indian portals (Naukri, LinkedIn, Indeed, Foundit, CutShort, Apna, ...)
forbid automated scraping in their ToS and block bots. This does NOT scrape:
it generates deep links the user opens in a browser, with their keywords /
location / remote / freshness filters already applied. That is the ToS-safe
substitute for scraping these sites.

Portals are grouped by category so you only surface relevant ones:
  general    Naukri, LinkedIn, Indeed, Foundit, Shine, TimesJobs, Glassdoor,
             Google Jobs, NCS
  tech       CutShort, Instahyre, Wellfound, Hirist, Hirect
  remote     LinkedIn(remote), Wellfound(remote), Google Jobs(remote)
  freshers   Internshala, Freshersworld
  bluecollar Apna, WorkIndia
  freelance  Upwork

Confidence: links marked (landing) drop the user on the site's search page
because that portal's deep-link format is unstable or app-first — they type the
query once there. All others are fully pre-filled.

Example:
  python search_urls.py --keywords "backend engineer haskell rust" \
      --location "Bengaluru" --remote --since-days 7 \
      --category general,tech --out search_links.md
"""
import argparse
import urllib.parse


def enc(s, plus=True):
    return (urllib.parse.quote_plus if plus else urllib.parse.quote)(s or "")


def slug(s, n=None):
    parts = s.lower().split()
    if n:
        parts = parts[:n]
    return "-".join(parts)


# Each builder returns (url, is_landing)
def linkedin(kw, loc, remote, fresh):
    p = {"keywords": kw, "location": loc or "India"}
    if fresh:
        p["f_TPR"] = f"r{fresh * 86400}"   # r604800 = past week
    if remote:
        p["f_WT"] = "2"                      # 1 on-site, 2 remote, 3 hybrid
    return ("https://www.linkedin.com/jobs/search/?" +
            urllib.parse.urlencode(p, quote_via=urllib.parse.quote), False)


def naukri(kw, loc, remote, fresh):
    base = f"https://www.naukri.com/{slug(kw)}-jobs"
    if loc:
        base += "-in-" + slug(loc)
    params = {}
    if fresh:
        params["jobAge"] = min([1, 3, 7, 15, 30], key=lambda x: abs(x - fresh))
    if remote:
        params["wfhType"] = "2"
    return (base + ("?" + urllib.parse.urlencode(params) if params else ""),
            False)


def indeed(kw, loc, remote, fresh):
    p = {"q": kw + (" remote" if remote else ""), "l": loc or "India"}
    if fresh:
        p["fromage"] = fresh
    return "https://in.indeed.com/jobs?" + urllib.parse.urlencode(p), False


def foundit(kw, loc, remote, fresh):
    url = f"https://www.foundit.in/srp/results?query={enc(kw)}"
    if loc:
        url += f"&locations={enc(loc)}"
    if remote:
        url += "&workModes=remote"
    return url, False


def shine(kw, loc, remote, fresh):
    url = f"https://www.shine.com/job-search/{slug(kw)}-jobs"
    if loc:
        url += "-in-" + slug(loc)
    return url, False


def timesjobs(kw, loc, remote, fresh):
    p = {"searchType": "personalizedSearch", "from": "submit",
         "txtKeywords": kw}
    if loc:
        p["txtLocation"] = loc
    return ("https://www.timesjobs.com/candidate/job-search.html?" +
            urllib.parse.urlencode(p), False)


def glassdoor(kw, loc, remote, fresh):
    p = {"sc.keyword": kw}
    if loc:
        p["locKeyword"] = loc
    return ("https://www.glassdoor.co.in/Job/jobs.htm?" +
            urllib.parse.urlencode(p), False)


def google_jobs(kw, loc, remote, fresh):
    q = kw + (" remote" if remote else "") + (f" {loc}" if loc else " jobs")
    # ibp=htl;jobs opens the Google Jobs panel
    return (f"https://www.google.com/search?q={enc(q)}&ibp=htl;jobs", False)


def ncs(kw, loc, remote, fresh):
    # National Career Service (govt). Form-based; drop on the job-search page.
    return "https://www.ncs.gov.in/Pages/jobsearchlanding.aspx", True


def cutshort(kw, loc, remote, fresh):
    return f"https://cutshort.io/jobs/{slug(kw, 3)}-jobs", False


def instahyre(kw, loc, remote, fresh):
    p = {"job_functions": kw}
    if loc:
        p["city"] = loc
    return ("https://www.instahyre.com/search-jobs/?" +
            urllib.parse.urlencode(p), False)


def wellfound(kw, loc, remote, fresh):
    role = slug(kw, 3)
    if remote:
        return f"https://wellfound.com/role/l/{role}/remote", False
    return f"https://wellfound.com/role/r/{role}", False


def hirist(kw, loc, remote, fresh):
    return f"https://www.hirist.tech/search/{enc(kw)}-jobs", False


def hirect(kw, loc, remote, fresh):
    return "https://www.hirect.in/", True  # app-first chat hiring


def internshala(kw, loc, remote, fresh):
    return f"https://internshala.com/jobs/keywords-{slug(kw)}/", False


def freshersworld(kw, loc, remote, fresh):
    return (f"https://www.freshersworld.com/jobs/jobsearch/{slug(kw)}-jobs",
            False)


def apna(kw, loc, remote, fresh):
    return "https://apna.co/jobs", True  # app-first, hyper-local


def workindia(kw, loc, remote, fresh):
    return "https://www.workindia.in/", True  # category/city based


def upwork(kw, loc, remote, fresh):
    return f"https://www.upwork.com/nx/search/jobs/?q={enc(kw)}", False


CATEGORIES = {
    "general": [
        ("Naukri", naukri), ("LinkedIn", linkedin),
        ("Indeed (India)", indeed), ("Foundit (Monster)", foundit),
        ("Shine", shine), ("TimesJobs", timesjobs),
        ("Glassdoor", glassdoor), ("Google Jobs", google_jobs),
        ("NCS (govt)", ncs),
    ],
    "tech": [
        ("CutShort", cutshort), ("Instahyre", instahyre),
        ("Wellfound", wellfound), ("Hirist", hirist), ("Hirect", hirect),
    ],
    "remote": [
        ("LinkedIn (remote)", linkedin), ("Wellfound (remote)", wellfound),
        ("Google Jobs (remote)", google_jobs),
    ],
    "freshers": [
        ("Internshala", internshala), ("Freshersworld", freshersworld),
    ],
    "bluecollar": [
        ("Apna", apna), ("WorkIndia", workindia),
    ],
    "freelance": [
        ("Upwork", upwork),
    ],
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keywords", required=True,
                    help='free-text query, e.g. "backend engineer haskell"')
    ap.add_argument("--location", default="", help="e.g. Bengaluru, India")
    ap.add_argument("--remote", action="store_true")
    ap.add_argument("--since-days", type=int, default=0,
                    help="freshness filter where the portal supports it")
    ap.add_argument("--category", default="general,tech",
                    help="comma list from: " + ",".join(CATEGORIES) + ",all")
    ap.add_argument("--out", default="", help="write markdown to this file")
    args = ap.parse_args()

    cats = (list(CATEGORIES) if args.category == "all"
            else [c.strip() for c in args.category.split(",") if c.strip()])

    lines = ["# Pre-filtered job search links", ""]
    lines.append(f"**Query:** {args.keywords}  ")
    lines.append(f"**Location:** {args.location or 'any'}  ")
    lines.append(f"**Remote only:** {args.remote}  ")
    if args.since_days:
        lines.append(f"**Posted within:** {args.since_days} days  ")
    lines.append("")

    seen = set()
    for cat in cats:
        portals = CATEGORIES.get(cat)
        if not portals:
            lines.append(f"_(unknown category: {cat})_")
            continue
        lines.append(f"## {cat.capitalize()}")
        for name, fn in portals:
            if name in seen:
                continue
            seen.add(name)
            try:
                url, landing = fn(args.keywords, args.location, args.remote,
                                  args.since_days)
                tag = " _(landing — type the query there)_" if landing else ""
                lines.append(f"- **{name}:** {url}{tag}")
            except Exception as e:  # noqa: BLE401
                lines.append(f"- **{name}:** (could not build — {e})")
        lines.append("")

    lines.append("> Deep-link filter params (LinkedIn `f_WT`/`f_TPR`, Naukri "
                 "`jobAge`/`wfhType`) change occasionally. If a filter looks "
                 "off, adjust it once in the UI — the rest of the query still "
                 "applies. Links marked _(landing)_ are app-first or use an "
                 "unstable URL format, so they open the search page only.")

    text = "\n".join(lines)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
