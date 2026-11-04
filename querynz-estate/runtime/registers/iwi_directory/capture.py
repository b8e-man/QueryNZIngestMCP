"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only.

Te Kāhui Māngai (`www.tkm.govt.nz`, Te Puni Kōkiri) is walked whole from its
home page (the whole-site doctrine): every page of the site a page links is
landed by its hash, each once a walk, the walk at most weekly. On 22 October
2026 the site had 13 region maps linking 117 iwi pages, 92 local and regional
authority pages, the other organisations and non-tribal marae pages, and its
about, copyright, disclaimer, privacy and glossary pages: about 240 pages.
What is not asked: files (the rohe maps' PDFs and pictures), the search and
contact forms, and addresses carrying a query. The position on file is
`position/iwi-and-hapu-directory.md` (the integrator moves it).

A run: resume the open walk, or begin one if the last finished walk is a
week old; take the frontier in the order found; land each page, recognise its
shape, and add the site's own links it carries. Seeds: the home page and the
site's navigation and footer pages, so a page no link reaches is still asked.

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` apart
(robots states no crawl delay; the gate's own floor binds too), off-peak
(22:00 to 06:00 NZ time) unless `--anytime`, a budget per run. A 403, 429 or a
challenge page is a block (hard limit 6): logged, and the run STOPS. A 5xx
with no challenge on the page is the server's own error: set aside, the run
rests `REST_S` and goes on. Three failed reads in a row stop the run. A
redirect to another host is not followed. A gate refusal is never caught. A
run that stops early after landing something exits green with a "stopped
early" line; red only when nothing landed.

    python -m registers.iwi_directory.capture [--anytime] [--max-pages N] [--budget-s N]
"""
import argparse
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.iwi_directory import read

SOURCE = SCHEMA = "iwi_directory"
JOB = "qv4-iwi-directory-capture"
HOST = "www.tkm.govt.nz"
BASE = f"https://{HOST}"
FLOOR_S = 5.0
REST_S = 60.0
OFF_PEAK = (22, 6)
FULL_EVERY_DAYS = 7
DEFAULT_BUDGET_S = 2 * 3600
STOP_AFTER_FAILURES = 3
MAX_PAGES_A_WALK = 1500
SERVER_ERRORS = (500, 502, 503, 504)
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: until the integrator moves `position/iwi-and-hapu-directory.md` to docs/legal/positions/, a session runs with
#: QV4_POSITIONS pointing at a folder holding it.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
READING = "-- ── the reading"
SEEDS = ("/", "/map/", "/browse/", "/omo/", "/marae/", "/NonTribalMarae/", "/glossary/", "/disclaimer/", "/about/",
         "/copyright/", "/privacy/", "/accessibility/", "/links/")
#: not pages, or forms: never asked (the first path segment, lower case)
NOT_ASKED_DIRS = ("search", "contact", "rohe", "images", "bin", "styles", "scripts", "js", "css")
FILE = re.compile(r"\.(pdf|jpe?g|png|gif|svg|ico|css|js|zip|docx?|xlsx?|kml|kmz)$", re.I)


# ── pure pieces ───────────────────────────────────────────────────────────────

def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    """The lane's own schema holds its tables by their names; any other (a session's scratch schema, a staging
    schema) carries the lane's prefix."""
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}\.")


def capture_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read().split(READING)[0]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(f"{schema}.{pre}", text)


def classify(url: str):
    """(the address to ask, '') for a page of the site; (url, why) for one never asked; (None, why) off the site."""
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in (HOST, HOST[4:]):
        return None, "off the site"
    path = p.path or "/"
    if FILE.search(path):
        return url, "a file, not a page"
    first = path.strip("/").split("/", 1)[0].lower()
    if first in NOT_ASKED_DIRS:
        return url, "a form, a map or a picture"
    if p.query:
        return url, "an address carrying a query"
    if not path.endswith("/"):
        path += "/"
    return f"{BASE}{path}", ""


def links_of(body: bytes, page_url: str) -> list:
    """The site's own links a page carries, in page order, each once: (address, why not asked or '')."""
    page = body.decode("utf-8", "replace")
    out, seen = [], set()
    for h in re.findall(r"href=[\"']([^\"'#]+)", page):
        h = html.unescape(h).strip()
        if h.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        url, why = classify(urllib.parse.urljoin(page_url, h))
        if url is None or url in seen:
            continue
        seen.add(url)
        out.append((url, why))
    return out


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

    def open_pass(self):
        r = self.conn.execute(f"SELECT pass_id FROM {self.T('capture_passes')} WHERE finished_at IS NULL "
                              "ORDER BY pass_id DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def last_finished(self):
        return self.conn.execute(f"SELECT max(finished_at) FROM {self.T('capture_passes')}").fetchone()[0]

    def begin(self, seeds):
        pid = self.conn.execute(f"INSERT INTO {self.T('capture_passes')} DEFAULT VALUES RETURNING pass_id").fetchone()[0]
        for s in seeds:
            self.add(pid, s, None, "")
        return pid

    def add(self, pid, url, found_on, why):
        n = self.conn.execute(f"SELECT count(*) FROM {self.T('capture_frontier')} WHERE pass_id = %s", (pid,)).fetchone()[0]
        self.conn.execute(f"INSERT INTO {self.T('capture_frontier')} (pass_id, url, ordinal, found_on, state, why) "
                          "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                          (pid, url, n, found_on, "not asked" if why else "todo", why or None))

    def next_todo(self, pid):
        r = self.conn.execute(f"SELECT url FROM {self.T('capture_frontier')} WHERE pass_id = %s AND state = 'todo' "
                              "ORDER BY ordinal LIMIT 1", (pid,)).fetchone()
        return r[0] if r else None

    def mark(self, pid, url, state, kind=None, sha=None, why=None):
        self.conn.execute(f"UPDATE {self.T('capture_frontier')} SET state = %s, kind = %s, sha256 = %s, why = %s, "
                          "at = now() WHERE pass_id = %s AND url = %s", (state, kind, sha, why, pid, url))
        if state == "landed":
            self.conn.execute(f"UPDATE {self.T('capture_passes')} SET pages = pages + 1 WHERE pass_id = %s", (pid,))

    def finish(self, pid):
        self.conn.execute(f"UPDATE {self.T('capture_passes')} SET finished_at = now() WHERE pass_id = %s", (pid,))

    def set_aside(self, pid, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.T('capture_set_aside')} (pass_id, item, stage, reason) "
                          "VALUES (%s, %s, %s, %s)", (pid, str(item), stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Stop(RuntimeError):
    """The run stops here: a block, a challenge, the host not answering."""


class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_pages: int = MAX_PAGES_A_WALK, anytime: bool = False,
                 seeds=SEEDS, log=print):
        self.t, self.land_fn, self.log = tables, land_fn, log
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.clock = clock or time.monotonic
        self.pacer = fg.Pacer(now=self.clock, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.budget_s, self.max_pages, self.anytime = budget_s, max_pages, anytime
        self.seeds = [BASE + s for s in seeds]
        self.started = self.clock()
        self.failures = 0
        self.counts = {"requests": 0, "landed": 0, "already_held": 0, "set_aside": 0, "found": 0, "finished": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def get(self, url: str, pid):
        """One gated, paced request: the answer, or None after a failed read (set aside). Raises Stop on a block,
        a challenge, or three failed reads in a row."""
        self.pacer.wait(HOST, REST_S if self.failures else FLOOR_S)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, 60)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read, never the end of the night
            return self.failed(url, pid, f"transport: {type(exc).__name__}: {str(exc)[:200]}")
        if f.status in SERVER_ERRORS and not fg.looks_challenged(200, f.body):
            return self.failed(url, pid, f"HTTP {f.status}: the server's own error; set aside, the run rests")
        self.failures = 0
        if f.blocked:
            self.t.mark(pid, url, "set aside", why=f.blocked)
            self.t.set_aside(pid, url, "fetch", f.blocked)
            self.counts["set_aside"] += 1
            raise Stop(f.blocked)
        return f

    def failed(self, url, pid, why):
        self.failures += 1
        self.t.mark(pid, url, "set aside", why=why)
        self.t.set_aside(pid, url, "fetch", why)
        self.counts["set_aside"] += 1
        if self.failures >= STOP_AFTER_FAILURES:
            raise Stop(f"{self.failures} failed reads in a row; the host may be in trouble")
        return None

    def page(self, pid, url):
        f = self.get(url, pid)
        if f is None:
            return
        if f.status != 200 or not f.body:
            why = f"HTTP {f.status}" + (f", redirected to {f.location}: not followed" if f.location else "")
            self.t.mark(pid, url, "set aside", why=why)
            self.t.set_aside(pid, url, "fetch", why)
            self.counts["set_aside"] += 1
            return
        try:
            kind = read.recognise(f.body)
        except read.NotTheShape as exc:
            self.t.mark(pid, url, "set aside", why=str(exc))
            self.t.set_aside(pid, url, "shape", str(exc))
            self.counts["set_aside"] += 1
            return
        ref, new = self.land_fn(f.body, name=url, source=SOURCE, name_kind="url", content_type="text/html")
        self.t.mark(pid, url, "landed", kind=kind, sha=ref.sha256)
        self.counts["landed" if new else "already_held"] += 1
        for link, why in links_of(f.body, url):
            self.t.add(pid, link, url, why)
            self.counts["found"] += 1

    def run(self) -> dict:
        try:
            pid = self.t.open_pass()
            if pid is None:
                last = self.t.last_finished()
                if last is not None and (dt.datetime.now(dt.timezone.utc) - last).days < FULL_EVERY_DAYS:
                    return {**self.counts, "stopped": "the last walk is under a week old"}
                pid = self.t.begin(self.seeds)
            asked = 0
            while self.time_left() and asked < self.max_pages:
                url = self.t.next_todo(pid)
                if url is None:
                    self.t.finish(pid)
                    self.counts["finished"] += 1
                    self.log(f"{SOURCE}: walk {pid} finished")
                    break
                asked += 1
                self.page(pid, url)
            else:
                if asked >= self.max_pages:
                    self.stopped = self.stopped or f"the page cap ({self.max_pages}) reached; the walk resumes next run"
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def outcome(out: dict):
    """(ok, the last words of the run's line): a polite early stop after landing something is green; red only when
    it stopped with nothing landed."""
    stopped = out["stopped"]
    if not stopped.startswith("stopped:"):
        return True, stopped or "done"
    if out["landed"] or out["already_held"]:
        return True, "stopped early: " + stopped[len("stopped:"):].strip()
    return False, stopped + "; nothing landed"


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.iwi_directory.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES_A_WALK)
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
        out = Run(t, land_fn=landing(conn), anytime=a.anytime, max_pages=a.max_pages, budget_s=a.budget_s).run()
    ok, last = outcome(out)
    detail = (f"{out['requests']} requests, {out['landed']} landed, {out['already_held']} already held, "
              f"{out['set_aside']} set aside, {out['found']} links found, {out['finished']} walks finished; {last}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
