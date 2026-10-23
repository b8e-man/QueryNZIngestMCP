#!/usr/bin/env python3
"""Beehive full-history backfill builder — record level, zero-LLM, stdlib.

Harvests the COMPLETE sitemap (all sub-pages, not just the tail the forward
collector diffs) and produces:
  /opt/data/beehive-scraper/backfill_inventory.jsonl  — every URL the site has
      ever published (url, lastmod, source_page) — raw, one row per sitemap row
  /opt/data/beehive-scraper/backfill_queue.jsonl      — inventory rows whose
      body is NOT yet captured (no done.jsonl status=ok) — the work list for
      beehive_bodyfetch.py --queue backfill_queue.jsonl

Run manually (or via cron) whenever a full re-scan is wanted. Dedupe key = URL.
"""

import json
import os
import re
import sys
import time
import urllib.request
from xml.etree import ElementTree as ET

BASE = "/opt/data/beehive-scraper"
INV_F = os.path.join(BASE, "backfill_inventory.jsonl")
QUEUE_F = os.path.join(BASE, "backfill_queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
SITEMAP_INDEX = "https://www.beehive.govt.nz/sitemap.xml"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
CHALLENGE = (b"_Incapsula_Resource?SWJIYLWA", b"Incapsula incident", b"SWUDNSAI")


def fetch(url, retries=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=40) as r:
                b = r.read()
            if not any(m in b[:2048] for m in CHALLENGE):
                return b
        except Exception:
            pass
        time.sleep(5)
    return None


def main():
    idx = fetch(SITEMAP_INDEX)
    if idx is None:
        print("sitemap index unreachable", file=sys.stderr)
        sys.exit(1)
    pages = re.findall(r"<loc>(.*?)</loc>", idx.decode())
    rows = {}
    for i, p in enumerate(pages):
        b = fetch(p)
        if b is None:
            print(f"sitemap page unreachable: {p}", file=sys.stderr)
            sys.exit(1)
        root = ET.fromstring(b)
        for u in root.iter(NS + "url"):
            loc = (u.findtext(NS + "loc") or "").strip()
            if loc.startswith("http"):
                rows[loc] = (u.findtext(NS + "lastmod") or "").strip()
        time.sleep(1)

    with open(INV_F, "w") as f:
        for u, lm in rows.items():
            f.write(json.dumps({"url": u, "lastmod": lm, "source": "sitemap"},
                               ensure_ascii=False) + "\n")

    done_ok = set()
    if os.path.exists(DONE_F):
        with open(DONE_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok":
                        done_ok.add(r["url"])
                except Exception:
                    pass

    pending = [u for u in rows if u not in done_ok]
    with open(QUEUE_F, "w") as f:
        for u in pending:
            f.write(json.dumps({"url": u, "kind": "backfill",
                                "lastmod": rows[u]}, ensure_ascii=False) + "\n")

    by_type = {}
    for u in rows:
        t = next((x for x in ("release", "speech", "feature") if f"/{x}/" in u), "page")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"inventory: {len(rows)} urls {by_type}")
    print(f"captured already: {len(rows) - len(pending)} | queue: {len(pending)}")


if __name__ == "__main__":
    main()
