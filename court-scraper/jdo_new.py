#!/usr/bin/env python3
"""JDO "everything new" ticker — the upstream freshness pipe.

The Ministry of Justice's Judicial Decisions Online indexes EVERY new
judgment (HC/CA/DC/FC/YC/tribunals) as it is deposited — upstream of
courtsofnz (selected only), NZLII, and OpenLaw. Its JSON search API is
served over plain HTTP and is NOT robots-disallowed (robots `/*/jdo`
suffix-matches /jdo only; /jdo-search-api does not match):

  GET /jdo-search-api?court=All&judgmentDate=['<from>','<to>']&page=N
  -> {"count": N, "results": [{"caseName": "... [2026] NZHC 3251 ...",
                               "url": "/jdo_documents/<uuid>.pdf"}, ...]}

Politeness: incremental only — a rolling lookback window (default 30d,
covers late deposits), dedupe against queue/done, ~1.5s between pages.
The PDFs themselves (/jdo_documents/ IS robots-disallowed) are fetched by
the capture tick's existing gentle lane (POLITE_SLEEP justice.govt.nz).
User direction: "scrape jdo politely" pending the MoJ email thread;
back-catalogue bulk stays with the institutional ask, NOT this ticker.
"""

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
LOGS = os.path.join(BASE, "logs", "jdo_new.log")
API = "https://www.justice.govt.nz/jdo-search-api"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")


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
    ap.add_argument("--lookback-days", type=int, default=30)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=args.lookback_days)).strftime(
        "%Y-%m-%dT00:00:00Z")
    to = now.strftime("%Y-%m-%dT23:59:59Z")
    window = f"['{frm}','{to}']"

    queued = load_urls(QUEUE_F)
    done = load_urls(DONE_F)
    known = queued | done

    added = seen = 0
    page = 1
    while True:
        qs = urllib.parse.urlencode({
            "court": "All", "judgmentDate": window, "page": str(page)})
        try:
            data = fetch_json(f"{API}?{qs}")
        except Exception as e:
            print(f"page {page}: {e}", flush=True)
            time.sleep(5)
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
                new.append({"url": u, "source": "jdo_api",
                            "case_name": r.get("caseName", "")})
                known.add(u)
        if new:
            with open(QUEUE_F, "a") as f:
                for rec in new:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += len(new)
        if len(results) < 10:
            break
        page += 1
        time.sleep(1.5)

    os.makedirs(os.path.dirname(LOGS), exist_ok=True)
    with open(LOGS, "a") as f:
        f.write(f"{now.isoformat(timespec='seconds')} window={args.lookback_days}d "
                f"seen={seen} added={added} queue={len(queued) + added}\n")
    if added:
        print(f"JDO new: {added} new decisions queued "
              f"({seen} in {args.lookback_days}d window)")


if __name__ == "__main__":
    main()
