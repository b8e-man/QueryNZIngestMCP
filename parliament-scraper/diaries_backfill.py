#!/usr/bin/env python3
"""One-shot diaries archive pass — page the aggregator export back to its
beginning (the diff collector only ever holds one 5,000-row window).

Follows the Link rel="next" cursor of
  https://ministerdiarysummaries.org.nz/ministerial_diaries_public/meetings.json
Rows are stored verbatim + `_collected` = now, appended to
data/diaries_records.jsonl (same shape as scrape_records.py writes), and
the rowids are merged into state/records_state.json so the live collector
never re-adds them. Idempotent: existing rowids are skipped.
"""

import json
import os
import time
import urllib.request

BASE = "/opt/data/parliament-scraper"
OUT_F = os.path.join(BASE, "data", "diaries_records.jsonl")
STATE_F = os.path.join(BASE, "state", "records_state.json")
START = ("https://ministerdiarysummaries.org.nz/ministerial_diaries_public/"
         "meetings.json?_shape=array&_size=5000")
UA = "Mozilla/5.0 (research)"
MAX_PAGES = 200


def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    seen = set()
    if os.path.exists(OUT_F):
        with open(OUT_F) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rid = json.loads(line).get("rowid")
                        if rid is not None:
                            seen.add(rid)
                    except ValueError:
                        pass
    state = {}
    if os.path.exists(STATE_F):
        with open(STATE_F) as f:
            state = json.load(f)
    seen.update(state.get("diary_rowids", []))

    url, pages, added, oldest = START, 0, 0, None
    stamp = now_iso()
    while url and pages < MAX_PAGES:
        pages += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read())
            link = r.headers.get("Link") or ""
        nxt = None
        for part in link.split(","):
            if 'rel="next"' in part:
                nxt = part[part.find("<") + 1:part.find(">")]
        if not rows:
            break
        new = []
        for rec in rows:
            rid = rec.get("rowid")
            if rid is None or rid in seen:
                continue
            rec["_collected"] = stamp
            new.append(rec)
            seen.add(rid)
        if new:
            with open(OUT_F, "a") as f:
                for rec in new:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += len(new)
            oldest = new[-1].get("date", oldest)
        url = nxt
        time.sleep(0.3)

    if added:
        state["diary_rowids"] = sorted(
            list(set(state.get("diary_rowids", [])) | {r for r in seen}))
        if len(state["diary_rowids"]) > 400000:
            state["diary_rowids"] = state["diary_rowids"][-300000:]
        os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
        with open(STATE_F, "w") as f:
            json.dump(state, f)
    print(f"diaries backfill: {pages} pages, +{added} rows, "
          f"oldest date seen {oldest}")


if __name__ == "__main__":
    main()
