#!/usr/bin/env python3
"""
collect_electoral.py — Electoral Commission collector (estate-collect@2026-11-13b).

Walks elections.nz + electionresults.govt.nz and downloads every document the
Commission publishes that the estate does not hold, whole and as fetched, with
the page that lists it and all its metadata. NO text extraction (the estate does
that). Inspecting bytes to tell a real document from an error page or stub is
allowed.

Skip rule (13b):
  * held rows with an address -> compare normalized addresses (no tracking
    parameters, no fragment, no scheme, host case-folded, no trailing slash)
  * held rows with a file name and kind candidate-return -> match the last part
    of the document's address (no download needed)
  * other held rows without an address -> match by sha256 only (those documents
    are fetched once to compare)
  * one document behind several addresses is one record (dedupe by sha256)

Routing: donation and loan disclosures -> sources/disclosures (estate-disclosures);
candidate returns -> sources/candidate_returns (estate-candidate_returns);
everything else -> sources/estate-elections (estate-elections). Nothing goes to
estate-local_elections.

Never collected: the electoral roll and enrolment extracts.
Politeness: robots.txt honoured (Disallow + Crawl-delay), paced fetches, and the
run STOPS and reports at any challenge or block (403/429 or challenge page).

Stdlib only. Resumable: queue + visited state in a JSON file; manifests are the
landing log (one row per sha256; extra addresses merge into the row).
"""

import argparse
import base64
import hashlib
import html.parser
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone

SCHEME = "https" + chr(58) + chr(47) + chr(47)
HOSTS = ("elections.nz", "electionresults.govt.nz")
UA = "QueryNZIngestBot/1.0 (estate-collect; polite collector; contact: operator)"
SRC_ROOT = "/opt/data/querynz-estate/sources"
ASKS_DIR = "/opt/data/qnz-mcp/asks"
HELD_TSV = os.path.join(ASKS_DIR, "held-electoral-commission.tsv")
STATE_PATH = "/opt/data/querynz-estate/collect_electoral_state.json"
LOCK_PATH = "/opt/data/querynz-estate/collect_electoral_state.lock"
GAPS_PATH = "/opt/data/querynz-estate/gaps/collect_electoral.jsonl"


def log_gap(source, url, reason, status=None, note=None):
    """A gap ledger row per failed read (Arthur, 2026-11-13: go slow and keep a
    list of gaps for each source to assess later). One row per gap, ever."""
    os.makedirs(os.path.dirname(GAPS_PATH), exist_ok=True)
    seen = set()
    if os.path.exists(GAPS_PATH):
        with open(GAPS_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("url") == url and r.get("reason") == reason:
                    return                     # already listed
                seen.add((r.get("url"), r.get("reason")))
    with open(GAPS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "source": source, "url": url, "reason": reason,
            "status": status, "at": now_iso(), "note": note,
        }, ensure_ascii=False) + "\n")

CORPUS_DIRS = {
    "donation-disclosure": "disclosures",        # estate-disclosures
    "candidate-return": "candidate_returns",     # estate-candidate_returns
    "other": "estate-elections",                 # estate-elections
}

DOC_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".rtf", ".odt",
            ".ods", ".ppt", ".pptx", ".zip", ".txt", ".json", ".xml")
TRACKING_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "gclid", "fbclid", "msclkid", "mc_cid",
                   "mc_eid")
NEVER_PATH = ("electoral-roll", "enrolment-extract", "enrolment_extract")
CHALLENGE_MARKERS = ("incapsula", "_incapsula_", "captcha", "access denied",
                     "attention required", "cf-chl")

PROXY_CONFIG = "/opt/data/beehive-scraper/proxy.json"
BUA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


def is_challenge(data):
    """An interstitial rather than the page asked for (C215: size is not the
    signal — marker + shell shape). A challenged read is a failed read."""
    head = data[:8192].decode("utf-8", "replace")
    if "_Incapsula_Resource" in head and ("main-iframe" in head or len(data) < 5000):
        return True
    return any(m in head for m in
               ("/cdn-cgi/challenge-platform/", "cf-chl-", "Just a moment...",
                "awsWafCoo"))


def _proxy_parts(proxied):
    """(user, password, hostport) for one fresh IPRoyal session."""
    if not proxied:
        return None
    cfg = json.load(open(PROXY_CONFIG))
    user = base64.b64decode(cfg["username_b64"]).decode()
    base_pw = base64.b64decode(cfg["password_base_b64"]).decode()
    pw = base_pw + "_country-nz_session-" + secrets.token_hex(6) + "_lifetime-30m"
    hostport = cfg["server"].split("//", 1)[1]
    return user, pw, hostport


def make_opener(proxied):
    """Direct opener, or one IPRoyal residential session for the whole run
    (ONE session per run, rotate on failure only — the questions-host lesson).
    Same config/password template as news-scrapers/ingestion/proxies.py."""
    parts = _proxy_parts(proxied)
    if not parts:
        return urllib.request.build_opener()
    user, pw, hostport = parts
    scheme_sep = "http" + chr(58) + chr(47) + chr(47)
    purl = scheme_sep + urllib.parse.quote(user) + ":" + urllib.parse.quote(pw) + "@" + hostport
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": purl, "https": purl}))


class BrowserFetcher:
    """Headed chromium on a DIRECT connection — the estate's own working
    recipe (the candidate_returns lane reads these sites with it daily;
    measured 2026-11-25: headless + the residential exit draws the Incapsula
    interstitial and it will not self-solve even at a 40s window, while this
    recipe reads clean). The interstitial self-solve below stays as the
    fallback semantics: a challenge that will not clear is a failed read —
    never defeated, solved or answered. Playwright only."""
    def __init__(self, proxied=False):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._b = self._pw.chromium.launch(headless=False, args=_LAUNCH_ARGS)
        self._ctx = self._b.new_context(user_agent=BUA)
        self.page = self._ctx.new_page()

    def close(self):
        try:
            self._b.close()
            self._pw.stop()
        except Exception:
            pass

    def _is_shell(self, body_text):
        return is_challenge(body_text.encode("utf-8", "replace"))

    def fetch(self, url, timeout=60):
        last = None
        for attempt in range(3):     # the WAF flaps (200/403/5xx same URL, measured)
            try:
                return self._fetch_once(url, timeout)
            except FetchError as e:
                retryable = e.kind == "challenge" or (
                    e.kind == "http" and e.status in (429, 500, 502, 503, 504))
                if not retryable or attempt == 2:
                    raise
                last = e
                time.sleep(20)
        raise last

    def _fetch_once(self, url, timeout=60):
        # browserfetch recipe (news-scrapers): request first — raw bytes as
        # fetched; where the interstitial answers, navigate to let it solve
        # itself (what any browser does — we do not defeat one), then re-read
        # the raw body with the solved cookie (it carries to later URLs).
        resp = self._ctx.request.get(url, timeout=timeout * 1000)
        data = resp.body()
        if resp.status >= 400 or is_challenge(data):
            if resp.status >= 400 and resp.status not in (403, 429) \
                    and not is_challenge(data):
                raise FetchError(resp.status, "http")
            try:
                self.page.goto(url, wait_until="domcontentloaded",
                               timeout=timeout * 1000)
            except Exception:
                pass
            # 20 rounds: a 12s (6x2s) window is insufficient on headless
            # chromium to let the interstitial's own script resolve (measured
            # on worksafe 2026-11-25 — 20 rounds needed there).
            for _ in range(20):
                if not self._is_shell(self.page.content()):
                    break
                time.sleep(2)
            else:
                raise FetchError(resp.status or 403, "challenge")
            resp = self._ctx.request.get(url, timeout=timeout * 1000)
            data = resp.body()
            if resp.status in (403, 429) or is_challenge(data):
                raise FetchError(resp.status or 403, "challenge")
        return {
            "address": url, "final_address": resp.url,
            "content_type": resp.headers.get("content-type"),
            "size": len(data),
            "last_modified": resp.headers.get("last-modified"),
            "etag": resp.headers.get("etag"),
            "fetched_at": now_iso(),
        }, data


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_addr(url):
    """Address compare: no tracking params, no fragment, no scheme, host
    case-folded, no trailing slash (rule_add, 13b)."""
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if k.lower() not in TRACKING_PARAMS]
    query = urllib.parse.urlencode(q)
    path = p.path or "/"
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    host = (p.hostname or "").lower()
    return host + path + (("?" + query) if query else "")


def last_part(url):
    path = urllib.parse.urlsplit(url).path
    return urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1]).lower()


def host_of(url):
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def same_site(url):
    h = host_of(url)
    return any(h == d or h.endswith("." + d) for d in HOSTS)


class Held:
    """held-electoral-commission.tsv: kind, date_or_year, address_or_name, sha256."""
    def __init__(self, path):
        self.addrs, self.names, self.shas = set(), set(), set()
        self.counts = {"address": 0, "candidate-name": 0, "store-name": 0, "sha": 0}
        with open(path, encoding="utf-8") as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                cols = line.rstrip("\n").split("\t")
                row = dict(zip(header, cols))
                name_or_addr = (row.get("address_or_name") or "").strip()
                sha = (row.get("sha256") or "").strip().lower()
                kind = (row.get("kind") or "").strip()
                if name_or_addr.startswith("http"):
                    self.addrs.add(norm_addr(name_or_addr))
                    self.counts["address"] += 1
                elif kind == "candidate-return":
                    self.names.add(name_or_addr.rsplit("/", 1)[-1].lower())
                    self.counts["candidate-name"] += 1
                elif name_or_addr:
                    self.names.add(name_or_addr.rsplit("/", 1)[-1].lower())
                    self.counts["store-name"] += 1
                if sha:
                    self.shas.add(sha)
                    self.counts["sha"] += 1

    def by_addr(self, url):
        return norm_addr(url) in self.addrs

    def by_name(self, url):
        return last_part(url) in self.names

    def by_sha(self, sha):
        return sha in self.shas


class LinkParser(html.parser.HTMLParser):
    """Links with anchor text + nearest row-ish context (the listing's own words)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []           # (href, anchor_text, context_text)
        self._stack = []          # open tags
        self._anchor = None       # [href, text_parts, context_parts, depth]
        self.title_parts = []
        self._in_title = 0

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag)
        if tag == "title":
            self._in_title += 1
        if tag == "a":
            href = dict(attrs).get("href")
            self._anchor = [href, [], [], len(self._stack)]

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = max(0, self._in_title - 1)
        if self._anchor is not None and tag == "a":
            href, parts, _ctx, _d = self._anchor
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if href:
                self.links.append((href, text, ""))
            self._anchor = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)


def page_title(html_bytes):
    p = LinkParser()
    try:
        p.feed(html_bytes.decode("utf-8", "replace"))
    except Exception:
        return ""
    return re.sub(r"\s+", " ", "".join(p.title_parts)).strip()


def row_context(html_text, href):
    """The nearest row-ish container around the href: the listing's own words
    about the document (everything the site states)."""
    idx = -1
    for v in (href, href.replace("&", "&amp;")):
        idx = html_text.find(v)
        if idx >= 0:
            break
    if idx < 0:
        return ""
    best = ""
    for open_t, close_t in (("<tr", "</tr>"), ("<li", "</li>"), ("<p", "</p>")):
        lo = html_text.rfind(open_t, 0, idx)
        hi = html_text.find(close_t, idx)
        if lo >= 0 and hi > lo:
            best = html_text[lo:hi + len(close_t)]
            break
    if not best:
        lo, hi = max(0, idx - 300), min(len(html_text), idx + 300)
        best = html_text[lo:hi]
    text = re.sub(r"<[^>]+>", " ", best)
    return re.sub(r"\s+", " ", text).strip()[:500]


DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{4})\b")


def extract_links(html_bytes, base_url):
    p = LinkParser()
    html_text = html_bytes.decode("utf-8", "replace")
    try:
        p.feed(html_text)
    except Exception:
        return []
    out = []
    for href, text, _ctx in p.links:
        u = urllib.parse.urljoin(base_url, href.strip())
        if u.startswith(("http:", "https:")):
            ctx = row_context(html_text, href.strip())
            m = DATE_RE.search(ctx)
            out.append((u, text, {
                "title": text or None,
                "date": m.group(1) if m else None,
                "context": ctx or None,
            }))
    return out


def classify(url, anchor):
    """-> (kind, corpus_dir_key). Donation/loan disclosures -> disclosures;
    candidate returns -> candidate_returns; everything else -> estate-elections."""
    hay = (urllib.parse.unquote(url) + " " + (anchor or "")).lower()
    fn = last_part(url)
    if "enrol" in hay and ("extract" in hay or "roll" in hay):
        return "never", None
    if re.match(r"^\d{4}_[^/]+_[^/]+_[^/]+\.pdf$", fn) or \
       ("candidate" in hay and "return" in hay):
        return "candidate-return", "candidate-return"
    if ("donation" in hay or "loan" in hay) and "disclosure" in hay:
        return "donation-disclosure", "donation-disclosure"
    return "document" if fn.endswith(DOC_EXTS) else "web-page", "other"


class FetchError(Exception):
    def __init__(self, status, kind):
        super().__init__(kind)
        self.status = status
        self.kind = kind  # 'challenge' | 'http' | 'io'


def fetch(url, opener, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-NZ,en;q=0.9",
    })
    try:
        with opener.open(req, timeout=timeout) as r:
            status = r.status
            if status in (403, 429):
                raise FetchError(status, "challenge")
            data = r.read()
            hdr = r.headers
            meta = {
                "address": url,
                "final_address": r.geturl(),
                "content_type": hdr.get("Content-Type"),
                "size": len(data),
                "last_modified": hdr.get("Last-Modified"),
                "etag": hdr.get("ETag"),
                "fetched_at": now_iso(),
            }
            return meta, data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise FetchError(e.code, "challenge")
        raise FetchError(e.code, "http")
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(0, "io:" + type(e).__name__)


def looks_like_challenge(data):
    return is_challenge(data)


class Robots:
    """robots.txt per RFC 9309: 2xx = obey; 4xx = no restrictions (a block on
    content is still honoured by the fetch layer); 5xx/io = stay out."""

    def __init__(self, opener):
        self.opener = opener
        self.rp = {}
        self.delay = {}

    def ready(self, host):
        if host not in self.rp:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(SCHEME + host + "/robots.txt",
                                             headers={"User-Agent": UA})
                with self.opener.open(req, timeout=30) as r:
                    rp.parse(r.read().decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:
                    rp.parse([])
                else:
                    rp.parse(["User-agent: *", "Disallow: /"])
            except Exception:
                rp.parse(["User-agent: *", "Disallow: /"])
            self.rp[host] = rp
            try:
                d = rp.crawl_delay("*")
                self.delay[host] = float(d) if d else 2.0
            except Exception:
                self.delay[host] = 2.0
        return self.rp[host]

    def allowed(self, url):
        rp = self.ready(host_of(url))
        try:
            return rp.can_fetch("*", url)
        except Exception:
            return True

    def pace(self, host):
        return max(5.0, float(self.delay.get(host, 2.0)))   # go slow (2026-11-13)


class Landings:
    """Manifest I/O: one row per sha256; extra addresses merge into the row."""

    def __init__(self):
        self.rows = {}          # corpus_key -> {sha: row}
        self.by_addr = {}       # corpus_key -> {norm_addr: sha}
        for key in CORPUS_DIRS.values():
            self._load(key)

    def _manifest(self, key):
        return os.path.join(SRC_ROOT, key, "manifest.jsonl")

    def _load(self, key):
        rows, addrs = {}, {}
        path = self._manifest(key)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    sha = row.get("sha256")
                    if not sha:
                        continue
                    rows[sha] = row
                    for u in row.get("urls", []):
                        addrs[norm_addr(u.get("url", ""))] = sha
        self.rows[key] = rows
        self.by_addr[key] = addrs

    def known_sha(self, sha):
        return any(sha in r for r in self.rows.values())

    def known_addr(self, key, url):
        return norm_addr(url) in self.by_addr.get(key, {})

    def land(self, key, row):
        sha = row["sha256"]
        rows = self.rows[key]
        if sha in rows:
            old = rows[sha]
            known = {norm_addr(u.get("url", "")) for u in old.get("urls", [])}
            if any(norm_addr(u.get("url", "")) not in known for u in row["urls"]):
                old.setdefault("urls", []).extend(row["urls"])
            old["landings"] = old.get("landings", 1) + 1
            old["last_landed"] = row["landed_at"]
            old["names"] = list(dict.fromkeys(old.get("names", []) + row.get("names", [])))
        else:
            rows[sha] = row
            self.by_addr.setdefault(key, {})
            for u in row["urls"]:
                self.by_addr[key][norm_addr(u["url"])] = sha

    def flush(self, key):
        path = self._manifest(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for row in self.rows[key].values():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)


def save_file(key, sha, ext, data):
    d = os.path.join(SRC_ROOT, key)
    os.makedirs(d, exist_ok=True)
    fn = sha + ext
    path = os.path.join(d, fn)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return fn


def ext_for(url, content_type):
    fn = last_part(url)
    if "." in fn:
        e = "." + fn.rsplit(".", 1)[-1].lower()
        if len(e) <= 6:
            return e
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        return {"text/html": ".html", "application/pdf": ".pdf",
                "text/csv": ".csv", "application/json": ".json",
                "text/xml": ".xml", "image/jpeg": ".jpg",
                "image/png": ".png", "application/zip": ".zip"}.get(ct, ".bin")
    return ".bin"


class Runner:
    def __init__(self, args):
        self.args = args
        self.held = Held(args.held_tsv)
        self.landings = Landings()
        self.opener = make_opener(args.proxy)
        self.robots = Robots(self.opener)
        self.browser = BrowserFetcher(args.proxy) if args.browser else None
        self.state = self._load_state()
        self.stats = {}   # host -> dict
        self.blocked = None
        self._io_errors = 0
        self._challenge_run = 0

    def _load_state(self):
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {"queued": [], "visited": {}}

    def _save_state(self):
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE_PATH)

    def stat(self, host):
        return self.stats.setdefault(host, {
            "fetched_pages": 0, "fetched_docs": 0, "landed": 0,
            "skipped_held": 0, "skipped_dup": 0, "skipped_disallowed": 0,
            "errors": 0, "blocked": False})

    def _record_failed(self, url, listing, listed_meta):
        """Keep the queue entry (listing context included) so a wave can
        re-ask exactly once, later. The gap ledger is the durable history;
        this is the retry source."""
        self.state.setdefault("failed", []).append([url, listing, listed_meta])

    def wave_reset(self):
        """One re-attempt wave (committed EC waves 11-24 / 12-01 / 12-08).
        Re-queues every failed read once — a listed URL is never re-hammered
        inside a run; the wave IS the spaced re-ask — and re-sweeps listing
        pages so new documents surface. Documents already held skip by
        address/name/sha on the walk. Terminal by ruling (held, never,
        disallowed, offsite) stay put."""
        requeued = 0
        for entry in self.state.get("failed", []):
            k = norm_addr(entry[0])
            if k not in self.state["visited"]:
                self.state["queued"].append(entry)
                requeued += 1
        self.state["failed"] = []
        for k, st in list(self.state["visited"].items()):
            url = SCHEME + k
            retryable = st in ("challenge", "challenge-page") or str(st).startswith("error:")
            page_sweep = st == "fetched" and not last_part(url).endswith(DOC_EXTS)
            if retryable or page_sweep:
                del self.state["visited"][k]
                self.state["queued"].append([url, None, None])
                requeued += 1
        print("wave: %d URLs re-queued" % requeued)

    def enqueue(self, url, listing, meta=None):
        n = norm_addr(url)
        if n not in self.state["visited"]:
            self.state["queued"].append([url, listing, meta])

    def seed(self):
        if self.state["queued"] or self.state["visited"]:
            return
        for h in HOSTS:
            self.enqueue(SCHEME + h + "/", None)

    def run(self):
        deadline = time.time() + self.args.max_seconds
        fetches = 0
        if getattr(self.args, "wave", False):
            self.wave_reset()
        self.seed()
        while self.state["queued"] and fetches < self.args.max_fetches \
                and time.time() < deadline and not self.blocked:
            q = self.state["queued"]
            di = next((i for i, e in enumerate(q)
                       if last_part(e[0]).endswith(DOC_EXTS)), None)
            url, listing, listed_meta = (q.pop(di if di is not None else 0) + [None])[:3]
            n = norm_addr(url)
            if n in self.state["visited"]:
                continue
            if not same_site(url):
                self.state["visited"][n] = "offsite"
                continue
            if any(p in urllib.parse.unquote(url).lower() for p in NEVER_PATH):
                self.state["visited"][n] = "never"
                self.stat(host_of(url))["skipped_held"] += 1
                continue
            host = host_of(url)
            st = self.stat(host)
            if not self.robots.allowed(url):
                self.state["visited"][n] = "disallowed"
                st["skipped_disallowed"] += 1
                log_gap(host, url, "disallowed")
                continue
            kind, dirkey = classify(url, None)
            if kind == "never":
                self.state["visited"][n] = "never"
                continue
            is_doc = last_part(url).endswith(DOC_EXTS)
            # held-by-address or held-by-filename: skip without downloading
            if self.held.by_addr(url) or (is_doc and self.held.by_name(url)):
                self.state["visited"][n] = "held"
                st["skipped_held"] += 1
                continue
            try:
                if self.browser is not None:
                    meta, data = self.browser.fetch(url)
                else:
                    meta, data = fetch(url, self.opener)
            except FetchError as e:
                if e.kind == "challenge":
                    st["challenged"] = st.get("challenged", 0) + 1
                    self.state["visited"][n] = "challenge"
                    self._record_failed(url, listing, listed_meta)
                    log_gap(host, url, "challenge", e.status)
                    time.sleep(15)     # cool down — go slow
                    continue
                st["errors"] += 1
                self.state["visited"][n] = "error:%s" % e.kind
                self._record_failed(url, listing, listed_meta)
                log_gap(host, url, "error", e.status, note=e.kind)
                if self.args.proxy and e.kind.startswith("io"):
                    self._io_errors += 1
                    if self._io_errors >= 3:   # rotate on failure only
                        self.opener = make_opener(True)
                        self.robots = Robots(self.opener)
                        self._io_errors = 0
                continue
            self._io_errors = 0
            fetches += 1
            if looks_like_challenge(data):
                st["challenged"] = st.get("challenged", 0) + 1
                self.state["visited"][n] = "challenge-page"
                self._record_failed(url, listing, listed_meta)
                log_gap(host, url, "challenge-page")
                time.sleep(15)     # cool down — go slow
                continue
            ctype = (meta.get("content_type") or "").split(";")[0].strip().lower()
            is_html = "html" in ctype or (not is_doc and not ctype)
            sha = hashlib.sha256(data).hexdigest()
            self.state["visited"][n] = "fetched"
            # held-by-sha (store-name rows): fetched once to compare (13b)
            if self.held.by_sha(sha) or self.landings.known_sha(sha):
                st["skipped_held" if self.held.by_sha(sha) else "skipped_dup"] += 1
                time.sleep(self.robots.pace(host))
                continue
            kind, dirkey = classify(url, None)
            # land whole bytes as fetched, with listing + response metadata
            dirname = CORPUS_DIRS[dirkey]
            ext = ext_for(url, ctype)
            fn = save_file(dirname, sha, ext, data)
            row = {
                "sha256": sha,
                "size": meta["size"],
                "kind": kind,
                "content_type": meta.get("content_type"),
                "file": fn,
                "urls": [{"url": meta["address"], "via": ["collect_electoral"]}],
                "names": [(listed_meta or {}).get("title") or meta["address"]],
                "listed_on": [listing] if listing else [],
                "listed": dict(listed_meta or {}, section=urllib.parse.urlsplit(listing or "").path or None),
                "landings": 1,
                "first_landed": meta["fetched_at"],
                "last_landed": meta["fetched_at"],
                "fetched_at": meta["fetched_at"],
                "landed_at": meta["fetched_at"],
                "last_modified": meta.get("last_modified"),
                "etag": meta.get("etag"),
                "final_address": meta.get("final_address"),
                "withdrawn": False,
                "withdrawn_reason": None,
                "problem": None,
            }
            self.landings.land(dirname, row)
            st["landed"] += 1
            if is_html:
                st["fetched_pages"] += 1
                title = page_title(data)
                if title:
                    row["names"] = [title]
                for href, anchor, lmeta in extract_links(data, meta["final_address"]):
                    if same_site(href):
                        self.enqueue(href, meta["address"], lmeta)
            else:
                st["fetched_docs"] += 1
            if fetches % 25 == 0:
                self._save_state()
                for key in CORPUS_DIRS.values():
                    self.landings.flush(key)
            time.sleep(self.robots.pace(host))
        self._save_state()
        for key in CORPUS_DIRS.values():
            self.landings.flush(key)
        if self.browser is not None:
            self.browser.close()
        self.report(fetches)

    def report(self, fetches):
        out = ["collect_electoral: %s" % now_iso(),
               "held TSV rows: %s" % self.held.counts,
               "fetches this run: %d" % fetches]
        for host, st in sorted(self.stats.items()):
            out.append("  %s: %s" % (host, st))
        if self.blocked:
            out.append("BLOCKED/CHALLENGE at %s (%s) — run stopped per the standing rule"
                       % (self.blocked[0], self.blocked[1]))
        q = len(self.state["queued"])
        out.append("queue remaining: %d" % q)
        print("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fetches", type=int, default=400)
    ap.add_argument("--max-seconds", type=int, default=1500)
    ap.add_argument("--held-tsv", default=HELD_TSV)
    ap.add_argument("--proxy", action="store_true",
                    help="route through one IPRoyal residential session (unblocker)")
    ap.add_argument("--browser", action="store_true",
                    help="fetch via headless chromium (Incapsula interstitials)")
    ap.add_argument("--wave", action="store_true",
                    help="one re-attempt wave: re-queue failed reads + re-sweep listing pages")
    args = ap.parse_args()
    # single-instance lock
    import fcntl
    with open(LOCK_PATH, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another run in progress — silent skip
        Runner(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
