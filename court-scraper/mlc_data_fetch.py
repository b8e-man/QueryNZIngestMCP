#!/usr/bin/env python3
"""MLC bulk data capture — the Māori Land Data page's downloadable datasets
(annual Māori Land Updates 2011-2025, National Lists of Māori Land Blocks,
National Registers of Māori Incorporations). Byte-exact, manifest with
sha256. Resumable. One-shot (28 files), re-run picks up new editions since
the site updates URLs per edition year.
"""
import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
OUT_DIR = os.path.join(BASE, "data", "mlc_data")
MANIFEST = os.path.join(BASE, "data", "mlc_data_manifest.jsonl")
SITE = "https://www.xn--morilandcourt-wqb.govt.nz"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture)")
SLEEP = 0.8

FILES = [
    "/assets/Documents/Maori-Land-Data/2025-10-28-MLC-Maori-Land-Update-2025.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2024.pdf",
    "/assets/Documents/Maori-Land-Data/2023-05-19-MoJ-MLC-Maori-Land-Update-ver-1.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2022.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2021.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2020.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2019.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2018.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2017.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2016.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2015.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2014.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2013.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2012.pdf",
    "/assets/Documents/Maori-Land-Data/Maori-Land-Update-2011.pdf",
    "/assets/Documents/Maori-Land-Data/MLC-2025-06-30-National-List-Maori-Land-in-New-Zealand.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2024-06-30-National-List-Maori-Land-in-New-Zealand.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2023-05-19-National-List-Maori-Land-in-New-Zealand-v1.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2022-07-19-Maori-Land-in-New-Zealand-National-List.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2021-10-08-National-List-Maori-Land-in-New-Zealand-Ver1.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2018-06-30-National-List-Maori-Land-in-New-Zealand.xls",
    "/assets/Documents/Maori-Land-Data/MLC-2017-06-30-National-List-Maori-Land-in-New-Zealand.xls",
    "/assets/Documents/Maori-Land-Data/MLC-2016-06-30-National-List-Maori-Land-in-New-Zealand.xls",
    "/assets/Documents/Maori-Land-Data/MLC-2025-06-30-National-Register-of-Maori-Incorporations.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2024-06-30-National-Register-of-Maori-Incorporations.xlsx",
    "/assets/Documents/Maori-Land-Data/MLC-2023-05-19-National-Register-of-Maori-Incorporations-v1.xlsx",
    "/assets/Documents/Incorporation-Register/MLC-2022-18-07-Register-of-Maori-Incorporations-for-New-Zealand-version-2.xlsx",
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    done = set()
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST):
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add(r["url"])
            except ValueError:
                pass
    got = 0
    for path in FILES:
        url = SITE + path
        if url in done:
            continue
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", path.split("/")[-1])
        dest = os.path.join(OUT_DIR, fname)
        entry = {"url": url, "path": dest,
                 "fetched_at": datetime.now(timezone.utc).isoformat(
                     timespec="seconds")}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read()
            with open(dest, "wb") as f:
                f.write(body)
            entry.update(status="ok", bytes=len(body),
                         sha256=hashlib.sha256(body).hexdigest())
            got += 1
        except Exception as e:
            entry.update(status=f"error:{e}")
        with open(MANIFEST, "a") as f:
            f.write(json.dumps(entry) + "\n")
        time.sleep(SLEEP)
    if got:
        print(f"mlc-data: +{got} files")


if __name__ == "__main__":
    main()
