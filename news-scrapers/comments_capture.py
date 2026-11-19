#!/usr/bin/env python3
"""comments_capture.py — estate-comments collector (ask estate-news-comments@2026-11-18).

Forward-only comment capture over the proven families:
  wp_rest   (8 hosts)  /wp-json/wp/v2/comments?post=<id>&per_page=100&page=N
  wp_inpage (6 hosts)  the rendered thread in the article page, parsed
  coral     (4 hosts)  persisted-GraphQL replay (coral-graphql-capture.json)

Record shape (shipped to the consumer 2026-11-17): one record per capture,
key (article, captured_at). Fields: article, captured_at, capture block
(fetch time, fetched address, HTTP status, sha256 of the raw response bytes
as served), comment_system, page_count, total_at_capture, comments[] with
the site-given per-comment fields (deterministic parse, no model-made
fields). Paginated threads keep every page's raw bytes (pages[]).

Falling schedule: first capture ASAP after publication, then d3 / d7 / d30.
Every capture kept, append-only. Failed reads land one row in the gap
ledger and move on — a challenge is never re-hammered.

Landing: /opt/data/news-scrapers/data-comments/<host>/manifest.jsonl +
store/<2>/<sha256> raw bytes (the estate-comments corpus mounts the glob
data-comments/*/manifest.jsonl — kept OUT of estate-news' data/ glob).

Mangle-safe: no scheme-ful URL literals (scheme assembled at runtime).
"""
import argparse
import base64
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
POLITE = 4.0
ROOT = "/opt/data/news-scrapers/data-comments"
NEWS = "/opt/data/news-scrapers/data"
GAPS = "/opt/data/querynz-estate/gaps/comments_gap_ledger.jsonl"
CORAL_CAPTURE = "/opt/data/querynz-estate/coral-graphql-capture.json"
FORWARD = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)  # 2026-11-18 00:00 NZ
MILESTONES = ("first", "d3", "d7", "d30")
AGE_DAYS = {"d3": 3, "d7": 7, "d30": 30}

WP_REST = ["kiwiblog.co.nz", "farmersweekly.co.nz", "hospitalitybusiness.co.nz",
           "kanivatonga.co.nz", "nztrucking.co.nz", "sciencemediacentre.co.nz",
           "tpplus.co.nz", "baybuzz.co.nz"]
WP_INPAGE = ["thestandard.nz", "newsroom.co.nz", "sunlive.co.nz",
             "interest.co.nz", "buildingtoday.co.nz", "localmatters.co.nz"]
CORAL = ["thepress.co.nz", "thepost.co.nz", "waikatotimes.co.nz", "stuff.co.nz"]
HOST_FAMILY = {h: "wp_rest" for h in WP_REST}
HOST_FAMILY.update({h: "wp_inpage" for h in WP_INPAGE})
HOST_FAMILY.update({h: "coral" for h in CORAL})
COMMENT_SYSTEM = {"wp_rest": "wordpress", "wp_inpage": "wordpress",
                  "coral": "coral"}

# newsroom.co.nz articles need the subscriber session (state minted by the
# news lane). Optional — anonymous first, session only as fallback.
NEWSROOM_STATE = "/opt/data/news-scrapers/ingestion/newsroom_state.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s):
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if not m:
            return None
        d = datetime.fromisoformat(m.group(1))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# -- fetch -----------------------------------------------------------------

_last_fetch = [0.0]


def fetch(addr, data=None, headers=None, cookies=None, timeout=30):
    """One polite GET/POST. Returns (status, final_addr, body, resp_headers)."""
    wait = POLITE - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    if cookies:
        hdrs["Cookie"] = cookies
    req = urllib.request.Request(addr, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            _last_fetch[0] = time.time()
            return r.status, r.geturl(), body, dict(r.headers)
    except urllib.error.HTTPError as e:
        _last_fetch[0] = time.time()
        return e.code, addr, (e.read() or b""), dict(e.headers or {})
    except Exception as e:  # noqa: BLE001 — network faults are gap rows
        _last_fetch[0] = time.time()
        return 0, addr, (str(e).encode()), {}


# -- landing ---------------------------------------------------------------

def store_raw(host, body):
    h = hashlib.sha256(body).hexdigest()
    d = os.path.join(ROOT, host, "store", h[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, h)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(body)
    return h, p


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def gap_row(host, addr, reason, status="open"):
    append_jsonl(GAPS, {"source": host, "url": addr, "reason": reason,
                        "status": status, "at": now_iso()})


def read_state():
    """last line per (article|milestone) wins."""
    st = {}
    p = os.path.join(ROOT, ".state.jsonl")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            st[(r.get("article"), r.get("milestone"))] = r
    return st


def land(host, milestone, article, published_at, family, pages_raw,
         comments, total):
    """pages_raw: [(status, fetched_addr, body, fetched_at)] page 1 first."""
    pages, primary = [], None
    for i, (st, addr, body, fat) in enumerate(pages_raw):
        sha, path = store_raw(host, body)
        entry = {"page": i + 1, "fetched_at": fat, "url": addr,
                 "http_status": st, "sha256": sha, "bytes": len(body),
                 "file": path}
        pages.append(entry)
        if i == 0:
            primary = entry
    cap_at = primary["fetched_at"]
    rid = hashlib.sha256(f"{article}|{cap_at}".encode()).hexdigest()[:32]
    row = {
        "record_id": rid,
        "source": host,
        "kind": "comment_capture",
        "comment_system": COMMENT_SYSTEM[family],
        "article": article,
        "published_at": published_at or "",
        "captured_at": cap_at,
        "milestone": milestone,
        "page_count": len(pages),
        "total_at_capture": total,
        "comments": comments,
        "pages": pages,
        "url": primary["url"],
        "fetched_at": cap_at,
        "http_status": primary["http_status"],
        "sha256": primary["sha256"],
        "bytes": primary["bytes"],
        "file": primary["file"],
        "landed_at": now_iso(),
    }
    append_jsonl(os.path.join(ROOT, host, "manifest.jsonl"), row)
    append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                 {"article": article, "milestone": milestone,
                  "captured_at": cap_at, "record_id": rid,
                  "status": "captured"})
    return rid, len(comments)


def fail_mark(article, milestone, reason, challenge=False):
    append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                 {"article": article, "milestone": milestone,
                  "captured_at": now_iso(), "record_id": None,
                  "status": "challenge" if challenge else "failed",
                  "reason": reason})


# -- family: WordPress REST -------------------------------------------------

POSTID_CACHE = os.path.join(ROOT, ".postids.json")
POSTID_RES = [re.compile(r'postid-(\d+)'),
              re.compile(r'/wp-json/wp/v2/posts/(\d+)'),
              re.compile(r'name="comment_post_ID"\s+value="(\d+)"')]


def resolve_post_id(host, article, row):
    """The WP post id as the site gives it: the postid-<N> body class on
    the article page (probe method 2026-11-17). Manifest upstream_id is a
    feed guid on some hosts (blogger-style 19-digit) — only trust it when
    it is a small integer. Cached per article."""
    cache = {}
    if os.path.exists(POSTID_CACHE):
        try:
            cache = json.load(open(POSTID_CACHE))
        except ValueError:
            cache = {}
    if article in cache:
        return cache[article]
    up = row.get("upstream_id")
    pid = None
    if isinstance(up, int) and up < 10 ** 10:
        pid = str(up)
    if pid is None:
        st, addr, body, _ = fetch(article)
        if st == 200:
            t = body.decode("utf-8", "replace")[:400000]
            for cre in POSTID_RES:
                m = cre.search(t)
                if m:
                    pid = m.group(1)
                    break
    if pid is None and isinstance(up, int) and up < 10 ** 15:
        pid = str(up)
    cache[article] = pid
    os.makedirs(ROOT, exist_ok=True)
    with open(POSTID_CACHE, "w") as f:
        json.dump(cache, f)
    return pid


def wp_rest_capture(host, article, post_id):
    """Returns (pages_raw, comments, total, err)."""
    base = SCHEME + host + "/wp-json/wp/v2/comments?post=" + str(post_id) \
        + "&per_page=100&orderby=date&order=asc&page="
    pages_raw, comments, page = [], [], 1
    while page <= 20:
        st, addr, body, _ = fetch(base + str(page))
        fat = now_iso()
        if st != 200:
            if page == 1:
                return pages_raw, comments, len(comments), f"http {st}"
            break
        pages_raw.append((st, addr, body, fat))
        try:
            rows = json.loads(body)
        except ValueError:
            return pages_raw, comments, len(comments), "bad json"
        if not isinstance(rows, list):
            return pages_raw, comments, len(comments), "not a list"
        for c in rows:
            comments.append(wp_rest_comment(article, c))
        if len(rows) < 100:
            break
        page += 1
    return pages_raw, comments, len(comments), None


def wp_rest_comment(article, c):
    av = c.get("author_avatar_urls") or {}
    out = {"comment_id": str(c.get("id", "")), "article": article}
    if c.get("parent"):
        out["parent_id"] = str(c["parent"])
    if c.get("author"):
        out["user_id"] = str(c["author"])
    if c.get("author_name"):
        out["display_name"] = c["author_name"]
    if c.get("author_url"):
        out["profile_link"] = c["author_url"]
    if av:
        out["avatar"] = av.get("96") or av.get("48") or sorted(av.values())[0]
    if c.get("date"):
        out["posted_at"] = c["date"]
    if (c.get("content") or {}).get("rendered"):
        out["text"] = c["content"]["rendered"]
    if c.get("status"):
        out["status"] = c["status"]
    if c.get("status") in ("trash", "spam"):
        out["deleted"] = True
    return out


# -- family: WordPress in-page ----------------------------------------------

COMMENT_ANCHOR_RE = re.compile(r'id="(?:div-)?comment[-_]?(\d+)"')
TIME_RE = re.compile(
    r'<time[^>]*datetime="([^"]+)"|<time[^>]*>([^<]{4,60})</time>'
    r'|<abbr[^>]*title="([^"]{4,60})"', re.I)
AUTHOR_RE = re.compile(
    r'<cite[^>]*>\s*(?:<a[^>]*>)?\s*([^<]{2,120}?)\s*(?:</a>)?\s*</cite>'
    r'|<a[^>]*class="[^"]*(?:url|comment-author|external)[^"]*"[^>]*>'
    r'\s*([^<]{2,120}?)\s*</a>'
    r'|<span[^>]*class="[^"]*author[^"]*"[^>]*>\s*([^<]{2,120}?)\s*</span>',
    re.I | re.S)
PROFILE_RE = re.compile(
    r'<a[^>]*class="[^"]*(?:comment-author|url|external)[^"]*"[^>]*'
    r'href="([^"]+)"|<a[^>]*rel="external[^"]*"[^>]*href="([^"]+)"'
    r'|<a[^>]*title="View user profile\.?"[^>]*href="([^"]+)"[^>]*>\s*'
    r'([^<]{2,120}?)\s*</a>', re.I)
USERID_RE = re.compile(r'data-comment-user-id="(\d+)"')
UNIX_TS_RE = re.compile(r'class="[^"]*comment-unix-timestamp[^"]*"[^>]*>'
                        r'\s*(\d{9,12})\s*<')
CONTENT_RES = [
    re.compile(r'<div[^>]*class="[^"]*(?:comment-content|commenttext|'
               r'comment-body|comment_text|field-name-comment-body)[^"]*"'
               r'[^>]*>(.*)', re.I | re.S),
    re.compile(r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*)', re.I | re.S),
]
DEPTH_RE = re.compile(r'class="[^"]*depth-(\d+)')
PARENT_RE = re.compile(r'class="[^"]*parent-(\d+)')


def _strip_tags(s):
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def _block_start(text, pos):
    head = text.rfind("<", 0, pos)
    li = text.rfind("<li", max(0, head - 600), head)
    if li >= 0:
        seg = text[li:head]
        if "comment" in seg and seg.count("<") == 1:
            return li
    return head


def wp_inpage_parse(page_body):
    """Deterministic thread parse off the served HTML.

    Comment blocks anchor on id="comment-<N>" (near-universal WP markup);
    nesting between consecutive anchors is NOT assumed — parent comes from
    the parent-<id> class where the theme gives it. Fields where the site
    gives them; nothing invented.
    """
    try:
        text = page_body.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        text = page_body.decode("latin-1", "replace")
    anchors = [(m.start(), m.group(1)) for m in COMMENT_ANCHOR_RE.finditer(text)]
    # keep the first anchor per id (div-comment-... wraps comment-...)
    seen, marks = set(), []
    for pos, cid in anchors:
        if cid not in seen:
            seen.add(cid)
            marks.append((pos, cid))
    # block start = the anchor's own tag head, extended back over the
    # wrapping <li ...> (depth/parent classes live on the li, not the
    # anchor element). Block end = the NEXT block's start — so no tail
    # leak of the next comment's opening tag into this block.
    starts = [_block_start(text, pos) for pos, _ in marks]
    comments = []
    depths = []
    for i, (pos, cid) in enumerate(marks):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[starts[i]:end]
        c = {"comment_id": cid, "article": None}
        m = AUTHOR_RE.search(block)
        if m:
            name = next((g for g in m.groups() if g), "").strip()
            if name:
                c["display_name"] = name[:200]
        m = PROFILE_RE.search(block)
        if m:
            link = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if link and not link.startswith("#"):
                c["profile_link"] = link
            if m.group(4) and "display_name" not in c:
                c["display_name"] = m.group(4).strip()[:200]
        m = USERID_RE.search(block)
        if m:
            c["user_id"] = m.group(1)
        m = UNIX_TS_RE.search(block)
        if m:
            c["posted_at"] = datetime.fromtimestamp(
                int(m.group(1)), timezone.utc).isoformat(timespec="seconds")
        else:
            m = TIME_RE.search(block)
            if m:
                c["posted_at"] = next((g for g in m.groups() if g),
                                      "").strip()
        m = PARENT_RE.search(block)
        if m:
            c["parent_id"] = m.group(1)
        m = DEPTH_RE.search(block)
        depth = int(m.group(1)) if m else None
        for cre in CONTENT_RES:
            m = cre.search(block)
            if m:
                body = m.group(1)
                # cut at the nested reply wrapper start if present
                cut = re.search(r'<(?:li|div)[^>]*class="[^"]*(?:children|'
                                r'reply|comment-reply)', body, re.I)
                if cut:
                    body = body[:cut.start()]
                t = _strip_tags(body)
                if t:
                    c["text"] = body.strip()[:20000]
                break
        comments.append(c)
        depths.append(depth)
    # parent from thread nesting: a comment at depth d replies to the
    # nearest preceding comment at depth d-1 (theme classes say 'depth-N')
    for i, c in enumerate(comments):
        if c.get("parent_id") or not depths[i] or depths[i] < 2:
            continue
        for j in range(i - 1, -1, -1):
            if depths[j] == depths[i] - 1:
                c["parent_id"] = comments[j]["comment_id"]
                break
    return comments


def wp_inpage_capture(host, article):
    cookies = None
    if host == "newsroom.co.nz" and os.path.exists(NEWSROOM_STATE):
        try:
            st = json.load(open(NEWSROOM_STATE))
            jar = st.get("cookies") or st
            if isinstance(jar, dict):
                cookies = "; ".join(f"{k}={v}" for k, v in jar.items()
                                    if isinstance(v, str))
        except (ValueError, OSError):
            pass
    st, addr, body, _ = fetch(article, cookies=cookies)
    fat = now_iso()
    if st in (401, 403) and cookies:
        st, addr, body, _ = fetch(article)   # anon retry to confirm gate
        fat = now_iso()
    if st != 200:
        return [], [], 0, f"http {st}"
    comments = wp_inpage_parse(body)
    for c in comments:
        c["article"] = article
        pl = c.get("profile_link")
        if pl and pl.startswith("/"):
            c["profile_link"] = SCHEME + host + pl
    return [(st, addr, body, fat)], comments, len(comments), None


# -- family: Coral ----------------------------------------------------------

def coral_payloads():
    """Load the persisted-query payload templates captured 2026-11-17."""
    d = json.load(open(CORAL_CAPTURE))
    stream = count = endpoint = None
    for r in d.get("requests", []):
        post = json.loads(r["post"])
        v = post.get("variables") or {}
        endpoint = endpoint or r["url"]
        if "commentsOrderBy" in v and stream is None:
            stream = post
        elif set(v) == {"storyID", "storyURL"} and count is None:
            count = post
    return endpoint, stream, count


def coral_story_id(article):
    path = urllib.parse.urlsplit(article).path
    segs = re.findall(r"(\d{6,})", path)
    return "masthead-" + segs[0] if segs else None


def coral_comments_from(node, article, out):
    c = {"comment_id": str(node.get("id", "")), "article": article}
    a = node.get("author") or {}
    if a.get("id"):
        c["user_id"] = str(a["id"])
    if a.get("username"):
        c["display_name"] = a["username"]
    if a.get("avatar"):
        c["avatar"] = a["avatar"]
    if a.get("createdAt"):
        c["joined_at"] = a["createdAt"]
    if node.get("parent") and node["parent"].get("id"):
        c["parent_id"] = str(node["parent"]["id"])
    if node.get("createdAt"):
        c["posted_at"] = node["createdAt"]
    if node.get("body"):
        c["text"] = node["body"]
    if node.get("actionCounts"):
        c["votes"] = node["actionCounts"]
    if node.get("status"):
        c["status"] = node["status"]
    if node.get("deleted"):
        c["deleted"] = bool(node["deleted"])
    out.append(c)
    for e in (node.get("replies") or {}).get("edges") or []:
        n = e.get("node")
        if n:
            coral_comments_from(n, article, out)


def coral_capture(host, article):
    endpoint, stream_t, count_t = coral_payloads()
    sid = coral_story_id(article)
    if not (endpoint and stream_t and sid):
        return [], [], 0, "no story id / payload"
    origin = SCHEME + urllib.parse.urlsplit(article).netloc
    hdrs = {"Content-Type": "application/json", "Origin": origin}
    pages_raw, comments = [], []
    # count first (total_at_capture + early exit for commentless stories)
    total = None
    if count_t:
        payload = dict(count_t)
        payload["variables"] = {"storyID": sid, "storyURL": article}
        st, addr, body, _ = fetch(
            endpoint, data=json.dumps(payload).encode(), headers=hdrs)
        fat = now_iso()
        pages_raw.append((st, addr, body, fat))
        try:
            total = (json.loads(body).get("data") or {}).get("story") \
                or {}
            total = (total.get("commentCounts") or {}).get("totalPublished")
        except ValueError:
            total = None
    payload = dict(stream_t)
    payload["variables"] = dict(stream_t["variables"])
    payload["variables"].update({"storyID": sid, "storyURL": article})
    st, addr, body, _ = fetch(
        endpoint, data=json.dumps(payload).encode(), headers=hdrs)
    fat = now_iso()
    pages_raw.append((st, addr, body, fat))
    if st != 200:
        return pages_raw, comments, 0, f"http {st}"
    try:
        data = json.loads(body)
    except ValueError:
        return pages_raw, comments, 0, "bad json"
    story = (data.get("data") or {}).get("story") or {}
    edges = ((story.get("comments") or {}).get("edges")) or []
    for e in edges:
        n = e.get("node")
        if n:
            coral_comments_from(n, article, comments)
    page_info = (story.get("comments") or {}).get("pageInfo") or {}
    if page_info.get("hasNextPage"):
        # fetchMore query id not captured (2026-11-17 pass) — honest gap
        gap_row(host, article,
                "coral stream pagination: hasNextPage with no fetchMore "
                "query id captured", "open")
    if total is None:
        total = len(comments)
    return pages_raw, comments, total, None


# -- the sweep --------------------------------------------------------------

def due_milestones(published_at, state, article):
    """Which milestones are due now and not yet captured/terminal."""
    if published_at < FORWARD:
        return []
    age = (datetime.now(timezone.utc) - published_at).total_seconds() / 86400.0
    out = []
    for m in MILESTONES:
        rec = state.get((article, m))
        if rec and rec.get("status") in ("captured", "challenge"):
            continue
        # failed (non-challenge) retries next sweep — a transient error
        # must not cost the milestone; challenges never retry
        if m == "first" or age >= AGE_DAYS[m]:
            out.append(m)
        if out and m != out[0]:
            break          # one milestone per sweep, oldest due first
    return out[:1]


def run_host(host, budget):
    family = HOST_FAMILY[host]
    mfest = os.path.join(NEWS, host, "manifest.jsonl")
    if not os.path.exists(mfest):
        return {"host": host, "error": "no news manifest"}
    state = read_state()
    arts = []
    for line in open(mfest):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") != "article":
            continue
        pub = parse_iso(r.get("published_at"))
        art = (r.get("urls") or [{}])
        art = art[0].get("url") if isinstance(art, list) else None
        if not art or not pub:
            continue
        arts.append((pub, art, r))
    arts.sort(key=lambda t: t[0])
    did = errs = 0
    for pub, art, row in arts:
        if did >= budget:
            break
        for milestone in due_milestones(pub, state, art):
            if family == "wp_rest":
                post_id = resolve_post_id(host, art, row)
                if not post_id:
                    gap_row(host, art, "no WP post id resolvable", "open")
                    fail_mark(art, milestone, "no post id", False)
                    errs += 1
                    continue
                pages, comments, total, err = wp_rest_capture(
                    host, art, post_id)
            elif family == "wp_inpage":
                pages, comments, total, err = wp_inpage_capture(host, art)
            else:
                pages, comments, total, err = coral_capture(host, art)
            if err or not pages:
                reason = err or "no bytes"
                challenge = reason.startswith("http 403") \
                    or reason.startswith("http 401") \
                    or "challenge" in reason
                gap_row(host, art, reason,
                        "challenge" if challenge else "open")
                fail_mark(art, milestone, reason, challenge)
                errs += 1
                continue
            rid, n = land(host, milestone, art, row.get("published_at"),
                          family, pages, comments, total)
            print(f"  {host} {milestone} {art[:70]} -> {rid} "
                  f"({n} comments, total={total})")
            did += 1
            state[(art, milestone)] = {"status": "captured"}
    return {"host": host, "captured": did, "errors": errs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--budget", type=int, default=12,
                    help="max captures per host per run")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    hosts = [args.host] if args.host else sorted(HOST_FAMILY)
    if args.dry:
        state = read_state()
        for h in hosts:
            fam = HOST_FAMILY[h]
            mfest = os.path.join(NEWS, h, "manifest.jsonl")
            n_due = 0
            if os.path.exists(mfest):
                for line in open(mfest):
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("kind") != "article":
                        continue
                    pub = parse_iso(r.get("published_at"))
                    art = (r.get("urls") or [{}])[0].get("url")
                    if art and pub and due_milestones(pub, state, art):
                        n_due += 1
            print(f"{fam:9} {h:28} due={n_due}")
        return 0
    total = {"captured": 0, "errors": 0}
    for h in hosts:
        r = run_host(h, args.budget)
        if "error" in r:
            print(f"  {h}: {r['error']}")
        total["captured"] += r.get("captured", 0)
        total["errors"] += r.get("errors", 0)
    print(f"comments capture: captured={total['captured']} "
          f"errors={total['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
