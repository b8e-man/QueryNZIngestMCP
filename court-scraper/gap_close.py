#!/usr/bin/env python3
"""Gap closer: probe missing cites (NZLII comparison) against the OFFICIAL
source (courtsofnz.govt.nz) and enqueue what is live.

NZLII is comparison-only — it tells us which judgments exist (IDs); capture
always happens from the official source. For each missing cite we probe the
canonical asset URL
    /assets/cases/<year>/<year>-<SERIES>-<num>.pdf
  200 -> enqueue for the normal capture tick (discovery gap closed)
  404 -> record as not-on-official-site (JDO back-catalogue evidence)

Scope: NZSC all years; NZCA/NZHC restricted to years given via --years
(default 2026) — older CA/HC judgments live only in JDO by design (see
nzlii_gap_report.md).

Resumable via gap_probe_done.json; polite 1 req/s (courtsofnz robots
allows all except /search/).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "/opt/data/court-scraper"
IDS_F = os.path.join(BASE, "nzlii_ids.jsonl")
CORPUS_FILES = ("records.jsonl", "done.jsonl", "queue.jsonl",
                "corpus_asset_ids.jsonl")
QUEUE_F = os.path.join(BASE, "queue.jsonl")
RESULT_F = os.path.join(BASE, "gap_probe_results.jsonl")
LEDGER_F = os.path.join(BASE, "gap_probe_done.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
ASSET = "https://www.courtsofnz.govt.nz/assets/cases/{y}/{y}-{s}-{n}.pdf"

sys.path.insert(0, BASE)
from nzlii_gap_check import norm, corpus_ids  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2026",
                    help="comma years for CA/HC probing (NZSC always all)")
    ap.add_argument("--time-budget", type=int, default=0)
    args = ap.parse_args()
    ca_hc_years = {int(y) for y in args.years.split(",")}
    t0 = time.time()

    nzlii = set()
    with open(IDS_F) as f:
        for line in f:
            try:
                r = json.loads(line)
                nzlii.add(norm(r["series"], r["year"], r["num"]))
            except Exception:
                pass
    ours = corpus_ids()
    missing = nzlii - ours

    probed = set()
    if os.path.exists(LEDGER_F):
        try:
            probed = {tuple(x) for x in json.load(open(LEDGER_F))}
        except Exception:
            probed = set()

    todo = sorted(
        (t for t in missing
         if (t[0] == "NZSC" or (t[0] in ("NZCA", "NZHC") and t[1] in ca_hc_years))
         and t not in probed),
        key=lambda t: (t[0], t[1], int(t[2])))

    enqueued = not_found = 0
    for series, year, num in todo:
        if args.time_budget and time.time() - t0 > args.time_budget:
            break
        url = ASSET.format(y=year, s=series, n=num)
        req = urllib.request.Request(url, headers={"User-Agent": UA},
                                     method="HEAD")
        code = 0
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = 0  # transient — leave out of ledger
        if code == 200:
            with open(QUEUE_F, "a") as f:
                f.write(json.dumps({"url": url, "source": "nzlii_gapcheck"})
                        + "\n")
            enqueued += 1
        elif code in (404, 410):
            with open(RESULT_F, "a") as f:
                f.write(json.dumps({"series": series, "year": year,
                                    "num": num, "http": code,
                                    "meaning": "not_on_courtsofnz"}) + "\n")
            not_found += 1
        else:
            continue
        probed.add((series, year, num))
        json.dump(sorted(list(p) for p in probed), open(LEDGER_F, "w"))
        time.sleep(1.0)
    print(f"GAPCLOSE probed={len(probed)} enqueued={enqueued} "
          f"not_on_official={not_found} remaining={len(todo) - enqueued - not_found}")


if __name__ == "__main__":
    main()
