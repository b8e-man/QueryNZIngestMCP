#!/usr/bin/env python3
"""Parliament API queue processor — drains the POST-endpoint corpora.

Corpora (paginated POST /api/data/search[/{corpus}]):
  questions  683,552 written Q&As (full questionText + replyText)
  ur-debates 333K | estimates | SOPs | books | bills 92 (full SPA body shape)

OFFSET CAP (learned 2026-10-22): the API 500s on any query past offset
~100,100 regardless of page size — plain pagination cannot reach the rest.
Workaround: year sharding via dateFrom/dateTo (verified: 2010 -> 38,963).
Any corpus whose total exceeds the cap is automatically drained year by year;
oversized years would split monthly (none expected). Records already captured
are deduped by record id.

Burn resilience: 0.8s polite delay; per-corpus cursor state in
api_queue_state.json; retries with backoff (30/120/300s) then proxy fallback;
--time-budget keeps runs inside the 120s cron-kill window (budget exhaustion
is a NORMAL tick end, silent exit 0). Alerts only after 3 consecutive failed
ticks. Output: data/api_queue/{corpus}.jsonl. Silent on success.
"""

import argparse
import base64
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone

import requests

BASE = "/opt/data/parliament-scraper"
OUT_DIR = os.path.join(BASE, "data", "api_queue")
STATE_F = os.path.join(BASE, "api_queue_state.json")
PROXY_F= "/opt/data/beehive-scraper/proxy.json"
SLEEP = 0.8
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
OFFSET_CAP = 90000          # stay under the ~100,100 hard server cap

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
    ("questions", "https://questions.parliament.nz/api/data/search",
     "value", "@odata.count", None),
    ("bills", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", BILLS_SHAPE),
    ("bills-historical", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", dict(BILLS_SHAPE, billTab="Historical")),
    ("SOPs", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", dict(BILLS_SHAPE, documentPreset=9)),
    ("sc-reports", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", dict(BILLS_SHAPE, documentPreset=14)),
    ("sc-submissions", "https://bills.parliament.nz/api/data/search",
     "results", "totalResults", dict(BILLS_SHAPE, documentPreset=10)),
]

YEAR_SHARDS = [(f"{y}-01-01", f"{y}-12-31") for y in range(2026, 1989, -1)]


def get_proxy():
    cfg = json.load(open(PROXY_F))
    sess = "s" + secrets.token_hex(5)
    pw = (base64.b64decode(cfg["password_base_b64"]).decode()
          + f"_country-nz_session-{sess}_lifetime-30m")
    user = base64.b64decode(cfg["username_b64"]).decode()
    return {"http": f"http://{user}:{pw}@geo.iproyal.com:12321",
            "https": f"http://{user}:{pw}@geo.iproyal.com:12321"}


class BudgetExhausted(Exception):
    """Time budget ran out mid-retry — normal tick end, NOT a failure."""


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
                    raise BudgetExhausted(f"tick budget ended mid-retry (last: {last_err})")
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


def load_seen(corpus):
    """Record ids already captured — shards overlap the unsharded prefix."""
    seen = set()
    path = os.path.join(OUT_DIR, f"{corpus}.jsonl")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    seen.add(json.loads(line).get("id"))
                except Exception:
                    pass
    return seen


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
    deadline = t0 + args.time_budget
    report = []
    hard_fail = False

    for name, url, items_key, total_key, shape in CORPORA:
        if time.time() > deadline:
            break
        cstate = state.get(name, {})
        total = cstate.get("total")
        out_f = os.path.join(OUT_DIR, f"{name}.jsonl")

        # discover total + shard plan on first touch
        if total is None:
            probe = dict(shape) if shape else {}
            probe.update({"pageSize": 1, "page": 1})
            try:
                resp = fetcher.post(url, probe, deadline)
            except BudgetExhausted as e:
                report.append(f"{name}: {e}")
                break
            except RuntimeError as e:
                hard_fail = True
                report.append(f"{name}: probe failed: {e}")
                continue
            total = resp.get(total_key, 0)
            if not total or total == -1:
                hard_fail = True
                report.append(f"{name}: bad total {resp.get(total_key)!r}")
                continue
            cstate["total"] = total
            cstate["shards"] = {}
            state[name] = cstate

        if not cstate.get("shards"):
            cstate["shards"] = ({"__all__": 0} if total <= OFFSET_CAP
                                else {f"{a}..{b}": 0 for a, b in YEAR_SHARDS})
            state[name] = cstate

        seen = None          # lazy: the 683k-row dedupe load only if pages write
        got = 0
        cur_year = (f"{datetime.now(timezone.utc).year}-01-01.."
                    f"{datetime.now(timezone.utc).year}-12-31")
        shard_list = list(cstate["shards"].items())
        for label, pages_done in shard_list:
            if time.time() > deadline:
                break
            if label in cstate.get("done", []) and label != cur_year:
                continue          # exhausted archive shard — never re-probe
            body = dict(shape) if shape else {}
            if label != "__all__":
                a, b = label.split("..")
                body.update({"dateFrom": a, "dateTo": b})
            page = pages_done + 1
            while time.time() < deadline:
                body.update({"pageSize": 100, "page": page})
                try:
                    resp = fetcher.post(url, body, deadline)
                except BudgetExhausted as e:
                    report.append(f"{name}[{label}]: {e}")
                    break
                except RuntimeError as e:
                    hard_fail = True
                    report.append(f"{name}[{label}]: fetch failed at page {page}: {e}")
                    break
                items = resp.get(items_key) or []
                if items:
                    if seen is None:
                        seen = load_seen(name)
                    with open(out_f, "a") as f:
                        for it in items:
                            if it.get("id") in seen:
                                continue
                            seen.add(it.get("id"))
                            it["_corpus"] = name
                            it["_shard"] = label
                            it["_fetched_at"] = datetime.now(timezone.utc).isoformat(
                                timespec="seconds")
                            f.write(json.dumps(it, ensure_ascii=False) + "\n")
                            got += 1
                    cstate["shards"][label] = page
                    with open(STATE_F, "w") as f:
                        json.dump(state, f)
                if len(items) < 100:          # shard exhausted (empty page too)
                    if label not in ("__all__", cur_year):
                        cstate.setdefault("done", []).append(label)
                        with open(STATE_F, "w") as f:
                            json.dump(state, f)
                    break
                page += 1
                time.sleep(SLEEP)
        if got:
            report.append(f"{name}: +{got} records (total {total})")

    state["_consecutive_failures"] = (state.get("_consecutive_failures", 0) + 1
                                      if hard_fail else 0)
    with open(STATE_F, "w") as f:
        json.dump(state, f)
    if hard_fail and state["_consecutive_failures"] >= 3:
        print("parliament api queue: " + "; ".join(report), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
