"""li_posts.py — Search LinkedIn *posts* (logged in) for hiring posts, newest first.

Uses the session of a throwaway LinkedIn account: cookies li_at + JSESSIONID
(env LINKEDIN_LI_AT / LINKEDIN_JSESSIONID). Post search is the endpoint the
linkedin.com "Posts" search tab pages through (server-driven UI, 2026): a POST that
answers with a React Server Components stream. parse_results() rebuilds each post
card from that stream (author, headline, full text, activity ID).

A post's activity ID encodes its creation time (ms = id >> 22), so the posting time
is exact and paging can stop precisely once results are older than the window.
"""
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.linkedin.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_ACTIVITY_RE = re.compile(r"urn:li:activity:(\d{15,22})")
_RETRY = {429, 999, 500, 502, 503, 504}


class AuthError(Exception):
    """Cookie missing/expired or the account is challenged — needs a fresh login."""


class Blocked(Exception):
    """LinkedIn kept throttling — stop for this run."""


class SearchUnavailable(Exception):
    """The search endpoint rejected the request shape (LinkedIn changed it)."""


def posted_at(activity_id):
    """Exact creation time encoded in a LinkedIn activity ID."""
    ms = int(activity_id) >> 22
    return datetime.fromtimestamp(ms / 1000, timezone.utc).replace(microsecond=0)


class Session:
    def __init__(self, li_at, jsessionid, delay=2.5, max_blocked=6, timeout=60, debug_dir=None):
        if not li_at or not jsessionid:
            raise AuthError("LINKEDIN_LI_AT / LINKEDIN_JSESSIONID not set")
        self.csrf = jsessionid.strip().strip('"')
        self.cookie = f'li_at={li_at.strip()}; JSESSIONID="{self.csrf}"'
        self.delay, self.max_blocked, self.timeout = delay, max_blocked, timeout
        self.debug_dir = debug_dir
        self.requests = self.blocked_total = 0
        self._streak = 0

    def _headers(self, api):
        h = {"User-Agent": UA, "Cookie": self.cookie, "Accept-Language": "en-US,en;q=0.9"}
        if api == "sdui":
            h.update({"csrf-token": self.csrf, "content-type": "application/json", "accept": "*/*",
                      "origin": BASE, "x-li-rsc-stream": "true",
                      "x-li-anchor-page-key": "d_flagship3_search_srp_content",
                      "referer": f"{BASE}/search/results/content/"})
            return h
        if api:
            h.update({"csrf-token": self.csrf, "x-restli-protocol-version": "2.0.0",
                      "x-li-lang": "en_US",
                      "Accept": "application/vnd.linkedin.normalized+json+2.1"})
        return h

    def get(self, url, api=True, data=None):
        for attempt in range(4):
            time.sleep(self.delay * random.uniform(0.7, 1.4))
            self.requests += 1
            req = urllib.request.Request(url, headers=self._headers(api), data=data,
                                         method="POST" if data is not None else "GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    final = r.geturl()
                    body = r.read().decode("utf-8", "replace")
                if any(p in final for p in ("/login", "/authwall", "/checkpoint", "/uas/")):
                    raise AuthError(f"redirected to {final.split('?')[0]} — log in again")
                self._streak = 0
                return body
            except urllib.error.HTTPError as e:
                if e.code in (401, 403) or (e.code == 302 and "login" in str(e.headers.get("Location", ""))):
                    raise AuthError(f"HTTP {e.code} — session cookie rejected") from e
                if e.code in (400, 404):
                    raise SearchUnavailable(f"HTTP {e.code} for {url[:120]}") from e
                if e.code not in _RETRY:
                    raise
            except OSError:  # URLError, socket timeouts (Python 3.9 included), resets
                pass
            self.blocked_total += 1
            self._streak += 1
            if self._streak >= self.max_blocked:
                raise Blocked(f"{self._streak} throttled responses in a row")
            time.sleep((5, 20, 60)[min(attempt, 2)])
        raise Blocked("gave up after retries")


# ── search request (LinkedIn's server-driven UI "pagination" action) ──────────
# LinkedIn retired the voyager GraphQL post search in 2026; the Posts tab now pages
# through this endpoint and answers with a React Server Components stream.
SEARCH_URL = f"{BASE}/flagship-web/rsc-action/actions/pagination?sduiid=com.linkedin.sdui.search.contentSearchResults"
PAGE_SIZE = 25  # the site asks for 3; 25 per request is accepted and far fewer requests


def search_body(keyword, start, search_id, count=PAGE_SIZE):
    payload = {"startIndex": start, "keywords": keyword, "count": count, "sortBy": ["date_posted"],
               "postedBy": [], "datePosted": [], "contentType": [], "fromMember": [],
               "mentionsOrganization": [], "mentionsMember": [], "fromOrganization": [],
               "authorCompany": [], "authorIndustry": [], "authorJobTitle": [],
               "spellCheckEnabled": True, "clusterStartPosition": 0, "searchId": search_id}
    args = {"$type": "proto.sdui.actions.requests.RequestedArguments", "requestedStateKeys": [],
            "payload": payload, "requestMetadata": {"$type": "proto.sdui.common.RequestMetadata"}}
    return json.dumps({
        "pagerId": "com.linkedin.sdui.search.contentSearchResults",
        "clientArguments": {**args, "states": [],
                            "screenId": "com.linkedin.sdui.flagshipnav.search.SearchResultsContent",
                            "knownTemplateIds": []},
        "paginationRequest": {
            "$type": "proto.sdui.actions.requests.PaginationRequest",
            "pagerId": "com.linkedin.sdui.search.contentSearchResults",
            "trigger": {"$case": "itemDistanceTrigger", "itemDistanceTrigger": {
                "$type": "proto.sdui.actions.requests.ItemDistanceTrigger",
                "preloadDistance": 3, "preloadLength": 1500}},
            "retryCount": 2, "requestedArguments": args},
    }).encode()


# ── parsing the React Server Components stream ───────────────────────────────
_REF = re.compile(r"^\$[L@]?([0-9a-f]+)$")
_ROW = re.compile(r"^([0-9a-f]+):(.*)$", re.S)


def _rows(text):
    """Stream lines `id:json` -> {id: value} (module/import rows are skipped)."""
    rows = {}
    for line in (text or "").split("\n"):
        m = _ROW.match(line)
        if m and m.group(2)[:1] in '[{"':
            try:
                rows[m.group(1)] = json.loads(m.group(2))
            except ValueError:
                pass
    return rows


def _deref(x, rows, seen):
    while isinstance(x, str):
        m = _REF.match(x)
        if not m or m.group(1) not in rows or m.group(1) in seen:
            break
        seen.add(m.group(1))
        x = rows[m.group(1)]
    return x


def _view(node, rows, seen):
    vts = _deref(node.get("viewTrackingSpecs"), rows, seen) if isinstance(node, dict) else None
    return vts.get("viewName") if isinstance(vts, dict) else None


def _texts(node, rows, seen, views, out):
    """Displayed text of a subtree as [(text, views)], following row references."""
    node = _deref(node, rows, seen)
    if isinstance(node, str):
        if not node.startswith("$"):
            out.append((node, views))
    elif isinstance(node, list):
        if len(node) == 4 and node[0] == "$" and isinstance(node[1], str):  # React element
            if node[1] == "br":
                out.append(("\n", views))
                return
            props = _deref(node[3], rows, seen)
            if isinstance(props, dict):
                v = _view(props, rows, seen)
                views2 = views + ((v,) if v else ())
                for key in ("children", "textProps"):
                    if key in props:
                        _texts(props[key], rows, seen, views2, out)
            return
        for x in node:
            _texts(x, rows, seen, views, out)
    elif isinstance(node, dict):
        v = _view(node, rows, seen)
        views2 = views + ((v,) if v else ())
        for key in ("children", "textProps"):
            if key in node:
                _texts(node[key], rows, seen, views2, out)


def _cards(node, out):
    if isinstance(node, dict):
        if str(node.get("componentKey", "")).startswith("update-card-"):
            out.append(node)
            return
        for x in node.values():
            _cards(x, out)
    elif isinstance(node, list):
        for x in node:
            _cards(x, out)


def _closure(node, rows):
    """JSON text of a card plus every row it references (for IDs / profile links)."""
    seen, stack, parts = set(), [node], []
    while stack:
        x = stack.pop()
        raw = json.dumps(x)
        parts.append(raw)
        for rid in re.findall(r'"\$[L@]?([0-9a-f]+)"', raw):
            if rid in rows and rid not in seen:
                seen.add(rid)
                stack.append(rows[rid])
    return "".join(parts)


def parse_results(payload):
    """Posts in one search response: [{id, text, author, headline, author_url, url, posted_at}]."""
    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    rows = _rows(payload)
    cards = []
    for val in rows.values():
        _cards(val, cards)
    posts, seen_ids = [], set()
    for card in cards:
        blob = _closure(card, rows)
        m = _ACTIVITY_RE.search(blob)
        if not m or m.group(1) in seen_ids:
            continue
        aid = m.group(1)
        seen_ids.add(aid)
        out = []
        _texts(card, rows, set(), (), out)
        body = "".join(t for t, v in out if "feed-commentary" in v).strip()
        if not body:  # link-only post: use the shared article's title/link
            body = " ".join(t for t, v in out if "feed-article" in v and t.strip()).strip()
        actor = [t.strip() for t, v in out if v and v[-1] == "feed-actor" and t.strip()]
        header = [t.strip() for t, v in out if v and v[-1] == "feed-full-update"
                  and t.strip() and t.strip() not in ("Feed post", "•")]
        prof = re.search(r'https://www\.linkedin\.com/(?:in|company)/[^"?\\/]+', blob)
        posts.append({
            "id": aid,
            "text": re.sub(r"\n{3,}", "\n\n", body),
            "author": actor[0] if actor else "",
            "headline": header[0] if header else "",
            "author_url": prof.group(0) if prof else "",
            "url": f"{BASE}/feed/update/urn:li:activity:{aid}/",
            "posted_at": posted_at(aid).isoformat(),
        })
    return posts


def search(session, keyword, since, max_pages=40, stop_at=None, debug=None):
    """Every post for `keyword` posted at/after `since` (datetime), newest first.

    Pages (PAGE_SIZE per request) until two pages in a row bring nothing inside the
    window — results are date-sorted, but not strictly, so one stale page isn't
    trusted as the end. Returns (posts, pages, hit_cap).
    """
    import uuid
    search_id = str(uuid.uuid4())
    out, seen, stale_pages = [], set(), 0
    for page in range(max_pages):
        if stop_at and time.monotonic() >= stop_at:
            return out, page, True
        body = session.get(SEARCH_URL, api="sdui",
                           data=search_body(keyword, page * PAGE_SIZE, search_id))
        if debug is not None and page == 0:
            debug[keyword] = body
        results = [p for p in parse_results(body) if p["id"] not in seen]
        if not results:
            return out, page + 1, False
        seen.update(p["id"] for p in results)
        fresh = [p for p in results if datetime.fromisoformat(p["posted_at"]) >= since]
        out += fresh
        stale_pages = 0 if fresh else stale_pages + 1
        if stale_pages >= 2:
            return out, page + 1, False
    return out, max_pages, True
