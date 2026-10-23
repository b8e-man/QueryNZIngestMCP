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
from ingest_wayback_docs import ingest, OUT, BudgetExceeded  # noqa: E402

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
    attempts = {}
    if os.path.exists(MANIFEST_F):
        with open(MANIFEST_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("kind") == "doc":
                        done.add(r["url"])
                    elif r.get("kind") == "attempt":
                        attempts[r["url"]] = attempts.get(r["url"], 0) + 1
                except Exception:
                    pass

    batch = []
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    u = json.loads(line)["url"]
                    if u not in done and attempts.get(u, 0) < 2:
                        batch.append(u)
                except Exception:
                    pass
    if not batch:
        sys.exit(0)

    batch = batch[:args.limit]
    deadline = time.time() + args.time_budget
    processed = 0
    gen_fail = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        i = 0
        while i < len(batch):
            remaining = deadline - time.time()
            if remaining <= 2:
                break
            wave = batch[i:i + args.workers]
            i += args.workers
            futs = {ex.submit(ingest, [u], deadline=deadline): u for u in wave}
            try:
                for fut in as_completed(futs, timeout=max(2, remaining)):
                    try:
                        fut.result()
                        processed += 1
                    except BudgetExceeded:
                        break     # budget gone mid-wave; resume next tick
                    except Exception:
                        gen_fail += 1   # genuine doc failure; URL retries capped
            except TimeoutError:
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    if gen_fail >= 3:
        print(f"wayback batch: {gen_fail} docs failed after retries", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
