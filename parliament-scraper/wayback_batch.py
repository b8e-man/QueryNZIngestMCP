#!/usr/bin/env python3
"""Parliament Wayback batch runner — drains wayback_queue.jsonl via the
proven ingest pipeline (challenge-stub filtering, gzip-aware, raw bodies).

Pops up to --limit URLs not yet in manifest kind=doc, ingests their snapshots
(newest real capture kept), time-budgeted for the 120s cron-kill window.
Silent on success; stderr + exit 1 on repeated failure.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_wayback_docs import ingest, OUT  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE_F = os.path.join(BASE, "wayback_queue.jsonl")
MANIFEST_F = os.path.join(OUT, "manifest.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--time-budget", type=int, default=95)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    done = set()
    if os.path.exists(MANIFEST_F):
        with open(MANIFEST_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("kind") == "doc":
                        done.add(r["url"])
                except Exception:
                    pass

    batch = []
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    u = json.loads(line)["url"]
                    if u not in done:
                        batch.append(u)
                except Exception:
                    pass
    if not batch:
        sys.exit(0)

    batch = batch[:args.limit]
    t0 = time.time()
    processed = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        i = 0
        while i < len(batch):
            if time.time() - t0 > args.time_budget:
                break
            wave = batch[i:i + args.workers]
            i += args.workers
            futs = {ex.submit(ingest, [u]): u for u in wave}
            for fut in as_completed(futs):
                try:
                    fut.result()
                    processed += 1
                except Exception as e:
                    print(f"wayback batch doc failed {futs[fut]}: {e}"[:150],
                          file=sys.stderr)

    if processed == 0:
        print("wayback batch: time budget exhausted before any doc", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
