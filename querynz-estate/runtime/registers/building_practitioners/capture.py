"""How this lane's documents arrive: case 3 of plan 1.10, one capture of its
own, politely, through the fetch gate and the landing wrapper only.

Two sources under part 4 of the Building Act 2004, on two footings:

1. The Building Practitioners Board's published complaint decisions, the
   list at `www.lbp.govt.nz/complaints-and-past-decisions/past-complaint-decisions/`:
   twenty decisions a page, newest first, `?start=20`, `?start=40`, …; the
   first page states the total ("Displaying 20 of 1600 results", 21 October
   2026), which the pass reconciles to. These are the Board's own
   publications, not searches of the register; the site's copyright grant
   lets them be "used, copied and re-distributed free of charge in any
   format", attributed. Captured: a full pass weekly, every page landed
   verbatim by hash. The decision PDFs the pages link to are not fetched
   (a card; the list carries every field the lane reads).

2. The register of licensed building practitioners itself (the search at
   `kete-lbp.mbie.govt.nz`): copied on ruling 132 (Arthur, 2 November 2026),
   recorded as the position's line `authorised: register <date> <how>`;
   without that line it is asked nothing (`register()` raises Held). Its
   capture and reading are `register.py`, run as `--register`.

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` apart
(the robots file states no crawl delay for us; the gate's floor binds too),
off-peak (22:00 to 06:00 NZ time) unless `--anytime`, a full pass at most
weekly. A 403, 429, 5xx or a challenge page is a failed read (hard limit 6):
a catch-log line and the run stops; the pass resumes from its next page on
the next run. Three transport failures in a row stop the run. Every line
printed is a count.

    python -m registers.building_practitioners.capture [--anytime] [--max-pages N]
    python -m registers.building_practitioners.capture --register [--anytime]   # the register (register.py)
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import support.fetchgate as fg

SOURCE = SCHEMA = "building_practitioners"
JOB = "qv4-building-practitioners-capture"
HOST = "www.lbp.govt.nz"
LIST_URL = f"https://{HOST}/complaints-and-past-decisions/past-complaint-decisions/"
REGISTER_URL = "https://kete-lbp.mbie.govt.nz/advanced-building-practitioner-search/"
PER_PAGE = 20
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
FULL_EVERY_DAYS = 7
DEFAULT_BUDGET_S = 3600
STOP_AFTER_FAILURES = 3
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: where the position is read from. Until the integrator moves `position/building-practitioners-register.md` to
#: docs/legal/positions/, a session runs with QV4_POSITIONS pointing at this lane's position folder.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
#: the documents about the source, landed with each full pass: the terms, the privacy statement, the register's own
#: statement of s 307, the statute
DOCS = {
    "copyright": f"https://{HOST}/about-us/copyright/",
    "privacy": f"https://{HOST}/about-us/privacy/",
    "register-search-page": REGISTER_URL,
}
_TOTAL = re.compile(rb"Displaying\s*<span[^>]*>\s*(\d+)\s*</span>\s*of\s*(\d+)\s*results", re.I)


class Held(RuntimeError):
    """The register is held: the position records no authorisation."""


class Stop(RuntimeError):
    """The run stops here: a block, a challenge, the host not answering, or a page not to be trusted."""


# ── pure pieces ───────────────────────────────────────────────────────────────

def page_url(start: int) -> str:
    return LIST_URL if start == 0 else f"{LIST_URL}?start={int(start)}"


def stated_total(body: bytes):
    """(shown, total) from a list page's own heading, or None."""
    m = _TOTAL.search(body)
    return (int(m.group(1)), int(m.group(2))) if m else None


def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def authorisation(what: str, positions_dir: str = None):
    """The position's `authorised: <what> …` line, or None."""
    folder = positions_dir or POSITIONS or fg.POSITIONS_DIR
    for host in ("kete-lbp.mbie.govt.nz", HOST):
        cls = fg.position_for(host, folder)
        if not cls:
            continue
        try:
            with open(os.path.join(folder, cls + ".md"), encoding="utf-8") as f:
                m = re.search(rf"^authorised:\s*{re.escape(what)}\s+(\S.*)$", f.read(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1)
    return None


def plan_pass(open_pass, last_full_done, now: dt.datetime) -> str:
    if open_pass is not None:
        return "resume"
    if last_full_done is None or now - last_full_done >= dt.timedelta(days=FULL_EVERY_DAYS):
        return "full"
    return "skip"


# ── the lane's capture tables ─────────────────────────────────────────────────

READING = "-- ── the reading"


def tables_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        return f.read().split(READING)[0].replace(f"{SCHEMA}.", f"{schema}.")


class Tables:
    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema

    def create(self):
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s}")
        self.conn.execute(tables_sql(self.s))

    def try_lock(self) -> bool:
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def open_pass(self):
        r = self.conn.execute(f"SELECT pass_id, next_start, pages, stated FROM {self.s}.capture_passes "
                              "WHERE finished_at IS NULL ORDER BY pass_id DESC LIMIT 1").fetchone()
        return None if r is None else {"pass_id": r[0], "next_start": r[1], "pages": r[2], "stated": r[3]}

    def last_full_done(self):
        r = self.conn.execute(f"SELECT max(finished_at) FROM {self.s}.capture_passes WHERE finished_at IS NOT NULL").fetchone()
        return r[0] if r else None

    def begin(self) -> dict:
        pid = self.conn.execute(f"INSERT INTO {self.s}.capture_passes DEFAULT VALUES RETURNING pass_id").fetchone()[0]
        return {"pass_id": pid, "next_start": 0, "pages": 0, "stated": None}

    def add_page(self, p, start, url, sha, items, new, stated):
        p["pages"] += 1
        self.conn.execute(f"INSERT INTO {self.s}.capture_pages (pass_id, page_no, start, url, sha256, items, new) "
                          "VALUES (%s, %s, %s, %s, %s, %s, %s)", (p["pass_id"], p["pages"], start, url, sha, items, new))
        self.conn.execute(f"UPDATE {self.s}.capture_passes SET pages = pages + 1, items = items + %s, next_start = %s, "
                          "stated = COALESCE(stated, %s) WHERE pass_id = %s",
                          (items, start + PER_PAGE, stated, p["pass_id"]))
        p["next_start"] = start + PER_PAGE
        p["stated"] = p["stated"] or stated

    def add_doc(self, name, url, sha, new):
        self.conn.execute(f"INSERT INTO {self.s}.capture_docs (name, url, sha256, new) VALUES (%s, %s, %s, %s)",
                          (name, url, sha, new))

    def finish(self, p):
        self.conn.execute(f"UPDATE {self.s}.capture_passes SET finished_at = now() WHERE pass_id = %s", (p["pass_id"],))

    def set_aside(self, pass_id, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.s}.capture_set_aside (pass_id, item, stage, reason) VALUES (%s, %s, %s, %s)",
                          (pass_id, item, stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_pages: int = 1000, anytime: bool = False, log=print):
        self.t, self.land_fn = tables, land_fn
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.budget_s, self.max_pages, self.anytime, self.log = budget_s, max_pages, anytime, log
        self.started = self.clock()
        self.last_end = None
        self.failures = 0
        self.counts = {"requests": 0, "pages": 0, "items": 0, "new": 0, "already_held": 0, "set_aside": 0,
                       "passes_finished": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
        elif self.counts["requests"] >= self.max_pages:
            self.stopped = self.stopped or "page cap reached"
        elif not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
        else:
            return True
        return False

    def get(self, url, pass_id=None, timeout=60):
        if self.last_end is not None:
            gap = self.last_end + FLOOR_S - self.clock()
            if gap > 0:
                self.sleep(gap)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, timeout)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001
            self.last_end = self.clock()
            self.failures += 1
            self._aside(pass_id, url, "fetch", f"transport: {type(exc).__name__}")
            if self.failures >= STOP_AFTER_FAILURES:
                raise Stop(f"{self.failures} transport failures in a row")
            return None
        self.last_end = self.clock()
        if f.blocked and 500 <= f.status < 600 and not fg.looks_challenged(200, f.body, getattr(f, "headers", None)):
            # the server's own error, not a block (the lesson on telling them apart): set aside, three in a row stop
            self.failures += 1
            self._aside(pass_id, url, "fetch", f"HTTP {f.status}: the server's own error")
            if self.failures >= STOP_AFTER_FAILURES:
                raise Stop(f"{self.failures} server errors in a row")
            return None
        if f.blocked:
            self._aside(pass_id, url, "fetch", f.blocked)
            raise Stop(f.blocked)
        # the gate hands back a redirect off the host asked unfetched, in f.location (final_url is the URL asked)
        if f.status in fg.REDIRECT_STATUSES and f.location and fg.host_of(f.location) != fg.host_of(url):
            self._aside(pass_id, url, "fetch", f"redirected to {fg.host_of(f.location)}")
            raise Stop("redirected to another host")
        self.failures = 0
        if f.status != 200:
            self._aside(pass_id, url, "fetch", f"HTTP {f.status}")
            return None
        return f

    def _aside(self, pass_id, item, stage, why):
        self.t.set_aside(pass_id, item, stage, why)
        self.counts["set_aside"] += 1

    def _land(self, body, url, content_type="text/html"):
        ref, new = self.land_fn(body, name=url, source=SOURCE, name_kind="url", content_type=content_type)
        self.counts["new" if new else "already_held"] += 1
        return ref, new

    def docs(self):
        for name, url in DOCS.items():
            if not self.time_left():
                return
            f = self.get(url)
            if f is not None:
                ref, new = self._land(f.body, url)
                self.t.add_doc(name, url, ref.sha256, new)

    def walk(self, p):
        from registers.building_practitioners import read
        while self.time_left():
            start = p["next_start"]
            url = page_url(start)
            f = self.get(url, p["pass_id"])
            if f is None:
                raise Stop(f"a list page failed; the pass resumes from start={start} next run")
            st = stated_total(f.body)
            n = read.count_items(f.body)
            if st is None or (n == 0 and start < (p["stated"] or 0)):
                self._aside(p["pass_id"], url, "parse", "not a page of the decisions list (no stated total, or empty early)")
                raise Stop("a list page could not be trusted")
            ref, new = self._land(f.body, url)
            self.t.add_page(p, start, url, ref.sha256, n, new, st[1])
            self.counts["pages"] += 1
            self.counts["items"] += n
            if start + PER_PAGE >= st[1] or n == 0:
                self.t.finish(p)
                self.counts["passes_finished"] += 1
                self.log(f"{SOURCE}: pass {p['pass_id']} finished: {p['pages']} pages, stated {st[1]}")
                return

    def run(self) -> dict:
        try:
            p = self.t.open_pass()
            what = plan_pass(p, self.t.last_full_done(), self.now())
            if what == "full":
                self.docs()
                p = self.t.begin()
            if what != "skip":
                self.walk(p)
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def register(positions_dir: str = None) -> str:
    """The position's authorisation to copy the register of practitioners (ruling 132, 2 November 2026); without
    the `authorised: register` line, Held: nothing is asked of it (Building Act 2004, ss 307 and 308)."""
    auth = authorisation("register", positions_dir)
    if not auth:
        raise Held("the register of licensed building practitioners is held: the position records no "
                   "`authorised: register` line; nothing is asked for")
    return auth


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.building_practitioners.capture")
    ap.add_argument("--register", action="store_true", help="the practitioner register (register.py)")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof or a first night)")
    ap.add_argument("--max-pages", type=int, default=1000)
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    if a.register:
        from registers.building_practitioners import register as reg
        return reg.main((["--anytime"] if a.anytime else []) + ["--budget-s", str(a.budget_s), "--database", a.database,
                                                                "--schema", a.schema])
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
    ok = not out["stopped"].startswith("stopped:")
    detail = (f"{out['requests']} requests, {out['pages']} list pages ({out['items']} decisions), {out['new']} new, "
              f"{out['already_held']} already held, {out['set_aside']} set aside, {out['passes_finished']} passes "
              f"finished; {out['stopped'] or 'done'}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
