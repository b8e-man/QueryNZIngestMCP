#!/usr/bin/env python3
"""GETS pre-2014 history enumeration via Wayback LISTING snapshots.

The live lists only go back to 29 Jul 2014, but archived snapshots of the
old GETS index/closed/awarded pages (2005-2014) carry detail IDs from
the hidden era — the era the CDX detail-page index only partially covers.

Flow:
  1. CDX: all archived URLs matching gets.govt.nz/External*.htm* (listing
     and search pages), collapse to one snapshot per URL.
  2. Replay each snapshot (web.archive.org/web/<ts>id_/<url> = raw bytes)
     and extract ExternalTenderDetails ids -> queue rows (source:
     gets_history_enum), canonicalised to the live site (old pages still
     serve live — verified 2026-11-02 with id=420996).

Enumeration-only for Wayback: captures target gets.govt.nz live (the
capture tick). Budget-aware + resumable (state/history_enum_state.json).
Wayback flaps ("Temporarily Offline") — failures exit 0, daily cron
retries.
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
STATE_F = os.path.join(BASE, "state", "history_enum_state.json")

CDX_LISTS = ("http://web.archive.org/cdx/search/cdx?url=gets.govt.nz/*"
             "&output=json&collapse=urlkey&fl=original,timestamp"
             "&filter=original:.*External(?!TenderDetails).*\\.htm.*"
             "&limit=2000&page={p}")
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
    ap.add_argument("--max-snapshots", type=int, default=400)
    args = ap.parse_args()
    t0 = time.time()

    os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
    state = {}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except ValueError:
            state = {}
    seen_urls = set(state.get("seen_urls", []))

    known = load_known()
    added = 0
    snaps = 0
    pages_done = 0

    try:
        raw = fetch(CDX_LISTS.format(p=0))
        rows = json.loads(raw)
    except Exception as e:
        print(f"GETS history-enum: CDX unavailable ({str(e)[:60]}) — retry next run")
        return 0

    # one row per archived listing URL: (original, first_timestamp)
    listings = []
    for row in rows:
        if not row or row[0] == "original":
            continue
        u = row[0]
        if "ExternalTenderDetails" in u or u in seen_urls:
            continue
        listings.append((u, row[1] if len(row) > 1 else ""))

    for u, ts in listings[:args.max_snapshots]:
        if time.time() - t0 > args.time_budget:
            break
        try:
            replay = f"https://web.archive.org/web/{ts}id_/{u}" if ts else \
                     f"https://web.archive.org/web/2id_/{u}"
            body = fetch(replay).decode("utf-8", errors="replace")
            for m in sorted(set(ID_RE.findall(body))):
                rfx = int(m)
                if rfx in known:
                    continue
                known.add(rfx)
                with open(QUEUE_F, "a") as f:
                    f.write(json.dumps({
                        "url": (f"https://www.gets.govt.nz/"
                                f"ExternalTenderDetails.htm?id={rfx}"),
                        "source": "gets_history_enum",
                        "rfx_id": rfx,
                        "court": "gets",
                    }, ensure_ascii=False) + "\n")
                added += 1
            seen_urls.add(u)
            snaps += 1
            pages_done += 1
            time.sleep(1.0)
        except Exception as e:
            print(f"GETS history-enum: {u[:60]} failed ({str(e)[:50]})")
            time.sleep(1.0)

    state["seen_urls"] = sorted(seen_urls)
    with open(STATE_F, "w") as f:
        json.dump(state, f)
    print(f"GETS history-enum: snapshots={snaps} added={added} "
          f"known={len(known)} listings_total={len(listings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
