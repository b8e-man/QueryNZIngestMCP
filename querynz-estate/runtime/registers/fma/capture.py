"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only.

The Financial Markets Authority publishes two lists of its actions on
`www.fma.govt.nz`: its warnings and alerts (`/library/warnings-and-alerts/`,
"the names of businesses or individuals you should be wary of", 726 on 21
October 2026) and its enforcement cases (`/about-us/enforcement/cases/`, 99).
Each list shows fifteen items a page, newest first, `?start=15`, `?start=30`,
…, and states its own count ("726 results found"). The old estate held 16
warnings (`ingestion/fma/scraper.py`, the first listing page only, its text
then sent to a model; this lane reads the page's own heading, date and
labelled fields and calls no model). The position on file is
`position/fma-warnings-and-enforcement.md` (the integrator moves it to
`docs/legal/positions/`): copyright the FMA's, licensed CC BY 4.0.

A run, in order:

  1. the documents about the source (the copyright licence, the privacy
     statement), at most every 30 days;
  2. a pass over each list, at most weekly, resuming from its next page:
     every listing page landed by its hash, every item listed with its
     fingerprint (its date and title as listed);
  3. the items listed and not held under that fingerprint, in listing
     order: an item is fetched once, and again only when the list shows it
     with a new date or title (the FMA re-dates a case it updates).

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` apart
(no robots file is published, so no crawl delay is stated; the gate's own
floor binds too), off-peak (22:00 to 06:00 NZ time) unless `--anytime`, a
budget per run. A 403, 429 or a challenge page is a block (hard limit 6):
logged, and the run STOPS. A 500, 502, 503 or 504 with no challenge on the
page is the server's own error: a failed read set aside, the run rests
`REST_S` and goes on. A transport failure is a failed read too. Three failed
reads in a row stop the run. A redirect to another host stops it. A gate
refusal is never caught. A run that stops early after landing something
exits green with a "stopped early" line; red only when nothing landed.

    python -m registers.fma.capture [--anytime] [--max-items N] [--max-pages N] [--budget-s N]
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.fma import read

SOURCE = SCHEMA = "fma"
JOB = "qv4-fma-capture"
HOST = "www.fma.govt.nz"
BASE = f"https://{HOST}"
FLOOR_S = 5.0
REST_S = 60.0
OFF_PEAK = (22, 6)
FULL_EVERY_DAYS = 7
DOCS_EVERY_DAYS = 30
DEFAULT_BUDGET_S = 4 * 3600
STOP_AFTER_FAILURES = 3
SERVER_ERRORS = (500, 502, 503, 504)
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: where the position is read from. Until the integrator moves `position/fma-warnings-and-enforcement.md` to
#: docs/legal/positions/, a session runs with QV4_POSITIONS pointing at this lane's position folder.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
READING = "-- ── the reading"


class List:
    """One listing the lane walks: its pages, its reader, its items' recogniser."""

    def __init__(self, name, page_url, per_page, read_listing, recognise_item):
        self.name, self.page_url, self.per_page = name, page_url, per_page
        self.read_listing, self.recognise_item = read_listing, recognise_item


LISTS = (
    List("warnings", lambda n: read.list_url("warnings", n), read.PER_PAGE,
         lambda body: read.read_listing(body, "warnings"), read.recognise_page),
    List("enforcement", lambda n: read.list_url("enforcement", n), read.PER_PAGE,
         lambda body: read.read_listing(body, "enforcement"), read.recognise_page),
)
DOCS = {
    "copyright": f"{BASE}/copyright/",
    "privacy": f"{BASE}/privacy/",
}


# ── pure pieces ───────────────────────────────────────────────────────────────

def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    """The lane's own schema holds its tables by their names; any other (a
    session's scratch schema, a staging schema) carries the lane's prefix."""
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}(_private)?\.")


def capture_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read().split(READING)[0]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(lambda m: f"{schema}{'_private' if m.group(1) and schema == SCHEMA else ''}.{pre}", text)


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

    def _pass(self, row):
        if row is None:
            return None
        return dict(zip(("pass_id", "list", "stated", "next_page", "pages", "items"), row))

    def open_pass(self, name):
        return self._pass(self.conn.execute(
            f"SELECT pass_id, list, stated, next_page, pages, items FROM {self.T('capture_passes')} "
            "WHERE list = %s AND finished_at IS NULL ORDER BY pass_id DESC LIMIT 1", (name,)).fetchone())

    def last_finished(self, name):
        return self.conn.execute(f"SELECT max(finished_at) FROM {self.T('capture_passes')} WHERE list = %s",
                                 (name,)).fetchone()[0]

    def begin(self, name):
        return self._pass(self.conn.execute(
            f"INSERT INTO {self.T('capture_passes')} (list) VALUES (%s) "
            "RETURNING pass_id, list, stated, next_page, pages, items", (name,)).fetchone())

    def add_page(self, p, page_no, url, sha, items, stated):
        self.conn.execute(f"INSERT INTO {self.T('capture_pages')} (pass_id, page_no, url, sha256, items) "
                          "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (p["pass_id"], page_no, url, sha, len(items)))
        for i, it in enumerate(items):
            self.conn.execute(f"INSERT INTO {self.T('capture_listed')} (pass_id, list, slug, url, card, ordinal) "
                              "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                              (p["pass_id"], p["list"], it["slug"], it["url"], it["card"], (page_no - 1) * 1000 + i))
        n = self.conn.execute(f"SELECT count(*) FROM {self.T('capture_listed')} WHERE pass_id = %s",
                              (p["pass_id"],)).fetchone()[0]
        p.update(next_page=page_no + 1, pages=p["pages"] + 1, items=n, stated=p["stated"] if p["stated"] else stated)
        self.conn.execute(f"UPDATE {self.T('capture_passes')} SET next_page = %s, pages = %s, items = %s, stated = %s "
                          "WHERE pass_id = %s", (p["next_page"], p["pages"], p["items"], p["stated"], p["pass_id"]))

    def finish(self, p):
        self.conn.execute(f"UPDATE {self.T('capture_passes')} SET finished_at = now() WHERE pass_id = %s", (p["pass_id"],))

    def pending(self, name, limit):
        """Listed in the newest pass that listed anything, and not held under the card listed."""
        return [tuple(r) for r in self.conn.execute(
            f"SELECT l.slug, l.url, l.card FROM {self.T('capture_listed')} l "
            f"WHERE l.pass_id = (SELECT max(pass_id) FROM {self.T('capture_listed')} WHERE list = %s) "
            f"AND NOT EXISTS (SELECT 1 FROM {self.T('capture_items')} i WHERE i.list = l.list AND i.slug = l.slug "
            "AND i.card = l.card) ORDER BY l.ordinal LIMIT %s", (name, limit))]

    def add_item(self, name, slug, url, card, sha):
        self.conn.execute(f"INSERT INTO {self.T('capture_items')} (list, slug, url, card, sha256) VALUES "
                          "(%s, %s, %s, %s, %s) ON CONFLICT (list, slug, sha256) DO UPDATE SET card = EXCLUDED.card, "
                          "at = now()", (name, slug, url, card, sha))

    def docs_due(self, days) -> bool:
        last = self.conn.execute(f"SELECT max(at) FROM {self.T('capture_docs')}").fetchone()[0]
        return last is None or (dt.datetime.now(dt.timezone.utc) - last).days >= days

    def add_doc(self, name, url, sha, new):
        self.conn.execute(f"INSERT INTO {self.T('capture_docs')} (name, url, sha256, new) VALUES (%s, %s, %s, %s)",
                          (name, url, sha, new))

    def set_aside(self, pass_id, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.T('capture_set_aside')} (pass_id, item, stage, reason) "
                          "VALUES (%s, %s, %s, %s)", (pass_id, str(item), stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Stop(RuntimeError):
    """The run stops here: a block, a challenge, the host not answering, or a page not to be trusted."""


class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_items: int = 100000, max_pages: int = 1000,
                 anytime: bool = False, lists=LISTS, docs=DOCS, log=print):
        self.t, self.land_fn, self.log = tables, land_fn, log
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.clock = clock or time.monotonic
        self.pacer = fg.Pacer(now=self.clock, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.budget_s, self.max_items, self.max_pages, self.anytime = budget_s, max_items, max_pages, anytime
        self.lists, self.docs = lists, docs
        self.started = self.clock()
        self.failures = 0
        self.tried = set()
        self.counts = {"requests": 0, "pages": 0, "listed": 0, "passes_finished": 0, "items": 0, "landed": 0,
                       "already_held": 0, "docs": 0, "set_aside": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def aside(self, pass_id, item, stage, reason):
        self.t.set_aside(pass_id, item, stage, reason)
        self.counts["set_aside"] += 1

    def get(self, url: str, pass_id=None):
        """One gated, paced request: the answer, or None after a failed read
        (set aside, the next request resting `REST_S`). Raises Stop on a block,
        a challenge, another host, or three failed reads in a row."""
        self.pacer.wait(HOST, REST_S if self.failures else FLOOR_S)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, 60)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read, never the end of the night
            return self.failed(url, pass_id, f"transport: {type(exc).__name__}: {str(exc)[:200]}")
        if f.status in SERVER_ERRORS and not fg.looks_challenged(200, f.body):
            return self.failed(url, pass_id, f"HTTP {f.status}: the server's own error; set aside, the run rests")
        self.failures = 0
        if f.blocked:
            self.aside(pass_id, url, "fetch", f.blocked)
            raise Stop(f.blocked)
        if fg.host_of(f.final_url or url) != HOST:
            why = f"redirected to {fg.host_of(f.final_url)}: not landed, and the run stops"
            self.aside(pass_id, url, "fetch", why)
            raise Stop(why)
        return f

    def failed(self, url, pass_id, why):
        self.failures += 1
        self.aside(pass_id, url, "fetch", why)
        if self.failures >= STOP_AFTER_FAILURES:
            raise Stop(f"{self.failures} failed reads in a row; the host may be in trouble")
        return None

    def land(self, f):
        return self.land_fn(f.body, name=f.url, source=SOURCE, name_kind="url", content_type="text/html")

    def land_docs(self):
        if not self.t.docs_due(DOCS_EVERY_DAYS):
            return
        for name, url in self.docs.items():
            if not self.time_left():
                return
            f = self.get(url)
            if f is None or f.status != 200:
                if f is not None:
                    self.aside(None, url, "doc", f"HTTP {f.status}")
                continue
            ref, new = self.land(f)
            self.t.add_doc(name, url, ref.sha256, new)
            self.counts["docs"] += 1

    def walk(self, lst):
        """A pass over one listing, resumed from its next page; a new pass at most every FULL_EVERY_DAYS."""
        p = self.t.open_pass(lst.name)
        if p is None:
            last = self.t.last_finished(lst.name)
            if last is not None and (dt.datetime.now(dt.timezone.utc) - last).days < FULL_EVERY_DAYS:
                return
            p = self.t.begin(lst.name)
        walked = 0
        while self.time_left() and walked < self.max_pages:
            n = p["next_page"]
            url = lst.page_url(n)
            f = self.get(url, p["pass_id"])
            if f is None:
                return
            if f.status != 200:
                self.aside(p["pass_id"], url, "listing", f"HTTP {f.status}")
                return
            try:
                out = lst.read_listing(f.body)
            except ValueError as exc:
                self.aside(p["pass_id"], url, "listing", f"not the listing's shape: {exc}")
                raise Stop(f"a listing page of {lst.name} is not its shape")
            ref, _ = self.land(f)
            self.t.add_page(p, n, url, ref.sha256, out["items"], out["stated"])
            self.counts["pages"] += 1
            walked += 1
            self.counts["listed"] += len(out["items"])
            if len(out["items"]) < lst.per_page or (p["stated"] and p["items"] >= p["stated"]):
                self.t.finish(p)
                self.counts["passes_finished"] += 1
                self.log(f"{SOURCE}: {lst.name}: pass {p['pass_id']} finished, {p['items']} listed of {p['stated']}")
                return

    def fetch(self, lst):
        while self.counts["items"] < self.max_items and self.time_left():
            batch = [r for r in self.t.pending(lst.name, 100 + len(self.tried)) if (lst.name, r[0]) not in self.tried]
            if not batch:
                return
            for slug, url, card in batch:
                if self.counts["items"] >= self.max_items or not self.time_left():
                    return
                self.tried.add((lst.name, slug))
                self.counts["items"] += 1
                f = self.get(url)
                if f is None:
                    continue
                if f.status != 200:
                    self.aside(None, url, "item", f"HTTP {f.status}")
                    continue
                why = lst.recognise_item(f.body)
                if why:
                    self.aside(None, url, "item", f"not the item's shape: {why}; not landed")
                    continue
                ref, new = self.land(f)
                self.t.add_item(lst.name, slug, url, card, ref.sha256)
                self.counts["landed" if new else "already_held"] += 1

    def run(self) -> dict:
        try:
            self.land_docs()
            for lst in self.lists:
                self.walk(lst)
            for lst in self.lists:
                self.fetch(lst)
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def outcome(out: dict):
    """(ok, the last words of the run's line): a polite early stop after
    landing something is green; red only when it stopped with nothing landed."""
    stopped = out["stopped"]
    if not stopped.startswith("stopped:"):
        return True, stopped or "done"
    if out["pages"] or out["landed"] or out["already_held"] or out["docs"]:
        return True, "stopped early: " + stopped[len("stopped:"):].strip()
    return False, stopped + "; nothing landed"


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.fma.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--max-items", type=int, default=100000)
    ap.add_argument("--max-pages", type=int, default=1000, help="listing pages per list per run")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--list", choices=[x.name for x in LISTS], help="walk and fetch this list only")
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
        out = Run(t, land_fn=landing(conn), anytime=a.anytime, max_items=a.max_items, max_pages=a.max_pages,
                  budget_s=a.budget_s, lists=[x for x in LISTS if a.list in (None, x.name)]).run()
    ok, last = outcome(out)
    detail = (f"{out['requests']} requests, {out['pages']} listing pages ({out['listed']} listed), "
              f"{out['passes_finished']} passes finished, {out['items']} items tried, {out['landed']} landed, "
              f"{out['already_held']} already held, {out['docs']} documents about the source, "
              f"{out['set_aside']} set aside; {last}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
