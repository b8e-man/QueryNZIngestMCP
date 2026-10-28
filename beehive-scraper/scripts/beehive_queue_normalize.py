#!/usr/bin/env python3
"""One-off backfill queue normalization (run 2026-10-28).

The Wayback CDX feed carries legacy '+slug' space-encoded URLs; live beehive
uses '-' and 404s every '+' form (3,524 unique '+slugs' x up to 3 retry
attempts = ~10K wasted fetches, measured 2026-10-28). This script:

1. backs up backfill_queue.jsonl (raw inventory preserved),
2. drops '+' entries whose '-' twin is already queued or captured,
3. rewrites remaining '+' entries to '-' form, keeping raw_url provenance,
4. logs every dropped URL to logs/queue_normalize.log (nothing vanishes).

Safe to re-run (idempotent).
"""
import json
import os
import shutil
from datetime import datetime, timezone

BASE = "/opt/data/beehive-scraper"
QUEUE = os.path.join(BASE, "backfill_queue.jsonl")
DONE = os.path.join(BASE, "done.jsonl")
LOG = os.path.join(BASE, "logs", "queue_normalize.log")


def to_hyphen(url):
    """Replace '+' with '-' in the path part only (query/fragment intact)."""
    head, sep, tail = url.partition("?")
    return head.replace("+", "-") + (sep + tail if sep else "")


def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok_urls = set()
    if os.path.exists(DONE):
        with open(DONE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok":
                        ok_urls.add(r["url"])
                except Exception:
                    pass

    entries = []
    with open(QUEUE) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass

    urls = {e.get("url", "") for e in entries}
    kept, dropped, rewritten = [], [], []
    seen = set()
    for e in entries:
        u = e.get("url", "")
        if "+" not in u:
            if u not in seen:
                seen.add(u)
                kept.append(e)
            continue
        hy = to_hyphen(u)
        if hy in urls or hy in ok_urls:
            dropped.append((u, "twin=" + hy))
            continue
        if hy in seen:
            dropped.append((u, "dup-of=" + hy))
            continue
        e["raw_url"] = u
        e["url"] = hy
        seen.add(hy)
        rewritten.append((u, hy))
        kept.append(e)

    shutil.copy2(QUEUE, QUEUE + ".bak-20261028")
    with open(QUEUE, "w") as f:
        for e in kept:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"[{ts}] kept={len(kept)} dropped={len(dropped)} "
                f"rewritten={len(rewritten)}\n")
        for u, why in dropped:
            f.write(f"  DROP {why} {u}\n")
        for u, hy in rewritten:
            f.write(f"  REWRITE {u} -> {hy}\n")
    print(f"kept={len(kept)} dropped={len(dropped)} rewritten={len(rewritten)} "
          f"(backup: queue.bak-20261028, log: logs/queue_normalize.log)")


if __name__ == "__main__":
    main()
