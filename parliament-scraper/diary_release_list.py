#!/usr/bin/env python3
"""Diary release list (provider Q36, 2026-11-03).

Every diary release held — one row per release PDF (source_url) with the
ministers and months its meetings cover, plus retention status from
diary_pdfs_manifest.jsonl. Output: data/diary_release_list.csv

Note on the provider's "119 releases have no PDF address": every meetings
row in our records carries a source_url (0 without), and Beehive's own
sitemap does not index the diary releases. The gap they measured is on
Beehive's ministerial-diaries landing page body (WAF'd from the VPS;
bodies come via the home-IP lane) — closing it needs that page's links
diffed against this list.
"""
import csv, json, re
from collections import defaultdict

BASE = "/opt/data/parliament-scraper/data"
DIARIES = f"{BASE}/diaries_records.jsonl"
MANIFEST = f"{BASE}/diary_pdfs_manifest.jsonl"
OUT = f"{BASE}/diary_release_list.csv"

rel = defaultdict(lambda: {"ministers": set(), "months": set(), "rows": 0,
                           "meeting": ""})
for line in open(DIARIES):
    try:
        r = json.loads(line)
    except ValueError:
        continue
    u = r.get("source_url") or ""
    e = rel[u]
    e["ministers"].add(str(r.get("minister") or "")[:40])
    d = str(r.get("date") or "")[:7]
    if d:
        e["months"].add(d)
    e["rows"] += 1
    if not e["meeting"]:
        e["meeting"] = str(r.get("meeting") or "")[:80]

status = {}
try:
    for line in open(MANIFEST):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("url"):
            status[r["url"]] = r.get("status", "")
except FileNotFoundError:
    pass

rows = []
for u, e in rel.items():
    rows.append({
        "pdf_url": u,
        "file": u.split("/")[-1][:120],
        "ministers": "; ".join(sorted(m for m in e["ministers"] if m)),
        "months": "; ".join(sorted(e["months"])),
        "meeting_rows": e["rows"],
        "retained": status.get(u, "not-fetched"),
    })
rows.sort(key=lambda r: r["months"])
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["pdf_url", "file", "ministers", "months",
                                      "meeting_rows", "retained"])
    w.writeheader()
    w.writerows(rows)
ok = sum(1 for r in rows if r["retained"] == "ok")
print(f"releases: {len(rows)} | retained ok: {ok} | other: {len(rows)-ok} -> {OUT}")
