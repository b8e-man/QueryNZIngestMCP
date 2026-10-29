#!/usr/bin/env python3
"""Seed the court case queue from the Wayback CDX index.

Wayback holds >=50,000 courtsofnz.govt.nz/cases/* URLs (query caps at
50K/page). This enumerates all CDX pages, dedupes, and appends unseen case
URLs to queue.jsonl. Run one-shot or re-run periodically; idempotent.

Standing rule: Wayback is used as an INDEX only — capture is always from
the live site (Wayback beehive-era captures proved to be challenge stubs).
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
# Prefixes fully fetched (success, even 0 rows). Failed buckets are retried
# on the next run — Wayback CDX drops queries with 503/504 regularly.
DONE_PREFIX_F = os.path.join(BASE, "cdx_prefixes_done.json")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
# CDX caps results at 50K per query and its page param is unreliable
# (showNumPages returns null; page blocks include @@images noise) — so the
# index is partitioned by slug prefix instead.
PREFIXES = ("-", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
            *tuple("abcdefghijklmnopqrstuvwxyz"))
SLUG_OK = re.compile(r"^https?://[^/]+/cases/[^/?#]+$")


def cdx_page(prefix, limit=50000, timeout=120):
    q = urllib.parse.urlencode({
        "url": "courtsofnz.govt.nz/cases/" + prefix,
        "matchType": "prefix", "output": "json", "fl": "original",
        "collapse": "urlkey", "filter": "statuscode:200",
        "limit": str(limit),
    })
    req = urllib.request.Request(CDX + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [row[0] for row in data[1:]]


def main():
    limit_n = int(sys.argv[1]) if len(sys.argv) > 1 else len(PREFIXES)

    done_prefixes = set()
    if os.path.exists(DONE_PREFIX_F):
        try:
            with open(DONE_PREFIX_F) as f:
                done_prefixes = set(json.load(f))
        except Exception:
            done_prefixes = set()

    done_urls = set()
    if os.path.exists(DONE_F):
        with open(DONE_F) as f:
            for line in f:
                try:
                    done_urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    queued = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    queued.add(json.loads(line)["url"])
                except Exception:
                    pass

    added = 0
    fetched = 0
    pending = [p for p in PREFIXES[:limit_n] if p not in done_prefixes]
    if not pending:
        print("all prefixes already fetched — nothing to do")
        return
    for prefix in pending:
        try:
            urls = cdx_page(prefix)
        except Exception as e:
            print(f"cdx prefix '{prefix}' failed: {e}", file=sys.stderr)
            time.sleep(5)
            continue
        fetched += len(urls)
        new = [u for u in urls
               if SLUG_OK.match(u)
               and u not in queued and u not in done_urls]
        if new:
            with open(QUEUE_F, "a") as f:
                for u in new:
                    f.write(json.dumps({"url": u}) + "\n")
            queued.update(new)
            added += len(new)
        done_prefixes.add(prefix)
        with open(DONE_PREFIX_F, "w") as f:
            json.dump(sorted(done_prefixes), f)
        print(f"prefix '{prefix}': {len(urls)} rows, {len(new)} new")
        if len(urls) >= 50000:
            print(f"WARNING: prefix '{prefix}' hit the 50K cap — "
                  f"needs finer partitioning", file=sys.stderr)
        time.sleep(1)
    print(f"DONE fetched={fetched} added={added} queue={len(queued)}")


if __name__ == "__main__":
    main()
