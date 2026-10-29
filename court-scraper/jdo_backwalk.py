#!/usr/bin/env python3
"""JDO backwalk — polite historical enumeration of the full JDO corpus.

JDO's /jdo-search-api serves history via judgmentDate windows (verified:
2005–2026, 53,002 judgments, 50 results/page; nothing pre-2005). This walks
MONTHLY windows BACKWARDS from the current month to 2005-01, enumerating
every judgment PDF URL into the capture queue.

Politeness: budgeted per tick (--max-windows, --time-budget), 1.5s between
API pages. The PDF fetches themselves are paced by the capture tick's
gentle justice.govt.nz lane (POLITE_SLEEP) — this script only enumerates.
User direction: "set up a backwalk for JDO" (2026-10-29); the MoJ email
thread remains a courtesy, not a dependency.

State: jdo_backwalk_state.json — remaining window list; completion marker
written once, then runs stay silent. Idempotent; dedupe vs queue/done.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "jdo_backwalk_state.json")
LOGS = os.path.join(BASE, "logs", "jdo_backwalk.log")
API = "https://www.justice.govt.nz/jdo-search-api"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")

START = (2005, 1)


def month_windows_backwards():
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    while (y, m) >= START:
        yield y, m
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def window_range(y, m):
    frm = f"{y}-{m}-1T00:00:00Z"
    last = 31 if m in (1, 3, 5, 7, 8, 10, 12) else 30 if m != 2 else \
        (29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28)
    to = f"{y}-{m}-{last}T23:59:59Z"
    return f"['{frm}','{to}']"


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


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-windows", type=int, default=8)
    ap.add_argument("--time-budget", type=int, default=100)
    args = ap.parse_args()
    t0 = time.time()

    state = {"pending": [], "complete": False}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except Exception:
            pass
    if state.get("complete"):
        sys.exit(0)
    if not state["pending"]:
        state["pending"] = [f"{y}-{m:02d}"
                            for y, m in month_windows_backwards()]

    queued = load_urls(QUEUE_F)
    done = load_urls(DONE_F)
    known = queued | done

    added = seen = windows = 0
    while state["pending"] and windows < args.max_windows \
            and time.time() - t0 < args.time_budget:
        key = state["pending"][0]
        y, m = (int(x) for x in key.split("-"))
        win = window_range(y, m)
        page = 1
        window_done = True
        while True:
            if time.time() - t0 > args.time_budget:
                window_done = False
                break
            qs = urllib.parse.urlencode({
                "court": "All", "judgmentDate": win, "page": str(page)})
            try:
                data = fetch_json(f"{API}?{qs}")
            except Exception as e:
                print(f"{key} page {page}: {e}", flush=True)
                window_done = False  # retry this window next run
                break
            results = data.get("results") or []
            if not results:
                break
            seen += len(results)
            new = []
            for r in results:
                u = r.get("url", "")
                if not u.lower().endswith(".pdf"):
                    continue
                u = urllib.parse.urljoin("https://www.justice.govt.nz", u)
                if u not in known:
                    new.append({"url": u, "source": "jdo_backwalk",
                                "case_name": r.get("caseName", "")})
                    known.add(u)
            if new:
                with open(QUEUE_F, "a") as f:
                    for rec in new:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                queued.update(rec["url"] for rec in new)
                added += len(new)
            if len(results) < 50:
                break
            page += 1
            time.sleep(1.5)
        if window_done:
            state["pending"].pop(0)
            windows += 1
        json.dump(state, open(STATE_F, "w"))
        time.sleep(1)

    if not state["pending"]:
        state["complete"] = True
        json.dump(state, open(STATE_F, "w"))
    os.makedirs(os.path.dirname(LOGS), exist_ok=True)
    with open(LOGS, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                f"windows={windows} seen={seen} added={added} "
                f"pending={len(state['pending'])} "
                f"complete={state['complete']}\n")
    if state["complete"]:
        print(f"JDO BACKWALK COMPLETE: {seen} seen, {added} added this run, "
              f"queue={len(queued)}")
    elif added:
        print(f"JDO backwalk: +{added} queued ({seen} seen, "
              f"{len(state['pending'])} windows left)")


if __name__ == "__main__":
    main()
