#!/usr/bin/env python3
"""Refresh the estate's tenancy ask queue (2026-11-11).

The estate asked us to gather the Tenancy Tribunal orders their register
lists and our copy lacks (estate-tenancy_tribunal@short-13249-2028-06-23),
soonest take-down first. This script rewrites
/opt/data/querynz-estate/tenancy_missing_queue.jsonl = the ask's orders that
have NOT yet landed, sorted by take-down date. The estate capture lane
(qv4-tenancy-tribunal-capture) works the same set soonest-to-leave-first;
the queue shrinks as records land.

An order is HELD when its PDF has actually landed. The correct test is the
PDF's own address (source_url) appearing among the manifest's names/urls, or
the capture lane's orders table recording the document hash — NOT a regex
over the manifest for the order_id. The Tribunal's MBIE orders are published
under a `publishedOrderPdfName` (e.g. `12621475-Tribunal_Order_Redacted.pdf`)
that is NOT the order_id, so an order_id regex could never see them and they
stayed "missing" forever even after their PDF landed (2026-11-17 fix).

Quiet when nothing changed (watchdog pattern). Run nightly.
"""
import json
import os
import sqlite3
import time

ASK = "/opt/data/qnz-mcp/asks/tenancy_tribunal.json"
MANIFEST = "/opt/data/querynz-estate/sources/tenancy_tribunal/manifest.jsonl"
QUEUE = "/opt/data/querynz-estate/tenancy_missing_queue.jsonl"
ORDERS_DB = "/opt/data/querynz-estate/runtime/db/tenancy_tribunal.sqlite"


def held_ids():
    """The set of ask order_ids whose document has landed.

    Two signals, either is enough:
      1. the manifest already carries the PDF's source_url among its
         names/urls (the URL the PDF was landed under); and
      2. the capture lane's orders table records the document hash.
    """
    held = set()
    landed_urls = set()
    if os.path.exists(MANIFEST):
        with open(MANIFEST, errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                for n in (row.get("names") or []):
                    landed_urls.add(n)
                for u in (row.get("urls") or []):
                    url = u.get("url") if isinstance(u, dict) else u
                    if url:
                        landed_urls.add(url)
    if os.path.exists(ORDERS_DB):
        conn = sqlite3.connect(ORDERS_DB)
        try:
            for order_id, source_url, document in conn.execute(
                    "SELECT order_id, source_url, document FROM orders"):
                if document is not None:
                    held.add(str(order_id))
                elif source_url and source_url in landed_urls:
                    held.add(str(order_id))
        finally:
            conn.close()
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
