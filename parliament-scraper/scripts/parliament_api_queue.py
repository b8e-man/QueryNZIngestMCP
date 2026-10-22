#!/usr/bin/env python3
"""Parliament API queue processor — drains the POST-endpoint corpora.

Corpora (all paginated POST /api/data/search[/{corpus}]):
  questions  683,552 written Q&As (also captured forward by scrape_records)
  ur-debates 125 | estimates-of-appropriations 54 | SOPs 114 | books 775
  bills      92 current bills (REQUIRES the full SPA body shape)

Record level. Chunky metadata already in rows; full texts for WQ (questionText
+ replyText). Written to /opt/data/parliament-scraper/data/api_queue/{corpus}.jsonl.

Burn resilience (Radware bans the IP at TCP level under burst — learned
2026-10-22):
  * 0.8s polite delay between requests
  * cursor state per corpus in api_queue_state.json — ticks resume mid-corpus
  * connection failures: 3 retries with backoff (30/120/300s), then switch to
    the IPRoyal proxy for the rest of the run
  * totalResults==-1 = wrong shape or soft block -> treat as failure
  * --time-budget keeps the run inside the 120s cron-kill window
Exit: silent 0 on progress; stderr + 1 on repeated failure.
"""

import argparse
import base64
import json
import os
import random
import secrets
import sys
import time
from datetime import datetime, timezone

import requests

BASE = "/opt/data/parliament-scraper"
OUT_DIR = os.path.join(BASE, "data", "api_queue")
STATE_F = os.path.join(BASE, "api_queue_state.json")
PROXY_F = "/opt/data/beehive-scraper/proxy.json"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
SLEEP = 0.8

BILLS_SHAPE = {
    "id": None, "documentPreset": 1, "keyword": None, "selectCommittee": None,
    "status": [], "documentTypes": [], "documentSubtypes": [],
    "beforeCommittee": None, "billStages": [], "billTab": "Current",
    "billId": None, "includeBillStages": True, "subject": None, "person": None,
    "parliament": None, "dateFrom": None, "dateTo": None, "datePeriod": None,
    "restrictedFrom": None, "restrictedTo": None, "terminatedReason": None,
    "sortBy": None, "sortDirection": None,
}

CORPORA = [
    # (name, url, items_key, total_key, full_shape)
    ("questions", "https://questions.parliament.nz/api/data/search",
     "value", "@odata.count", False),
    ("bills", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", True),
    ("ur-debates", "https://searches.parliament.nz/api/data/search/ur-debates",
     "results", "totalResults", False),
    ("estimates-of-appropriations",
     "https://searches.parliament.nz/api/data/search/estimates-of-appropriations",
     "results", "totalResults", False),
    ("SOPs", "https://searches.parliament.nz/api/data/search/SOPs",
     "results", "totalResults", False),
    ("books", "https://searches.parliament.nz/api/data/search/books",
     "results", "totalResults", False),
]


def get_proxy():
    cfg = json.load(open(PROXY_F))
    sess = "s" + secrets.token_hex(5)
    pw = (base64.b64decode(cfg["password_base_b64"]).decode()
          + f"_country-nz_session-{sess}_lifetime-30m")
    user = base64.b64decode(cfg["username_b64"]).decode()
    return {"http": f"http://{user}:{pw}@geo.iproyal.com:12321",
            "https": f"http://{user}:{pw}@geo.iproyal.com:12321"}


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.use_proxy = False

    def post(self, url, body, deadline=None):
        last_err = None
        for attempt, backoff in enumerate((0, 30, 120, 300)):
            if backoff:
                if deadline and time.time() + backoff > deadline:
                    raise RuntimeError(f"budget exhausted (last: {last_err})")
                time.sleep(backoff)
            try:
                proxies = get_proxy() if self.use_proxy else None
                r = self.session.post(url, json=body, timeout=30, proxies=proxies)
                if r.status_code == 200 and r.text.strip():
                    return r.json()
                last_err = f"HTTP {r.status_code} {r.text[:60]!r}"
            except Exception as e:
                last_err = str(e)[:100]
            if attempt == 1 and not self.use_proxy:
                self.use_proxy = True   # direct burned -> proxy for the rest
        raise RuntimeError(last_err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=95)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    state = {}
    if os.path.exists(STATE_F):
        state = json.load(open(STATE_F))

    fetcher = Fetcher()
    t0 = time.time()
    report = []
    hard_fail = False

    for name, url, items_key, total_key, full_shape in CORPORA:
        if time.time() - t0 > args.time_budget:
            break
        deadline = t0 + args.time_budget
        out_f = os.path.join(OUT_DIR, f"{name}.jsonl")
        done_pages = state.get(name, {}).get("pages_done", 0)
        total = state.get(name, {}).get("total")
        page = done_pages + 1
        got = 0
        while time.time() - t0 < args.time_budget:
            body = dict(BILLS_SHAPE) if full_shape else {}
            body.update({"pageSize": 100, "page": page})
            try:
                resp = fetcher.post(url, body, deadline)
            except RuntimeError as e:
                hard_fail = True
                report.append(f"{name}: fetch failed at page {page}: {e}")
                break
            if total is None:
                total = resp.get(total_key, 0)
                if total in (None, -1):
                    hard_fail = True
                    report.append(f"{name}: bad total {resp.get(total_key)!r}")
                    break
            items = resp.get(items_key) or []
            if not items:
                break
            with open(out_f, "a") as f:
                for it in items:
                    it["_corpus"] = name
                    it["_fetched_at"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds")
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            got += len(items)
            page += 1
            state[name] = {"pages_done": page - 1, "total": total}
            with open(STATE_F, "w") as f:
                json.dump(state, f)
            if len(items) < 100:
                break
            time.sleep(SLEEP)
        if got:
            report.append(f"{name}: +{got} records (page {done_pages+1}..{page-1} of ~{total})")

    with open(STATE_F, "w") as f:
        json.dump(state, f)
    if hard_fail:
        print("parliament api queue: " + "; ".join(report), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
