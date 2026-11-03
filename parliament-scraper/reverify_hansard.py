#!/usr/bin/env python3
"""Hansard re-verify: catch corrected PDFs published in place (provider
Q32, 2026-11-03). The daily tick fetches each sitting day's PDF once;
Parliament later replaces drafts with corrected versions at the same URL.
This pass re-fetches a bounded recent window oldest-checked-first and,
on byte change, JOINS the corrected version — old bytes kept, new bytes
stored as a sha-suffixed sibling, a change_events.jsonl row emitted
(same convention as court-scraper/reverify_courts.py).

State: data/hansard_reverify_state.json (url -> last_checked).
"""
import argparse, hashlib, json, os, sys, time
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
REC = os.path.join(DATA, "hansard_debates.jsonl")
EVENTS = os.path.join(DATA, "change_events.jsonl")
STATE = os.path.join(DATA, "hansard_reverify_state.json")
RAW = os.path.join(BASE, "raw")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--window-days", type=int, default=120)
    ap.add_argument("--time-budget", type=int, default=90)
    args = ap.parse_args()
    t0 = time.time()
    deadline = t0 + args.time_budget

    state = {}
    if os.path.exists(STATE):
        state = json.load(open(STATE))

    rows = []
    for line in open(REC):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    # window: last N sitting days, from 28 Apr 2026 on (the draft era)
    dates = sorted({r.get("sitting_date") for r in rows if r.get("sitting_date")})
    cutoff = dates[max(0, len(dates) - 1)][:]
    win = [d for d in dates if d >= "2026-04-28"][-args.window_days:]
    winset = set(win)
    cand = [r for r in rows if r.get("sitting_date") in winset]
    # oldest-checked-first
    cand.sort(key=lambda r: (state.get(r["url"], ""), r.get("sitting_date", "")))

    events = 0
    checked = 0
    for r in cand:
        if checked >= args.limit or time.time() > deadline:
            break
        url = r["url"]
        state[url] = now_iso()
        checked += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    continue
                body = resp.read()
        except Exception:
            continue
        h = hashlib.sha256(body).hexdigest()
        if h == r.get("sha256"):
            continue
        # corrected/changed in place -> JOIN: sibling bytes + event
        sib = f"raw/hansard_{r.get('sitting_date')}_{h[:8]}.pdf"
        with open(os.path.join(BASE, sib), "wb") as f:
            f.write(body)
        ev = {"url": url, "event": "content_changed", "detected_at": now_iso(),
              "prev_sha256": r.get("sha256"), "new_sha256": h, "path": sib,
              "corpus": "parliament-hansard-debates",
              "sitting_date": r.get("sitting_date"),
              "note": "draft replaced by corrected version (bytes joined, "
                      "original retained)"}
        with open(EVENTS, "a") as f:
            f.write(json.dumps(ev) + "\n")
        events += 1
        time.sleep(1.0)
    with open(STATE, "w") as f:
        json.dump(state, f)
    print(f"hansard reverify: checked={checked} events={events}")
    sys.exit(0)

if __name__ == "__main__":
    main()
