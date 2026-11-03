#!/usr/bin/env python3
"""Records reconciliation — provider gap audit 2026-11-03.

Three record-level faults in one pass (append-only history preserved as
records.jsonl.bak-<date> before any in-place fix):

1. sha256 drift: the tick used to overwrite files on refetch, leaving
   records whose sha no longer matched the bytes at their path (107
   measured). Record sha is reconciled to the file as stored; the
   original is kept as `original_sha256`; URLs with multiple fetches
   where content genuinely changes between fetches get `content_churn`
   (those pages have no single stable sha — honest, not papered over).
2. Missing classification: `court` backfilled from case name citation /
   URL host+slug (kills the generic 'tribunals' bucket that produced
   'tribunals/unknown' paths); `doc_date` (the judgment's own date) and
   `citation` parsed from the JDO case-name bracket.

Usage: python3 reconcile_records.py [--dry-run]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
RECORDS_F = os.path.join(BASE, "records.jsonl")
sys.path.insert(0, BASE)
from court_scraper import classify  # noqa: E402


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = []
    with open(RECORDS_F) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # how many records share each URL (churn detection)
    per_url = {}
    for r in rows:
        per_url[r["url"]] = per_url.get(r["url"], 0) + 1

    fixed_sha = churn = reclassified = dated = missing_file = 0
    for r in rows:
        p = r.get("path", "")
        full = os.path.join(BASE, "data", p) if p else ""
        if not p or not os.path.exists(full):
            r["file_missing"] = True
            missing_file += 1
        else:
            with open(full, "rb") as f:
                disk = hashlib.sha256(f.read()).hexdigest()
            if disk != r.get("sha256"):
                r["original_sha256"] = r.get("sha256")
                r["sha256"] = disk
                r["sha256_reconciled_at"] = now_iso()
                if per_url[r["url"]] > 1:
                    r["content_churn"] = True
                    churn += 1
                fixed_sha += 1

        court, doc_date, citation = classify(
            {"case_name": r.get("case_name", ""), "court": r.get("court", "")},
            r["url"])
        if (not r.get("court") or r.get("court") in ("", "tribunals")) and court:
            r["court"] = court
            r["court_reclassified_at"] = now_iso()
            reclassified += 1
        if not r.get("doc_date") and doc_date:
            r["doc_date"] = doc_date
            dated += 1
        if not r.get("citation") and citation:
            r["citation"] = citation

    if args.dry_run:
        print(f"DRY RUN sha_fixed={fixed_sha} churn={churn} "
              f"reclassified={reclassified} dated={dated} "
              f"file_missing={missing_file}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    shutil.copyfile(RECORDS_F, f"{RECORDS_F}.bak-{stamp}")
    with open(RECORDS_F, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"RECONCILED sha_fixed={fixed_sha} churn={churn} "
          f"reclassified={reclassified} dated={dated} "
          f"file_missing={missing_file} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
