"""The lane's one figure against the outside world (contract: the lane): the
words that keep councils' own award and tender lists out of the estate.
Exit 1 on any of:

  1. no watch held, or none of a watched page in the last `STALE_DAYS` days
  2. a watched page's newest answer is `changed`: its terms no longer say
     what bars us, so a session reads the position's four questions again
  3. a watched page's newest answer was a failed read (a block, a challenge,
     an error, a page that is not the one watched)

Green means: each page still says what it said on 22 October 2026, and the
lane rightly holds no council's list.

    python -m registers.council_procurement.check [--database querynz_v4]
"""
import argparse
import datetime as dt
import sys

from registers.council_procurement import capture, read

SCHEMA = "council_procurement"
STALE_DAYS = 40


def outside(conn, schema: str = SCHEMA, now=None) -> list:
    T = capture.table(schema, "capture_watch")
    if conn.execute("SELECT to_regclass(%s)", (T,)).fetchone()[0] is None:
        return ["no watch of the councils' terms is held"]
    newest = {u: (at, a) for u, at, a in conn.execute(
        f"SELECT DISTINCT ON (url) url, at, answer FROM {T} ORDER BY url, at DESC").fetchall()}
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for url, (_, _, who) in read.WATCHED.items():
        if url not in newest:
            out.append(f"{who}: never watched")
            continue
        at, answer = newest[url]
        if (now - at).days >= STALE_DAYS:
            out.append(f"{who}: the newest watch is {(now - at).days} days old")
        if answer == "changed":
            out.append(f"{who}: its page no longer says what bars the capture: read the position again")
        elif answer != "bars":
            out.append(f"{who}: the newest watch was a failed read: {answer[:120]}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.council_procurement.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db
    key = db.READ_KEY if a.database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.database) as conn:
        problems = outside(conn, a.schema)
    for p in problems:
        print(f"{SCHEMA}: RED: {p}")
    print(f"{SCHEMA}: " + ("every watched page still bars the capture; 0 problems" if not problems
                           else f"{len(problems)} problems"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
