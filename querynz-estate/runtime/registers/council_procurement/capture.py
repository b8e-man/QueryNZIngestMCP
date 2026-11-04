"""How this lane's documents arrive: case 3 of plan 1.10, through the fetch
gate and the landing wrapper only. A watch, not a capture of tenders.

Councils' awards and tenders off GETS (the position,
`council-procurement-platforms`): Clutha's terms bar commercial copying,
Tauranga's allow non-commercial use only, Dunedin's ask for a request first,
VendorPanel shows tenders to registered suppliers only, and TenderLink and
Queenstown Lakes answered with a challenge (failed reads, never asked
again). So no council page of tenders or awards is asked. What a run does,
at most every `EVERY_DAYS` days:

  each of the four pages whose words decide that (`read.WATCHED`), once:
  recognised (the words still bar us, or they have changed), landed by
  hash, recorded in `capture_watch`.

Politeness (hard limit 7): one request at a time, `FLOOR_S` apart (Clutha
states 7 s), off-peak unless `--anytime`; a 403, 429 or a challenge stops
the run (a failed read, not retried); a redirect is not followed; a gate
refusal is never caught.

    python -m registers.council_procurement.capture [--anytime]
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.council_procurement import read

SOURCE = SCHEMA = "council_procurement"
JOB = "qv4-council-procurement-watch"
FLOOR_S = 7.0
OFF_PEAK = (22, 6)
EVERY_DAYS = 30
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
#: until the integrator moves `position/council-procurement-platforms.md` to docs/legal/positions/, a session runs
#: with QV4_POSITIONS pointing at a folder holding it.
POSITIONS = os.environ.get("QV4_POSITIONS") or None
PAGES = tuple(read.WATCHED)


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

    def due(self, days) -> bool:
        last = self.conn.execute(f"SELECT max(at) FROM {self.T('capture_watch')}").fetchone()[0]
        return last is None or (dt.datetime.now(dt.timezone.utc) - last).days >= days

    def add(self, url, status, sha, answer):
        self.conn.execute(f"INSERT INTO {self.T('capture_watch')} (at, url, status, sha256, answer) "
                          "VALUES (clock_timestamp(), %s, %s, %s, %s)", (url, status, sha, answer[:300]))


class Stop(RuntimeError):
    pass


class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now=None, anytime=False, log=print):
        self.t, self.land_fn, self.log = tables, land_fn, log
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS,
                                                                  same_host_hops=0))
        self.pacer = fg.Pacer(now=clock or time.monotonic, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.anytime = anytime
        self.counts = {"requests": 0, "landed": 0, "bars": 0, "changed": 0, "set_aside": 0}
        self.stopped = ""

    def ask(self, url):
        if not self.anytime and not off_peak(self.now()):
            raise Stop("off-peak is over")
        host = fg.host_of(url)
        self.pacer.wait(host, FLOOR_S)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, 60)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read
            self.t.add(url, None, None, f"set aside: transport: {type(exc).__name__}")
            self.counts["set_aside"] += 1
            return
        if f.blocked:
            self.t.add(url, f.status, None, f"set aside: {f.blocked}")
            self.counts["set_aside"] += 1
            raise Stop(f.blocked)
        if f.status != 200 or not f.body:
            self.t.add(url, f.status, None, f"set aside: HTTP {f.status}" +
                       (f", redirected to {f.location}: not followed" if f.location else ""))
            self.counts["set_aside"] += 1
            return
        try:
            answer = read.recognise(url, f.body)
        except read.NotTheShape as exc:
            self.t.add(url, f.status, None, f"set aside: {exc}")
            self.counts["set_aside"] += 1
            return
        ref, new = self.land_fn(f.body, name=url, source=SOURCE, name_kind="url", content_type="text/html")
        self.t.add(url, f.status, ref.sha256, answer)
        self.counts["landed"] += 1 if new else 0
        self.counts[answer] += 1

    def run(self) -> dict:
        if not self.t.due(EVERY_DAYS):
            return {**self.counts, "stopped": f"not due: watched within {EVERY_DAYS} days"}
        try:
            for url in PAGES:
                self.ask(url)
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.council_procurement.capture")
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
    ok = not out["stopped"].startswith("stopped:") and out["set_aside"] == 0
    detail = (f"{out['requests']} requests: {out['bars']} pages still bar the capture, {out['changed']} changed, "
              f"{out['set_aside']} set aside; {out['landed']} new documents" +
              (f"; {out['stopped']}" if out["stopped"] else ""))
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
