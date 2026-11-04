"""Loading (plan 1b.7): the staging contract, `load(conn, schema) -> int` and
`publish(conn, staging)`, for a lane that publishes nothing. Te Haeata's
records sit behind a login, so no row is ever read: `load` makes no table and
returns 0, `publish` makes no view. Both say so. The day the watch finds the
wall gone, check.py goes red and a session builds the reading under a fresh
position; until then this file is the contract kept, not a loader.

    python -m registers.settlement_commitments.load --job
"""
import argparse
import sys

from support import jobrun

SCHEMA = "settlement_commitments"
JOB = "qv4-settlement-commitments-load"
WHY = "no record held: Te Haeata's records sit behind a login (hard limit 6)"


def load(conn, schema: str, log=print) -> int:
    log(f"{SCHEMA}: {WHY}; nothing read into {schema}")
    return 0


def publish(conn, staging: str, log=print) -> None:
    log(f"{SCHEMA}: nothing to publish from {staging}: {WHY}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.settlement_commitments.load")
    ap.add_argument("--job", action="store_true")
    ap.parse_args(argv)
    print(f"{SCHEMA}: {WHY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
