"""Loading (plan 1b.7): the staging contract, `load(conn, schema) -> int` and
`publish(conn, staging)`, for a lane that publishes nothing. No council's
award or tender list is held (the position: terms, a request, a login, a
challenge), so `load` makes no table and returns 0, and `publish` makes no
view. The day the watch finds a page changed, check.py goes red and a
session reads the position again; until then this file is the contract
kept, not a loader. Councils' awards on GETS are in `pub.award_notices`.

    python -m registers.council_procurement.load --job
"""
import argparse
import sys

SCHEMA = "council_procurement"
WHY = ("no council list held: the councils' own terms bar commercial copying or ask for a request first, "
       "and the platforms ask for a login or challenge")


def load(conn, schema: str, log=print) -> int:
    log(f"{SCHEMA}: {WHY}; nothing read into {schema}")
    return 0


def publish(conn, staging: str, log=print) -> None:
    log(f"{SCHEMA}: nothing to publish from {staging}: {WHY}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.council_procurement.load")
    ap.add_argument("--job", action="store_true")
    ap.parse_args(argv)
    print(f"{SCHEMA}: {WHY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
