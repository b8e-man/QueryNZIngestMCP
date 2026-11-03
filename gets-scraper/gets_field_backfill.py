#!/usr/bin/env python3
"""One-off: backfill page_fields onto GETS records captured before the
fields patch (2026-11-03). Parses each record's own stored page bytes —
no refetch, no byte change; appends an updated record row (same sha/path/
fetched_at + page_fields). Append-only history preserved.
"""
import json
import os
import sys

BASE = "/opt/data/gets-scraper"
RECORDS_F = os.path.join(BASE, "records.jsonl")
sys.path.insert(0, BASE)
from gets_capture import parse_fields  # noqa: E402

rows = [json.loads(l) for l in open(RECORDS_F) if l.strip()]
updated = skipped = 0
appended = []
for r in rows:
    if r.get("page_fields") or r.get("kind") != "tender_notice":
        continue
    full = os.path.join(BASE, "data", r.get("path", ""))
    if not r.get("path") or not os.path.exists(full):
        skipped += 1
        continue
    html = open(full, "rb").read().decode("utf-8", errors="replace")
    pf = parse_fields(html)
    if not pf:
        skipped += 1
        continue
    r = dict(r)
    r["page_fields"] = pf
    for src_k, dst_k in (("Open Date", "open_date"),
                         ("Tender Coverage", "coverage"),
                         ("Categories", "categories"),
                         ("Regions", "regions"),
                         ("Exemption Reason", "exemption_reason"),
                         ("Required Pre-qualifications", "prequalifications"),
                         ("Supplier", "award_supplier"),
                         ("Awarded To", "award_supplier"),
                         ("Award Date", "award_date")):
        if src_k in pf and not r.get(dst_k):
            r[dst_k] = pf[src_k]
    appended.append(r)
    updated += 1

# append-only: the MCP ingest enriches missing fields from later rows with
# the same id (first record keeps its capture bytes; updated_at moves)
with open(RECORDS_F, "a") as f:
    for r in appended:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"backfill: appended={updated} skipped={skipped}")
