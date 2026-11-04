"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only.

Two publishers' documents, both the Department of Internal Affairs':

  dia-file      the national file of class 4 grants, "Grants from Gaming
                Machine Profits" (CC BY 4.0), a CSV the government data
                catalogue lists on its package page. The page is asked at most
                every `FILE_EVERY_DAYS`; the CSV it links is asked only when the
                page's link or the page itself has changed since the file held
                was landed (the Department updates it once a year).
  lottery-page  Community Matters (`www.communitymatters.govt.nz`), walked
                whole from its homepage (the whole-site doctrine: never
                hand-pick an organisation's pages), because its records of
                Lottery grants hang off no index: every page met is landed by
                its hash, and the reading reads the ones whose shape is a
                record of grants. The walk resumes from its frontier; a page is
                asked again only after `RECRAWL_DAYS`.
  about         the pages about the sources: the Department's copyright and
                terms, the catalogue's terms, at most every `ABOUT_EVERY_DAYS`;
                and each society's terms, copyright or privacy page, met on its
                walk, before its first list is landed.
  society-page  a class 4 society's own grants page (`SOCIETY_SITES`, class A
  society-file  of the card: the nine whose lists are files) and the pages it
                links on the same site whose address or words speak of grants,
                approved, declined, distributions, recipients or results, to
                `SOCIETY_DEPTH`; every file those pages link whose address or
                link words say the same is landed once (`society-file`) and
                never asked again: a society publishes a new list as a new file.
                A file whose name dates it wholly before 2017 is left unasked
                (ruling 71). A page is asked again after `RECRAWL_DAYS`.

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` apart
(the gate's floor binds too: the catalogue states a crawl delay of 10 s),
off-peak (22:00 to 06:00 NZ time) unless `--anytime`, a budget per run.
A redirect is never followed blind: the lane asks the gate about the address
it points to before asking for it, and leaves a page that points off the
publisher's host unasked. A 403, 429 or a challenge page (the gate's marks,
and the Imperva interstitial "Pardon Our Interruption" the catalogue served
on 21 October 2026 with a 200) is a block (hard limit 6): logged, the host is
not asked again this run, and the run moves to the next list. A 500, 502,
503 or 504 with no challenge is the server's own error: a failed read set
aside, the run rests `REST_S` and goes on; three in a row stop that host. A
gate refusal is never caught.

    python -m registers.grants.capture [--anytime] [--list dia-file|lottery-page|about|society-file] [--society KEY] [--max-requests N] [--budget-s N]
"""
import argparse
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.grants import read

SOURCE = SCHEMA = "grants"
JOB = "qv4-grants-capture"
FLOOR_S = 5.0
REST_S = 60.0
OFF_PEAK = (22, 6)
FILE_EVERY_DAYS = 30
ABOUT_EVERY_DAYS = 30
RECRAWL_DAYS = 30
DEFAULT_BUDGET_S = 4 * 3600
STOP_AFTER_FAILURES = 3
MAX_DEPTH = 8
SERVER_ERRORS = (500, 502, 503, 504)
SOCIETY_DEPTH = 2
FILE_DEPTH = -1        # a society's file in the frontier: asked once
ABOUT_DEPTH = -2       # a society's terms, copyright or privacy page in the frontier
#: class A of `cards/the-societies-own-grants-lists-by-class.md`: society key → its grants page, at the address it
#: answers on (the survey of 21 October 2026 followed each home page's redirect)
SOCIETY_SITES = {
    "nz-community-trust": "https://www.nzct.org.nz/grants",
    "air-rescue-services": "https://www.airrescueservices.co.nz/grant-distributions/",
    "pelorus-trust": "https://www.pelorustrust.net.nz/grants",
    "aotearoa-gaming-trust": "https://www.agt.nz/resources/funding-distributions",
    "one-foundation": "https://onefoundation.nz/grants",
    "trust-aoraki": "https://trustaoraki.co.nz/grants-list/",
    "new-horizon-community-trust": "https://www.newhorizoncommunitytrust.co.nz/approved-grants/",
    "milestone-foundation": "https://www.milestonefoundation.co.nz/grant-recipients.html",
    "we-care-community-trust": "https://wecare.org.nz/historical-grants.html",
}
#: the words by which a society's page or file says it is about the grants made
GRANT_WORDS = re.compile(r"(?i)grant|approved|declined|distribution|recipient|result|successful|allocation|funded")
#: words of a page about the source itself: its terms, copyright, privacy
ABOUT_WORDS = re.compile(r"(?i)terms|copyright|disclaimer|privacy")
FILE_SUFFIX = re.compile(r"(?i)\.(?:pdf|xlsx?|csv)$")
NOT_A_PAGE = re.compile(r"(?i)(/wp-admin|/wp-json|/feed\b|/cart|/login|/apply|/application|\.(?:docx?|zip|jpe?g|png|gif|"
                        r"svg|mp4|css|js|ico)$)")
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: until the integrator moves `position/*.md` to docs/legal/positions/, a session runs with QV4_POSITIONS pointing at
#: this lane's position folder.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
READING = "-- ── the reading"

FILE_PAGE = "https://catalogue.data.govt.nz/dataset/class-4-grants-data"
FILE_LINK = re.compile(r'href="(https://catalogue\.data\.govt\.nz/dataset/[0-9a-f-]+/resource/[0-9a-f-]+/download/'
                       r'class-4-grants[^"]*\.csv)"', re.I)
CM_HOST = "www.communitymatters.govt.nz"
CM_HOME = f"https://{CM_HOST}/"
ABOUT = {
    "dia-copyright": ("dia", "https://www.dia.govt.nz/Copyright"),
    "dia-terms-of-use": ("dia", "https://www.dia.govt.nz/Terms-of-use"),
}
#: marks of a challenge page the gate's own list lacks (card `the-fetch-gate-misses-an-imperva-interstitial`)
MORE_CHALLENGE_MARKS = ("pardon our interruption", "reese84", "_incapsula_resource", "x-spa-interstitial")
#: addresses the walk never asks: files, the CMS's own machinery, the ask-us search (it refused us, 21 October 2026)
SKIP = re.compile(r"(?i)(/__data/|/_media/|/_design|/_admin|/_edit|/_login|/_recache|/_performance|\?|/ask-us\b|"
                  r"\.(?:pdf|docx?|xlsx?|csv|zip|jpe?g|png|gif|svg|mp4|css|js|ico)$)")


# ── pure pieces ───────────────────────────────────────────────────────────────

def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    """The lane's own schema holds its tables by their names; any other (a session's scratch schema, a staging
    schema) carries the lane's prefix."""
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}(_private)?\.")


def capture_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read().split(READING)[0]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(lambda m: f"{schema}{'_private' if m.group(1) and schema == SCHEMA else ''}.{pre}", text)


def challenged(status: int, body: bytes) -> str:
    why = fg.looks_challenged(status, body)
    if why:
        return why
    head = body[:8192].decode("utf-8", "replace").lower()
    for mark in MORE_CHALLENGE_MARKS:
        if mark in head:
            return f"a challenge page ({mark!r}); a challenged read is a failed read (hard limit 6)"
    return ""


def canonical(url: str) -> str:
    """One address per page: no fragment, no trailing slash but the root's, the host in lower case."""
    p = urllib.parse.urlsplit(url)
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((p.scheme or "https", (p.hostname or "").lower(), path, p.query, ""))


def links(base: str, body: bytes, host: str) -> list:
    """Every address on the page on `host` that the walk may ask, in page order, once each."""
    out = []
    for h in re.findall(rb'href="([^"#]+)', body):
        u = urllib.parse.urljoin(base, html.unescape(h.decode("utf-8", "replace")).strip())
        if urllib.parse.urlsplit(u).scheme not in ("http", "https") or fg.host_of(u) != host or SKIP.search(u):
            continue
        u = canonical(u)
        if u not in out:
            out.append(u)
    return out


def site_of(host: str) -> str:
    """A host without its `www.`: a society links its own files under both."""
    return re.sub(r"^www\.", "", (host or "").lower())


def on_host(url: str, host: str) -> str:
    """A page of the same site at the walk's own host (a society links itself under both `www.` and bare)."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, host, p.path, p.query, p.fragment))


def quoted(url: str) -> str:
    """The address as a request can carry it: a space in a file's name (AGT's `download.php?file=… Q1 2026 ….pdf`)
    is percent-encoded, an escape already there is kept."""
    return urllib.parse.quote(url, safe=":/?=&%#;,+@~!$'()*")


def _years(text: str) -> list:
    return [int(y) for y in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", text)]


def before_window(url: str) -> bool:
    """A file whose name carries years and every one of them is before ruling 71's 2017."""
    ys = _years(urllib.parse.unquote(urllib.parse.urlsplit(url).path + "?" + urllib.parse.urlsplit(url).query))
    return bool(ys) and max(ys) < read.WINDOW_FROM


def society_links(base: str, body: bytes):
    """(pages, files, about) a society's page links on its own site, in page order, once each: pages and files whose
    address or link words say grants, and pages about the source (terms, copyright, privacy)."""
    pages, files, about = [], [], []
    site = site_of(fg.host_of(base))
    for h, words in re.findall(rb'<a\b[^>]*?href="([^"#]+)"[^>]*>(.*?)</a>', body, re.S | re.I):
        u = urllib.parse.urljoin(base, html.unescape(h.decode("utf-8", "replace")).strip())
        if urllib.parse.urlsplit(u).scheme not in ("http", "https") or site_of(fg.host_of(u)) != site:
            continue
        said = html.unescape(re.sub(r"<[^>]+>|\s+", " ", words.decode("utf-8", "replace")))
        path = urllib.parse.unquote(urllib.parse.urlsplit(u).path + " " + urllib.parse.urlsplit(u).query)
        file_name = urllib.parse.unquote(u.split("file=", 1)[1]) if "file=" in u else urllib.parse.urlsplit(u).path
        if FILE_SUFFIX.search(file_name):
            if GRANT_WORDS.search(path + " " + said) and u not in files:
                files.append(u)
        elif NOT_A_PAGE.search(urllib.parse.urlsplit(u).path):
            continue
        elif ABOUT_WORDS.search(path + " " + said):
            if canonical(u) not in about:
                about.append(canonical(u))
        elif GRANT_WORDS.search(path + " " + said) and canonical(u) not in pages:
            pages.append(canonical(u))
    return pages, files, about


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_once(url: str, timeout: int):
    """One request with the estate's User-Agent and no redirect followed: (status, body, final, location)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(quoted(url), headers={"User-Agent": fg.UA})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read(), r.geturl(), ""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.headers else ""
        body = b""
        try:
            body = e.read() or b""
        except Exception:  # noqa: BLE001 — an error page with no body is still the status
            pass
        return e.code, body, url, urllib.parse.urljoin(url, loc) if loc else ""


# ── the lane's capture tables ─────────────────────────────────────────────────

class Tables:
    """The capture's record over a psycopg connection in autocommit mode."""

    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema
        self.T = lambda t: table(schema, t)

    def create(self):
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s}")
        self.conn.execute(capture_sql(self.s))

    def try_lock(self) -> bool:
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def begin(self) -> int:
        return self.conn.execute(f"INSERT INTO {self.T('capture_runs')} DEFAULT VALUES RETURNING run_id").fetchone()[0]

    def finish(self, run_id, counts, stopped):
        self.conn.execute(f"UPDATE {self.T('capture_runs')} SET finished_at = now(), requests = %s, landed = %s, "
                          "set_aside = %s, stopped = %s WHERE run_id = %s",
                          (counts["requests"], counts["landed"], counts["set_aside"], stopped or None, run_id))

    def last(self, lst, url=None, publisher=None):
        """When `lst` (and `url`, and `publisher`) was last landed, and the hash."""
        q = f"SELECT at, sha256 FROM {self.T('capture_docs')} WHERE list = %s"
        args = [lst]
        if url:
            q += " AND url = %s"
            args.append(url)
        if publisher:
            q += " AND publisher = %s"
            args.append(publisher)
        return self.conn.execute(q + " ORDER BY at DESC LIMIT 1", args).fetchone()

    def add_doc(self, run_id, lst, publisher, url, sha, recognised, new):
        self.conn.execute(f"INSERT INTO {self.T('capture_docs')} (run_id, list, publisher, url, sha256, recognised, new) "
                          "VALUES (%s, %s, %s, %s, %s, %s, %s)", (run_id, lst, publisher, url, sha, recognised, new))

    def set_aside(self, run_id, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.T('capture_set_aside')} (run_id, item, stage, reason) "
                          "VALUES (%s, %s, %s, %s)", (run_id, str(item), stage, reason[:500]))

    def frontier_add(self, host, urls, depth):
        for u in urls:
            self.conn.execute(f"INSERT INTO {self.T('capture_frontier')} (host, url, depth) VALUES (%s, %s, %s) "
                              "ON CONFLICT DO NOTHING", (host, u, depth))

    def frontier_next(self, host, limit, recrawl_days):
        return [tuple(r) for r in self.conn.execute(
            f"SELECT url, depth FROM {self.T('capture_frontier')} WHERE host = %s AND depth <= %s AND "
            "depth >= 0 AND (asked_at IS NULL OR asked_at < now() - make_interval(days => %s)) ORDER BY asked_at NULLS FIRST, depth, "
            "found_at, url LIMIT %s", (host, MAX_DEPTH, recrawl_days, limit))]

    def frontier_unasked(self, host, depth):
        """The addresses at `depth` (a society's files, or its pages about the source) never asked, in order found."""
        return [r[0] for r in self.conn.execute(
            f"SELECT url FROM {self.T('capture_frontier')} WHERE host = %s AND depth = %s AND asked_at IS NULL "
            "ORDER BY found_at, url", (host, depth))]

    def frontier_asked(self, host, url, status):
        self.conn.execute(f"UPDATE {self.T('capture_frontier')} SET asked_at = now(), status = %s "
                          "WHERE host = %s AND url = %s", (status, host, url))


# ── a run ─────────────────────────────────────────────────────────────────────

LISTS = ("about", "dia-file", "lottery-page", "society-file")


class Blocked(RuntimeError):
    """This host blocked or challenged us: it is not asked again this run. `status` is the answer that blocked."""

    def __init__(self, why, status=None, asked=True):
        super().__init__(why)
        self.status, self.asked = status, asked


class Run:
    def __init__(self, tables, *, land_fn, fetch=None, clock=None, sleep=None, now=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_requests: int = 100000, anytime: bool = False,
                 lists=LISTS, societies=(), log=print):
        self.t, self.land_fn, self.log = tables, land_fn, log
        self.fetch = fetch or fetch_once
        self.clock = clock or time.monotonic
        self.pacer = fg.Pacer(now=self.clock, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.budget_s, self.max_requests, self.anytime, self.lists = budget_s, max_requests, anytime, lists
        self.societies = tuple(societies)
        self.started = self.clock()
        self.failures = {}
        self.blocked = {}
        self.run_id = None
        self.counts = {"requests": 0, "landed": 0, "already_held": 0, "set_aside": 0, "records_of_grants": 0,
                       "society_lists": 0, "before_window": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.counts["requests"] >= self.max_requests:
            self.stopped = self.stopped or "request budget spent"
            return False
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def aside(self, item, stage, reason):
        self.t.set_aside(self.run_id, item, stage, reason)
        self.counts["set_aside"] += 1

    def get(self, url: str, host: str):
        """One gated, paced request to `host` with no redirect followed: (status, body, location), or None after a
        failed read. Raises Blocked on a 403, 429 or challenge, or after three failed reads in a row."""
        if host in self.blocked:
            raise Blocked(self.blocked[host], asked=False)
        dec = fg.check(url, positions_dir=POSITIONS)          # a refusal raises fg.Refused and is never caught
        self.pacer.wait(dec.host, max(dec.floor, REST_S if self.failures.get(host) else FLOOR_S))
        self.counts["requests"] += 1
        try:
            status, body, _, location = self.fetch(url, 60)
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read
            return self.failed(url, host, f"transport: {type(exc).__name__}: {str(exc)[:200]}")
        if status in SERVER_ERRORS and not challenged(200, body):
            return self.failed(url, host, f"HTTP {status}: the server's own error; set aside, the run rests")
        self.failures[host] = 0
        why = challenged(status, body)
        if why:
            self.aside(url, "fetch", why)
            self.blocked[host] = why
            raise Blocked(why, status)
        return status, body, location

    def failed(self, url, host, why):
        self.failures[host] = self.failures.get(host, 0) + 1
        self.aside(url, "fetch", why)
        if self.failures[host] >= STOP_AFTER_FAILURES:
            self.blocked[host] = f"{self.failures[host]} failed reads in a row; the host may be in trouble"
            raise Blocked(self.blocked[host])
        return None

    def get_following(self, url, host, hops=3):
        """Follow a redirect on the same host, each hop asked of the gate; another host is left unasked."""
        for _ in range(hops + 1):
            got = self.get(url, host)
            if got is None:
                return None, url
            status, body, location = got
            if status in (301, 302, 303, 307, 308) and location:
                if site_of(fg.host_of(location)) != site_of(host):
                    self.aside(url, "fetch", f"redirects to {fg.host_of(location)}: not followed")
                    return None, url
                url, host = location, fg.host_of(location)
                continue
            return got, url
        self.aside(url, "fetch", "too many redirects")
        return None, url

    def land(self, body, url, lst, publisher):
        ref, new = self.land_fn(body, name=url, source=SOURCE, name_kind="url")
        slug = read.recognise(body)
        self.t.add_doc(self.run_id, lst, publisher, url, ref.sha256, slug, new)
        self.counts["landed" if new else "already_held"] += 1
        return ref.sha256, slug

    def due(self, lst, days, url=None):
        last = self.t.last(lst, url)
        return last is None or (dt.datetime.now(dt.timezone.utc) - last[0]).days >= days

    # the lists

    def about(self):
        if not self.due("about", ABOUT_EVERY_DAYS):
            return
        for name, (publisher, url) in ABOUT.items():
            if not self.time_left():
                return
            got, final = self.get_following(url, fg.host_of(url))
            if got is None or got[0] != 200:
                if got is not None:
                    self.aside(url, "about", f"HTTP {got[0]}")
                continue
            self.land(got[1], final, "about", publisher)

    def dia_file(self):
        if not self.due("dia-file-page", FILE_EVERY_DAYS) or not self.time_left():
            return
        host = fg.host_of(FILE_PAGE)
        got, final = self.get_following(FILE_PAGE, host)
        if got is None or got[0] != 200:
            if got is not None:
                self.aside(FILE_PAGE, "dia-file-page", f"HTTP {got[0]}")
            return
        held = self.t.last("dia-file-page")
        self.land(got[1], final, "dia-file-page", read.DIA)
        found = FILE_LINK.findall(got[1].decode("utf-8", "replace"))
        if not found:
            self.aside(FILE_PAGE, "dia-file-page", "the package page links no class 4 grants CSV; nothing asked")
            return
        url = html.unescape(found[0])
        last = self.t.last("dia-file", url)
        page_same = held is not None and held[1] == self.t.last("dia-file-page")[1]
        if last is not None and page_same:
            return                                           # the page and its link unchanged: the file is held
        if not self.time_left():
            return
        got, final = self.get_following(url, host)
        if got is None or got[0] != 200:
            if got is not None:
                self.aside(url, "dia-file", f"HTTP {got[0]}")
            return
        sha, slug = self.land(got[1], final, "dia-file", read.DIA)
        if slug != read.DIA_CSV:
            self.aside(url, "dia-file", "the file landed is not the profile's shape; the reading will set it aside")

    def walk_one(self, url, host):
        """One page of a walk. A page that blocks is marked asked, with the status that blocked, before the block
        stops the host: else it stays first in the frontier and every later run opens on it and stops (the first
        walk of 22 October 2026 met a 403 on its sixteenth page)."""
        try:
            got, final = self.get_following(url, host)
        except Blocked as exc:
            if exc.asked:
                self.t.frontier_asked(host, url, exc.status)
            raise
        self.t.frontier_asked(host, url, got[0] if got else None)
        return got, final

    def lottery_pages(self):
        host = CM_HOST
        self.t.frontier_add(host, [canonical(CM_HOME)], 0)
        while self.time_left():
            batch = self.t.frontier_next(host, 50, RECRAWL_DAYS)
            if not batch:
                return
            for url, depth in batch:
                if not self.time_left():
                    return
                got, final = self.walk_one(url, host)
                if got is None:
                    continue
                status, body, _ = got
                if status != 200:
                    if status != 404:
                        self.aside(url, "lottery-page", f"HTTP {status}")
                    continue
                if b"<html" not in body[:4096].lower():
                    continue
                sha, slug = self.land(body, final, "lottery-page", read.LOTTERY)
                if slug == read.LOTTERY_PAGE:
                    self.counts["records_of_grants"] += 1
                self.t.frontier_add(host, links(final, body, host), depth + 1)

    def society_files(self):
        """Each class A society's grants page, the grants pages it links (to `SOCIETY_DEPTH`), every grants file they
        link landed once, and the society's terms, copyright or privacy page landed under `about` before its first
        file. A block stops that society's site, not the run."""
        for key, start in SOCIETY_SITES.items():
            if self.societies and key not in self.societies:
                continue
            if not self.time_left():
                return
            try:
                self.society(key, start)
            except Blocked as exc:
                self.log(f"{SOURCE}: society-file {key}: stopped for this site: {exc}")
                self.stopped = (self.stopped + "; " if self.stopped else "") + f"{key} stopped: {exc}"

    def society(self, key, start):
        """The walk keeps what it finds in the frontier: pages at their depth from the grants page, files at
        `FILE_DEPTH` and the pages about the source at `ABOUT_DEPTH`, so a run cut short leaves nothing found
        unasked for long. A file is asked once; a page again after `RECRAWL_DAYS`."""
        host = fg.host_of(start)
        self.t.frontier_add(host, [canonical(start)], 0)
        seen = set()
        while self.time_left():
            batch = [(u, d) for u, d in self.t.frontier_next(host, 50, RECRAWL_DAYS)
                     if 0 <= d <= SOCIETY_DEPTH and u not in seen]
            if not batch:
                break
            for url, depth in batch:
                seen.add(url)
                if not self.time_left():
                    return
                got, final = self.walk_one(url, host)
                if got is None:
                    continue
                status, body, _ = got
                if status != 200:
                    if status != 404:
                        self.aside(url, "society-page", f"HTTP {status}")
                    continue
                if b"<html" not in body[:4096].lower():
                    continue
                self.land(body, final, "society-page", key)
                pages, files, about = society_links(final, body)
                self.t.frontier_add(host, [on_host(p, host) for p in pages], depth + 1)
                self.t.frontier_add(host, files, FILE_DEPTH)
                self.t.frontier_add(host, about, ABOUT_DEPTH)
        if not self.t.last("about", None, key):
            for url in self.t.frontier_unasked(host, ABOUT_DEPTH)[:2]:
                if not self.time_left():
                    return
                got, final = self.walk_one(url, host)
                if got is not None and got[0] == 200:
                    self.land(got[1], final, "about", key)
        for url in self.t.frontier_unasked(host, FILE_DEPTH):
            if before_window(url):
                self.counts["before_window"] += 1
                continue
            if self.t.last("society-file", url) is not None:
                self.t.frontier_asked(host, url, 200)
                self.counts["already_held"] += 1
                continue
            if not self.time_left():
                return
            got, final = self.walk_one(url, host)
            if got is None:
                continue
            if got[0] != 200:
                self.aside(url, "society-file", f"HTTP {got[0]}")
                continue
            sha, slug = self.land(got[1], url, "society-file", key)
            if slug:
                self.counts["society_lists"] += 1

    def run(self) -> dict:
        self.run_id = self.t.begin()
        steps = {"about": self.about, "dia-file": self.dia_file, "lottery-page": self.lottery_pages,
                 "society-file": self.society_files}
        for name in self.lists:
            try:
                steps[name]()
            except Blocked as exc:
                self.log(f"{SOURCE}: {name}: stopped for this host: {exc}")
                self.stopped = (self.stopped + "; " if self.stopped else "") + f"{name} stopped: {exc}"
        self.t.finish(self.run_id, self.counts, self.stopped)
        return {**self.counts, "stopped": self.stopped, "blocked_hosts": sorted(self.blocked)}


def outcome(out: dict):
    """(ok, last words): a host that blocked is red only when nothing at all landed in the run."""
    if out["blocked_hosts"] and not (out["landed"] or out["already_held"]):
        return False, out["stopped"] + "; nothing landed"
    return True, out["stopped"] or "done"


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.grants.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--list", action="append", choices=list(LISTS))
    ap.add_argument("--society", action="append", choices=sorted(SOCIETY_SITES))
    ap.add_argument("--max-requests", type=int, default=100000)
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db, jobrun
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            return 0
        out = Run(t, land_fn=landing(conn), anytime=a.anytime, max_requests=a.max_requests, budget_s=a.budget_s,
                  lists=tuple(a.list or LISTS), societies=a.society or ()).run()
    ok, last = outcome(out)
    detail = (f"{out['requests']} requests, {out['landed']} landed, {out['already_held']} already held, "
              f"{out['records_of_grants']} records of grants met, {out['society_lists']} society lists landed, "
              f"{out['set_aside']} set aside; {last}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
