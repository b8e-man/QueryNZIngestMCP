#!/usr/bin/env python3
"""Seed queue.jsonl from the Wayback CDX index for tribunal/court PDF hosts.

Wayback is an INDEX only — capture is always from the live site, stored raw
(no extraction or conversion). justice.govt.nz /robots.txt disallows /assets/;
the user directed direct fetch anyway at a gentle cadence (POLITE_SLEEP in
court_scraper.py).

Corpora sized 2026-10-29 (CDX rows, PDFs):
  justice.govt.nz/assets/Documents/Decisions/  ~6,418  (REA/LCDT/Teachers/LCRO)
  employmentcourt.govt.nz/assets/Documents/   ~3,351
  environmentcourt.govt.nz/                   ~3,879
  coronerscourt.govt.nz/assets/               ~150

Idempotent: done prefixes tracked in tribunal_cdx_done.json; re-runs only
retry buckets Wayback dropped (its CDX serves 503/504 regularly).
"""

import json
import os
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
DONE_PREFIX_F = os.path.join(BASE, "tribunal_cdx_done.json")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

PREFIXES = (
    "justice.govt.nz/assets/Documents/Decisions/",
    "employmentcourt.govt.nz/assets/Documents/Decisions/",
    "coronerscourt.govt.nz/assets/",
    "environmentcourt.govt.nz/",
)
MAX_TRIES = 3


def cdx_page(prefix, limit=50000, timeout=120):
    q = urllib.parse.urlencode({
        "url": prefix, "matchType": "prefix", "output": "json",
        "fl": "original", "collapse": "urlkey", "filter": "statuscode:200",
        "limit": str(limit),
    })
    req = urllib.request.Request(CDX + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [row[0] for row in data[1:]]


def load_urls(path):
    urls = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    return urls


def main():
    done_prefixes = set()
    if os.path.exists(DONE_PREFIX_F):
        try:
            with open(DONE_PREFIX_F) as f:
                done_prefixes = set(json.load(f))
        except Exception:
            done_prefixes = set()

    queued = load_urls(QUEUE_F)
    done_urls = load_urls(DONE_F)

    added = fetched = 0
    pending = [p for p in PREFIXES if p not in done_prefixes]
    if not pending:
        print("all prefixes already fetched — nothing to do")
        return
    for prefix in pending:
        urls = None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                urls = cdx_page(prefix)
                break
            except Exception as e:
                print(f"cdx '{prefix}' attempt {attempt}: {e}", flush=True)
                time.sleep(15 * attempt)
        if urls is None:
            continue  # left out of ledger -> retried next run
        fetched += len(urls)
        new = [u for u in urls
               if u.lower().split("?")[0].endswith(".pdf")
               and u not in queued and u not in done_urls]
        if new:
            with open(QUEUE_F, "a") as f:
                for u in new:
                    f.write(json.dumps({"url": u, "source": "tribunal_cdx"})
                            + "\n")
            queued.update(new)
            added += len(new)
        done_prefixes.add(prefix)
        with open(DONE_PREFIX_F, "w") as f:
            json.dump(sorted(done_prefixes), f)
        print(f"'{prefix}': {len(urls)} rows, {len(new)} new")
        time.sleep(2)
    print(f"DONE fetched={fetched} added={added} queue={len(queued)}")


if __name__ == "__main__":
    main()
