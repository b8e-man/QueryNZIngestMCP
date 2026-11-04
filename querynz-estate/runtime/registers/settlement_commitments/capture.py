"""How this lane's documents arrive: case 3 of plan 1.10, through the fetch
gate and the landing wrapper only. A watch, not a capture of records.

Te Haeata (`tehaeata.govt.nz`, Te Puni Kōkiri), the record of Treaty
settlement commitments, answers every records address with its login page
(22 October 2026). Getting past a login is getting past a lock (hard limit
6), so no account is made and no record is asked for. Te Tari Whakatau's
settlement pages are open but its terms bar "any data collection
activities"; the job sends it nothing. What a run does:

  1. the records address (`/commitments`), once: recognised as the wall or
     not, landed by hash, recorded in `capture_watch`;
  2. the pages about the source (about, copyright, terms of use, privacy),
     at most every 30 days, landed by hash, so a change of terms is seen.

Politeness (hard limit 7): one request at a time, `FLOOR_S` apart,
off-peak unless `--anytime`; a 403, 429 or a challenge stops the run (a
failed read, not retried); a gate refusal is never caught.

    python -m registers.settlement_commitments.capture [--anytime]
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.settlement_commitments import read

SOURCE = SCHEMA = "settlement_commitments"
JOB = "qv4-settlement-commitments-watch"
HOST = "tehaeata.govt.nz"
BASE = f"https://{HOST}"
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
DOCS_EVERY_DAYS = 30
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: until the integrator moves `position/treaty-settlement-commitments.md` to docs/legal/positions/, a session runs
#: with QV4_POSITIONS pointing at a folder holding it.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
RECORDS = f"{BASE}/commitments"
DOCS = (f"{BASE}/about-us", f"{BASE}/copyright", f"{BASE}/terms-use", f"{BASE}/privacy")


def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}\.")


def capture_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read()
    return _NAMES.sub(f"{schema}.{'' if schema == SCHEMA else SCHEMA + '_'}", text)


class Tables:
    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema
        self.T = lambda t: table(schema, t)

    def create(self):
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s}")
        self.conn.execute(capture_sql(self.s))

    def docs_due(self, days) -> bool:
        last = self.conn.execute(f"SELECT max(at) FROM {self.T('capture_watch')} WHERE purpose = 'about the source'"
                                 ).fetchone()[0]
        return last is None or (dt.datetime.now(dt.timezone.utc) - last).days >= days

    def add(self, url, purpose, status, sha, answer):
        self.conn.execute(f"INSERT INTO {self.T('capture_watch')} (at, url, purpose, status, sha256, answer) "
                          "VALUES (clock_timestamp(), %s, %s, %s, %s, %s)", (url, purpose, status, sha, answer[:300]))


class Stop(RuntimeError):
    pass


class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None, anytime=False, log=print):
        self.t, self.land_fn, self.log = tables, land_fn, log
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.pacer = fg.Pacer(now=clock or time.monotonic, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.anytime = anytime
        self.counts = {"requests": 0, "landed": 0, "records": "", "set_aside": 0}
        self.stopped = ""

    def ask(self, url, purpose):
        if not self.anytime and not off_peak(self.now()):
            raise Stop("off-peak is over")
        self.pacer.wait(HOST, FLOOR_S)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, 60)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read
            self.t.add(url, purpose, None, None, f"set aside: transport: {type(exc).__name__}")
            self.counts["set_aside"] += 1
            return
        if f.blocked:
            self.t.add(url, purpose, f.status, None, f"set aside: {f.blocked}")
            self.counts["set_aside"] += 1
            raise Stop(f.blocked)
        if f.status != 200 or not f.body:
            self.t.add(url, purpose, f.status, None, f"set aside: HTTP {f.status}" +
                       (f", redirected to {f.location}: not followed" if f.location else ""))
            self.counts["set_aside"] += 1
            return
        try:
            answer = read.recognise(f.body)
        except read.NotTheShape as exc:
            self.t.add(url, purpose, f.status, None, f"set aside: {exc}")
            self.counts["set_aside"] += 1
            return
        ref, new = self.land_fn(f.body, name=url, source=SOURCE, name_kind="url", content_type="text/html")
        self.t.add(url, purpose, f.status, ref.sha256, answer)
        self.counts["landed"] += 1 if new else 0
        if purpose == "records":
            self.counts["records"] = answer

    def run(self) -> dict:
        try:
            self.ask(RECORDS, "records")
            if self.t.docs_due(DOCS_EVERY_DAYS):
                for url in DOCS:
                    self.ask(url, "about the source")
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.settlement_commitments.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db, jobrun
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        out = Run(t, land_fn=landing(conn), anytime=a.anytime).run()
    ok = bool(out["records"])
    detail = (f"{out['requests']} requests, the records address answered with "
              f"{dict(wall='the login wall', open='NO WALL: the records may be open').get(out['records'], 'nothing readable')}; "
              f"{out['landed']} new documents, {out['set_aside']} set aside" + (f"; {out['stopped']}" if out["stopped"] else ""))
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
