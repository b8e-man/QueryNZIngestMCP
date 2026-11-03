#!/usr/bin/env python3
"""Māori Land Court + Māori Appellate Court enumeration via the JDO API.

Cracked 2026-11-03 (provider Q-mlc): /jdo-search-api accepts court NAMES:
  court='Māori Land Court'      (100 judgments in 2025, 76 in 2024, ~2 in 2020,
                                 none before 2015 — JDO holds the SELECTED set)
  court='Māori Appellate Court' (14 in 2025, 4 in 2024)
The court's own judgments page links justice.govt.nz/courts/decisions/
?Filter_Jurisdiction=24|468 = exactly these two. Citations are MB-style:
"[2025] Māori Appellate Court MB 45". The full minute-book corpus is on
the MLC site's "Our Record" (separate lane).

Rows -> queue.jsonl (kind=judgment_pdf; the capture tick fetches the
/jdo_documents/*.pdf bytes like any JDO row). Year windows, budget/resume
via state mlc_enum_state.json {court: [done years]}. Dedupe vs queue+done.
"""
import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "mlc_enum_state.json")
API = "https://www.justice.govt.nz/jdo-search-api"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture)")
SLEEP = 1.5
COURTS = {"Māori Land Court": "maori_land",
          "Māori Appellate Court": "maori_appellate"}
CIT = re.compile(r"\[(\d{4})\]\s*Māori (?:Land|Appellate) Court MB\s*(\d+)")
Y0, Y1 = 1990, datetime.now(timezone.utc).year


def load_urls(path):
    urls = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                urls.add(json.loads(line)["url"])
            except Exception:
                pass
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=80)
    args = ap.parse_args()
    deadline = time.time() + args.time_budget

    state = {}
    if os.path.exists(STATE_F):
        state = json.load(open(STATE_F))
    known = load_urls(QUEUE_F) | load_urls(DONE_F)

    report = []
    for court, tag in COURTS.items():
        done_years = set(state.get(court, []))
        added = 0
        for year in range(Y0, Y1 + 1):
            if time.time() > deadline:
                break
            if year in done_years:
                continue
            qs = urllib.parse.urlencode({
                "court": court,
                "judgmentDate": f"['{year}-01-01T00:00:00Z',"
                                f"'{year}-12-31T23:59:59Z']",
                "page": "1"})
            try:
                req = urllib.request.Request(f"{API}?{qs}",
                                             headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
            except Exception as e:
                report.append(f"{tag} {year}: fetch failed {e}")
                break
            rows = data.get("results") or []
            new = []
            for r in rows:
                u = urllib.parse.urljoin("https://www.justice.govt.nz",
                                         r.get("url", ""))
                if not u.lower().endswith(".pdf") or u in known:
                    continue
                cn = r.get("caseName", "")
                m = CIT.search(cn)
                rec = {"url": u, "source": "jdo_api",
                       "case_name": cn, "court": tag,
                       "kind": "judgment_pdf",
                       "citation": (f"[{m.group(1)}] Māori Land Court MB "
                                    f"{m.group(2)}" if m else ""),
                       "judgment_date": "",
                       "discovered_via": f"jdo_api:{tag}"}
                new.append(rec)
                known.add(u)
            if new:
                with open(QUEUE_F, "a") as f:
                    for rec in new:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += len(new)
            done_years.add(year)
            state[court] = sorted(done_years)
            with open(STATE_F, "w") as f:
                json.dump(state, f)
            time.sleep(SLEEP)
        if added:
            report.append(f"{tag}: +{added} ({len(done_years)}/{Y1 - Y0 + 1} years)")

    if report:
        print("mlc-enum: " + "; ".join(report))


if __name__ == "__main__":
    main()
