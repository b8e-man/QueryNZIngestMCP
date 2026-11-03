#!/usr/bin/env python3
"""Reclassify courts records from metadata only (filename / URL / case_name).

Fills: court tag, citation, doc_date. Pure metadata — never touches stored
bytes, path, sha256 or capture provenance. Backs up records.jsonl first.

2026-11-03: fixes the classifier hole found in the provider audit —
4,400 court judgments sitting in a generic 'tribunals' bucket (filename
citations never parsed), 5,947 untagged rows, 11,314 missing doc_date.
"""
import json, os, re, shutil, sys

REC = "/opt/data/court-scraper/records.jsonl"
MONTHS = ("January February March April May June July August September "
          "October November December").split()
MN = {m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)}

COURT_MAP = {
    "NZSC": "supreme-court", "NZCA": "court-of-appeal", "NZHC": "high-court",
    "NZDC": "district-court", "NZFC": "family-court", "NZYC": "youth-court",
    "NZEMPC": "employment-court", "NZENVC": "environment-court",
    "NZACC": "district-court", "NZREADT": "readt", "NZHRRT": "hrrt",
    "NZIPT": "ipt", "NZARLA": "arla", "NZLCDT": "lcdt",
    "NZTDT": "teachers", "NZMVDT": "mvdt", "NZTT": "tenancy",
    "NZCMAC": "court-martial-appeal", "NZERA": "era",
    "NZAGDET": "agdet", "NZACC": "district-court",
}
HOST_MAP = [
    ("determinations.era.govt.nz", "era"),
    ("hpdt.org.nz", "hpdt"),
    ("waitangitribunal.govt.nz", "waitangi"),
    ("coronerscourt.govt.nz", "coroners-court"),
    ("employmentcourt.govt.nz", "employment-court"),
    ("environmentcourt.govt.nz", "environment-court"),
]
GENERIC = {"", "tribunals", "unknown", None}

CIT_BR = re.compile(r"\[((?:19|20)\d{2})\]\s*(NZ[A-Za-z]+)\s+(\d+)")
CIT_FN = re.compile(r"((?:19|20)\d{2})-([A-Z][A-Za-z]{1,9})-(\d{1,5})")
DATE_BR = re.compile(r"\[(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+((?:19|20)\d{2})\]")
DATE_FN = re.compile(r"[-_](\d{1,2})[-_]([A-Za-z]{3,9})[-_]((?:19|20)\d{2})")
ISO_FN = re.compile(r"((?:19|20)\d{2}-\d{2}-\d{2})")
YR = re.compile(r"/((?:19|20)\d{2})/")

def parse(r):
    fn = os.path.basename(r.get("url", "").split("?")[0])
    url = r.get("url", "")
    name = str(r.get("case_name") or "")
    cit = (r.get("citation") or "").strip()
    doc_date = (r.get("doc_date") or "").strip()
    court = (r.get("court") or "").strip()

    # citation
    year = code = num = None
    if not cit:
        m = CIT_BR.search(name) or CIT_FN.search(fn)
        if m:
            year, code, num = m.group(1), m.group(2).upper(), m.group(3)
            cit = f"[{year}] {code} {num}"
    else:
        m = CIT_BR.search(cit)
        if m:
            year, code = m.group(1), m.group(2).upper()

    # doc_date: full date where honest, else year precision
    if not doc_date:
        m = DATE_BR.search(name)
        if m:
            doc_date = f"{m.group(3)}-{MN[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
        else:
            m = DATE_FN.search(fn)
            if m and m.group(2)[:3].lower() in MN:
                doc_date = f"{m.group(3)}-{MN[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
            else:
                m = ISO_FN.search(fn)
                if m:
                    doc_date = m.group(1)
                else:
                    if not year:
                        mc = CIT_BR.search(name) or CIT_FN.search(fn)
                        if mc:
                            year = mc.group(1)
                    if not year:
                        my = YR.search(url)
                        year = my.group(1) if my else None
                    doc_date = year or ""

    # court
    if code and code in COURT_MAP:
        court = COURT_MAP[code]
    if court == "coroners":
        court = "coroners-court"
    if court in GENERIC:
        for host, slug in HOST_MAP:
            if host in url:
                court = slug
                break
    return cit, doc_date, court

def main():
    rows = []
    with open(REC) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # pass 2 aid: case pages inherit court from same-slug PDFs
    slug_court = {}
    for r in rows:
        if r.get("case_slug") and (r.get("citation") or r.get("court")):
            c = r.get("court") or ""
            if c not in GENERIC:
                slug_court.setdefault(r["case_slug"], c)

    stat = {"cit": 0, "date": 0, "court": 0, "slug": 0, "total": len(rows)}
    for r in rows:
        cit, doc_date, court = parse(r)
        if cit and not (r.get("citation") or "").strip():
            r["citation"] = cit
            stat["cit"] += 1
        if doc_date and not (r.get("doc_date") or "").strip():
            r["doc_date"] = doc_date
            stat["date"] += 1
        if court in GENERIC:
            sc = slug_court.get(r.get("case_slug") or "")
            if sc:
                r["court"] = sc
                stat["slug"] += 1
                continue
        if court and court != (r.get("court") or ""):
            r["court"] = court
            stat["court"] += 1

    bak = REC + ".bak-20261103"
    if not os.path.exists(bak):
        shutil.copy2(REC, bak)
    tmp = REC + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, REC)
    print(json.dumps(stat))

if __name__ == "__main__":
    main()
