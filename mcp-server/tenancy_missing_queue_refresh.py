#!/usr/bin/env python3
"""Refresh the estate's tenancy ask queue (2026-11-11).

The estate asked us to gather the Tenancy Tribunal orders their register
lists and our copy lacks (estate-tenancy_tribunal@short-13249-2028-06-23),
soonest take-down first. This script rewrites
/opt/data/querynz-estate/tenancy_missing_queue.jsonl = the ask's orders that
have NOT yet landed in the estate-tenancy_tribunal manifest, sorted by
take-down date. The estate capture lane (qv4-tenancy-tribunal-capture) works
the same set soonest-to-leave-first; the queue shrinks as records land.

Quiet when nothing changed (watchdog pattern). Run nightly.
"""
import json
import os
import re
import time

ASK = "/opt/data/qnz-mcp/asks/tenancy_tribunal.json"
MANIFEST = ("/opt/data/querynz-estate/sources/tenancy_tribunal/manifest.jsonl")
QUEUE = "/opt/data/querynz-estate/tenancy_missing_queue.jsonl"

ID_RE = re.compile(r"(\d{6,})")


def held_ids():
    held = set()
    if not os.path.exists(MANIFEST):
        return held
    with open(MANIFEST, errors="replace") as f:
        for line in f:
            for m in ID_RE.finditer(line):
                held.add(m.group(1))
    return held


def main():
    ask = json.load(open(ASK))
    orders = ask.get("orders", [])
    held = held_ids()
    missing = [o for o in orders if str(o.get("order_id")) not in held]
    missing.sort(key=lambda o: (str(o.get("take_down") or "9999"),
                                str(o.get("order_id"))))
    new = []
    with open(QUEUE + ".new", "w") as f:
        for o in missing:
            f.write(json.dumps({"order_id": str(o.get("order_id")),
                                "take_down": o.get("take_down")}) + "\n")
            new.append(str(o.get("order_id")))
    # only swap when the set actually moved
    old = []
    if os.path.exists(QUEUE):
        with open(QUEUE, errors="replace") as f:
            for line in f:
                try:
                    old.append(str(json.loads(line).get("order_id")))
                except ValueError:
                    continue
    if old == new:
        os.remove(QUEUE + ".new")
        return 0
    os.replace(QUEUE + ".new", QUEUE)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp}  tenancy ask queue: {len(missing)} of "
          f"{len(orders)} asked orders still missing "
          f"(was {len(old)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
