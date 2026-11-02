#!/usr/bin/env python3
"""GETS history discovery via Wayback CDX.

The live lists only expose recent tenders (open ~400, closed ~6.1K,
awarded ~1.1K), and the logged-in search is out of reach. The historical
ID universe comes from Wayback's CDX index of gets.govt.nz detail URLs —
6K+ unique IDs seen at the 10K-row cap, IDs from 420996 (2010s) to
35M (now). Old detail pages still serve LIVE from gets.govt.nz, so CDX
is enumeration-only (measurement instrument), capture targets the live
site.

Budget-aware + resumable via state/cdx_state.json (pages walked).
Wayback flaps ("Temporarily Offline") — failures exit 0 quietly; the
daily cron retries.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

BASE = "/opt/data/gets-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "state", "cdx_state.json")

CDX = ("http://web.archive.org/cdx/search/cdx?url=gets.govt.nz/*"
       "&output=json&collapse=urlkey&fl=original"
       "&filter=original:.*ExternalTenderDetails.*&limit=5000&page={p}")

ID_RE = re.compile(r"ExternalTenderDetails\.htm\?id=(\d+)")


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "Query-NZ-corpus-capture"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_known():
    known = set()
    for path in (QUEUE_F, DONE_F):
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = ID_RE.search(json.loads(line).get("url", ""))
                except ValueError:
                    continue
                if m:
                    known.add(int(m.group(1)))
    return known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()

    os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
    state = {}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except ValueError:
            state = {}
    pages_done = set(state.get("pages_done", []))

    known = load_known()
    added = 0
    walked = 0
    reached_end = False

    for p in range(args.max_pages):
        if time.time() - t0 > args.time_budget:
            break
        if p in pages_done:
            continue
        try:
            raw = fetch(CDX.format(p=p))
            rows = json.loads(raw)
        except Exception as e:
            print(f"GETS cdx: page {p} failed ({str(e)[:60]}) — retry next run")
            return 0  # Wayback flap; not an alert-worthy failure
        if not rows:
            reached_end = True
            break
        for row in rows:
            u = row[0]
            if u == "original":
                continue
            m = ID_RE.search(u)
            if not m:
                continue
            rfx = int(m.group(1))
            if rfx in known:
                continue
            known.add(rfx)
            rec = {
                "url": (f"https://www.gets.govt.nz/"
                        f"ExternalTenderDetails.htm?id={rfx}"),
                "source": "gets_cdx",
                "rfx_id": rfx,
                "court": "gets",
            }
            with open(QUEUE_F, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += 1
        pages_done.add(p)
        walked += 1
        time.sleep(1.0)

    state["pages_done"] = sorted(pages_done)
    if reached_end:
        state["complete"] = True
    with open(STATE_F, "w") as f:
        json.dump(state, f)
    print(f"GETS cdx: pages={walked} added={added} known={len(known)}"
          + (" (complete)" if reached_end or state.get("complete") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
