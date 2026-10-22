#!/usr/bin/env python3
"""Parliament Wayback enumerator — builds the historical document queue.

CDX prefix enumeration over www.parliament.nz/en/* and www3.parliament.nz/en/*
(te reo /mi/ mirrors deliberately EXCLUDED), year-sliced to dodge the 50K
row cap (collapse=urlkey dedupes the union). Skip-types (calendar/ical,
alerts/maintenance, ajax/) excluded. URLs already ingested (manifest.jsonl
kind=doc) or queued are not re-added.

Writes/refreshes /opt/data/parliament-scraper/wayback_queue.jsonl
  {"url", "latest_ts", "source"}
Idempotent — safe to run daily (cron). Silent on success.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE_F = os.path.join(BASE, "wayback_queue.jsonl")
MANIFEST_F = os.path.join(BASE, "data", "wayback_docs", "manifest.jsonl")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

SKIP_TYPES = ("calendar/ical", "alerts/maintenance", "ajax/")
SLICES = [(2000, 2012), (2013, 2016), (2017, 2019), (2020, 2021),
          (2022, 2023), (2024, 2025), (2026, 2026)]


def cdx_slice(prefix, y0, y1):
    q = urllib.parse.urlencode({
        "url": prefix + "*", "output": "json", "fl": "original,timestamp",
        "collapse": "urlkey", "filter": "statuscode:200",
        "from": str(y0), "to": str(y1), "limit": "50000"})
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(CDX + "?" + q, headers=UA),
                                        timeout=180) as r:
                data = json.loads(r.read())
            return [(row[0], row[1]) for row in data[1:]]
        except Exception:
            time.sleep(5)
    return None


def main():
    found = {}
    for prefix in ("www.parliament.nz/en/", "www3.parliament.nz/en/"):
        for y0, y1 in SLICES:
            rows = cdx_slice(prefix, y0, y1)
            if rows is None:
                print(f"CDX failed: {prefix} {y0}-{y1}", file=sys.stderr)
                sys.exit(1)
            for url, ts in rows:
                path = url.split("://", 1)[-1].split("/", 1)[-1].lower()
                if any(s in path for s in SKIP_TYPES):
                    continue
                key = url.split("://", 1)[-1].split("?")[0].split("#")[0].rstrip("/").lower()
                if ts > found.get(key, ("", ""))[1]:
                    found[key] = (url, ts)
            time.sleep(1.5)

    done = set()
    if os.path.exists(MANIFEST_F):
        with open(MANIFEST_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("kind") == "doc":
                        done.add(r["url"].split("://", 1)[-1].split("?")[0]
                                 .split("#")[0].rstrip("/").lower())
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
    with open(QUEUE_F, "a") as f:
        for key, (url, ts) in found.items():
            if key in done or url in queued:
                continue
            f.write(json.dumps({"url": url, "latest_ts": ts,
                                "source": "cdx"}, ensure_ascii=False) + "\n")
            added += 1

    print(f"enum: {len(found)} urls found, {added} new queued",
          file=sys.stderr if added == 0 and not found else sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
