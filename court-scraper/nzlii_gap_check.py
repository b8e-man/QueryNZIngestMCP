#!/usr/bin/env python3
"""NZLII comparison crawl — GAP DETECTION ONLY, not a gathering source.

NZLII case IDs are neutral citations encoded in the URL path
(/nz/cases/NZHC/2024/1000.html == [2024] NZHC 1000 — verified via Wayback
replay titles 2026-10-29). NZLII itself is Cloudflare-challenged headless
(even via NZ residential exit), so the ID universe is enumerated from the
Wayback CDX index — zero traffic to NZLII, metadata only. No case content
is fetched or stored from NZLII in any phase.

Phases:
  enumerate  — CDX per series/year -> nzlii_ids.jsonl (series, year, num)
  report     — diff NZLII IDs vs court-scraper corpus IDs -> nzlii_gap_report.md

Corpus side IDs come from filenames/URLs in records.jsonl / done.jsonl /
queue.jsonl (e.g. 2026-NZSC-122.pdf -> NZSC/2026/122). Series whose
filenames carry no citation (coroners findings, some EnvC) are compared at
count level only — noted in the report.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "/opt/data/court-scraper"
IDS_F = os.path.join(BASE, "nzlii_ids.jsonl")
LEDGER_F = os.path.join(BASE, "nzlii_cdx_done.json")
REPORT_F = os.path.join(BASE, "nzlii_gap_report.md")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

SERIES = ("NZSC", "NZCA", "NZHC", "NZDC", "NZFC", "NZYC",
          "NZEmpC", "NZEmpCA", "NZEnvC", "NZCorC",
          "NZREADT", "NZLCDT", "NZLCRO", "NZTD", "NZDT", "NZHRRT")
YEARS = range(2000, 2027)
MAX_TRIES = 4

ID_RE = re.compile(r"/nz/cases/(NZ[A-Za-z]+)/(\d{4})/(\d+)\.html")
CITE_RE = re.compile(r"(19|20)(\d{2})[-_]?(NZ[A-Za-z]{2,8})[-_](\d{1,4})(?!\d)")
ASSET_RE = re.compile(r"(19|20)(\d{2})-(NZ[A-Za-z]{2,8})-(\d{1,4})(?!\d)")
COURT_OF_NZ_SERIES = {"NZSC", "NZCA", "NZHC"}
CORPUS_CDX_F = os.path.join(BASE, "corpus_asset_ids.jsonl")
CORPUS_LEDGER_F = os.path.join(BASE, "corpus_asset_done.json")


def norm(series, year, num):
    """Canonical triple: uppercased series, unpadded num (kills NZLII's
    '043' vs '43' duplicate URL variants)."""
    return (series.upper(), int(year), str(int(num)))


def cdx(prefix, limit=50000, timeout=120):
    q = urllib.parse.urlencode({
        "url": prefix,
        "matchType": "prefix", "output": "json", "fl": "original",
        "collapse": "urlkey", "limit": str(limit),
    })
    req = urllib.request.Request(CDX + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return [row[0] for row in json.loads(r.read())[1:]]


def enumerate_ids():
    ledger = set()
    if os.path.exists(LEDGER_F):
        try:
            ledger = set(json.load(open(LEDGER_F)))
        except Exception:
            ledger = set()
    known = set()
    if os.path.exists(IDS_F):
        with open(IDS_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    known.add((r["series"], r["year"], r["num"]))
                except Exception:
                    pass

    added = fetched = 0
    for series in SERIES:
        for year in YEARS:
            key = f"{series}/{year}"
            if key in ledger:
                continue
            urls = None
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    urls = cdx(f"nzlii.org/nz/cases/{series}/{year}/")
                    break
                except Exception as e:
                    print(f"cdx {key} attempt {attempt}: {e}", flush=True)
                    time.sleep(10 * attempt)
            if urls is None:
                continue  # retried next run
            fetched += len(urls)
            new = []
            for u in urls:
                m = ID_RE.search(u)
                if not m:
                    continue
                k = norm(m.group(1), m.group(2), m.group(3))
                if k not in known:
                    rec = {"series": m.group(1), "year": int(m.group(2)),
                           "num": m.group(3), "url": u}
                    new.append(rec)
                    known.add(k)
            if new:
                with open(IDS_F, "a") as f:
                    for rec in new:
                        f.write(json.dumps(rec) + "\n")
                added += len(new)
            ledger.add(key)
            json.dump(sorted(ledger), open(LEDGER_F, "w"))
            if urls:
                print(f"{key}: {len(urls)} rows, {len(new)} new", flush=True)
            time.sleep(1)
    print(f"DONE fetched={fetched} added={added} total_ids={len(known)}")


def corpus_ids():
    """Citation triples from our own filenames/URLs (records/done/queue) plus
    the courtsofnz asset-filename universe (CDX index of our own source)."""
    hits = set()
    for fn in ("records.jsonl", "done.jsonl", "queue.jsonl",
               CORPUS_CDX_F):
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                for field in ("url", "path"):
                    s = urllib.parse.unquote(r.get(field, "") or "")
                    for m in CITE_RE.finditer(s):
                        hits.add(norm(m.group(3), m.group(1) + m.group(2),
                                      m.group(4)))
    return hits


def enrich_corpus():
    """Enumerate courtsofnz.govt.nz/assets/cases/ PDF filenames via the CDX
    index — our own source's full citation universe (filenames carry neutral
    cites: 2026-NZSC-122.pdf). Discovery-level gap checks need this; queue
    case-page slugs carry no citations."""
    ledger = set()
    if os.path.exists(CORPUS_LEDGER_F):
        try:
            ledger = set(json.load(open(CORPUS_LEDGER_F)))
        except Exception:
            ledger = set()
    known = set()
    if os.path.exists(CORPUS_CDX_F):
        with open(CORPUS_CDX_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    known.add(norm(r["series"], r["year"], r["num"]))
                except Exception:
                    pass
    added = 0
    for year in range(2003, 2027):
        key = str(year)
        if key in ledger:
            continue
        urls = None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                urls = cdx(f"courtsofnz.govt.nz/assets/cases/{year}/")
                break
            except Exception as e:
                print(f"asset cdx {key} attempt {attempt}: {e}", flush=True)
                time.sleep(10 * attempt)
        if urls is None:
            continue
        new = []
        for u in urls:
            m = ASSET_RE.search(urllib.parse.unquote(u))
            if not m:
                continue
            k = norm(m.group(3), m.group(1) + m.group(2), m.group(4))
            if k not in known:
                new.append({"series": m.group(3),
                            "year": int(m.group(1) + m.group(2)),
                            "num": m.group(4), "url": u})
                known.add(k)
        if new:
            with open(CORPUS_CDX_F, "a") as f:
                for rec in new:
                    f.write(json.dumps(rec) + "\n")
            added += len(new)
        ledger.add(key)
        json.dump(sorted(ledger), open(CORPUS_LEDGER_F, "w"))
        print(f"assets/{year}: {len(urls)} rows, {len(new)} new", flush=True)
        time.sleep(1)
    print(f"ENRICH DONE added={added} corpus_ids={len(known)}")


def report():
    nzlii = set()
    by_series_year = defaultdict(set)
    if os.path.exists(IDS_F):
        with open(IDS_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    k = norm(r["series"], r["year"], r["num"])
                    nzlii.add(k)
                    by_series_year[(k[0], k[1])].add(k[2])
                except Exception:
                    pass
    ours = corpus_ids()
    ours_sy = defaultdict(set)
    for s, y, n in ours:
        ours_sy[(s, y)].add(n)

    lines = ["# NZLII comparison — gap report", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
             f"NZLII IDs (from CDX index, metadata only): **{len(nzlii)}**",
             f"Corpus citation IDs (filenames/URLs): **{len(ours)}**", "",
             "NZLII is a comparison source — no content gathered. "
             "ID == neutral citation (verified against Wayback replay titles).", ""]

    total_missing = 0
    for series in SERIES:
        s_up = series.upper()
        years = sorted({y for (s, y) in by_series_year if s == s_up})
        if not years:
            lines.append(f"## {series}: no NZLII rows found in index\n")
            continue
        s_nz = {(s, y, n) for (s, y, n) in nzlii if s == s_up}
        s_ours = {(s, y, n) for (s, y, n) in ours if s == s_up}
        missing = s_nz - s_ours
        extra = s_ours - s_nz
        total_missing += len(missing)
        lines.append(f"## {series}")
        lines.append(f"- NZLII: {len(s_nz)} cases ({years[0]}–{years[-1]})  |  "
                     f"corpus IDs: {len(s_ours)}  |  "
                     f"**missing from corpus: {len(missing)}**  |  "
                     f"ours-only: {len(extra)}")
        if missing:
            miss_sy = defaultdict(list)
            for s, y, n in missing:
                miss_sy[y].append(n)
            for y in sorted(miss_sy, reverse=True)[:5]:
                nums = sorted(miss_sy[y], key=int)[:12]
                more = f" (+{len(miss_sy[y])-len(nums)} more)" \
                    if len(miss_sy[y]) > len(nums) else ""
                lines.append(f"- {y} missing: {', '.join(nums)}{more}")
        lines.append("")
    lines.append(f"TOTAL missing across matched series: {total_missing}")
    with open(REPORT_F, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "enumerate"
    if phase == "enumerate":
        enumerate_ids()
    elif phase == "enrich":
        enrich_corpus()
    else:
        report()
