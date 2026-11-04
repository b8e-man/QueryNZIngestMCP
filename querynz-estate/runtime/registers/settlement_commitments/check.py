"""The lane's one figure against the outside world (contract: the lane): the
login wall in front of Te Haeata's records. Exit 1 on any of:

  1. no watch of the records address in the last `STALE_DAYS` days
  2. the newest watch found the records address answering without the login
     wall: the records may be open, and a session should read the position's
     four questions again and build the reading
  3. the newest watch was a failed read (a block, a challenge, an error)

Green means: the wall stands and the lane rightly holds nothing.

    python -m registers.settlement_commitments.check [--database querynz_v4]
"""
import argparse
import datetime as dt
import sys

from registers.settlement_commitments import capture

SCHEMA = "settlement_commitments"
STALE_DAYS = 8


def outside(conn, schema: str = SCHEMA, now=None) -> list:
    T = capture.table(schema, "capture_watch")
    if conn.execute("SELECT to_regclass(%s)", (T,)).fetchone()[0] is None:
        return ["no watch of Te Haeata's records address is held"]
    r = conn.execute(f"SELECT at, answer FROM {T} WHERE purpose = 'records' ORDER BY at DESC LIMIT 1").fetchone()
    if r is None:
        return ["no watch of Te Haeata's records address is held"]
    at, answer = r
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    if (now - at).days >= STALE_DAYS:
        out.append(f"the newest watch is {(now - at).days} days old")
    if answer == "open":
        out.append("Te Haeata's records address answered without the login wall: read the position again and "
                   "build the reading")
    elif answer != "wall":
        out.append(f"the newest watch was a failed read: {answer[:120]}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.settlement_commitments.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db
    key = db.READ_KEY if a.database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.database) as conn:
        problems = outside(conn, a.schema)
    for p in problems:
        print(f"{SCHEMA}: RED: {p}")
    print(f"{SCHEMA}: " + ("the wall stands; 0 problems" if not problems else f"{len(problems)} problems"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
