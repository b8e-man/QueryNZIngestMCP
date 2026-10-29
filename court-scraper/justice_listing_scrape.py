#!/usr/bin/env python3
"""Justice tribunal listing scraper — closes CDX coverage gaps.

CDX-as-index is partial (Wayback crawls PDF trees unevenly); the WAF-free
listings are the authoritative enumerator. This drains a paginated
SilverStripe listing (?Filter_Jurisdiction=N&start=0,25,...), extracts
/assets/ PDF links, and appends unseen ones to queue.jsonl.

Use: justice_listing_scrape.py <listing-url> <tag> [--max-start N]
  e.g. .../readt-decisions/?Filter_Jurisdiction=32 rea 1200

Polite: 1.5s between page fetches (justice.govt.nz, listing = HTML page).
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
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
PDF_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: justice_listing_scrape.py <listing-url> <tag> "
                 "[--max-start N]")
    listing, tag = sys.argv[1], sys.argv[2]
    max_start = 1200
    if "--max-start" in sys.argv:
        max_start = int(sys.argv[sys.argv.index("--max-start") + 1])

    queued = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    queued.add(json.loads(line)["url"])
                except Exception:
                    pass

    added = pages = 0
    sep = "&" if "?" in listing else "?"
    for start in range(0, max_start + 25, 25):
        url = f"{listing}{sep}start={start}"
        try:
            status, html = fetch(url)
        except Exception as e:
            print(f"start={start}: {e}", flush=True)
            time.sleep(5)
            continue
        pages += 1
        hrefs = {urllib.parse.urljoin(url, h) for h in PDF_RE.findall(html)}
        new = [u for u in sorted(hrefs) if u not in queued]
        if not hrefs:
            print(f"start={start}: no PDF links — end of listing "
                  f"({pages} pages scanned)", flush=True)
            break
        if new:
            with open(QUEUE_F, "a") as f:
                for u in new:
                    f.write(json.dumps({"url": u, "source": f"listing_{tag}"})
                            + "\n")
            queued.update(new)
            added += len(new)
        print(f"start={start}: {len(hrefs)} links, {len(new)} new",
              flush=True)
        time.sleep(1.5)
    print(f"DONE pages={pages} added={added} queue={len(queued)}")


if __name__ == "__main__":
    main()
