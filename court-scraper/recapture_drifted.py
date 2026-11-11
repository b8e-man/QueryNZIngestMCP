#!/usr/bin/env python3
"""Recapture for the 107 drifted rows — provider note 2026-11-09.

QueryNZ refused 107 of 62,891 `courts` records: each record's
`original_sha256` (the sha of the bytes as captured) no longer matches the
bytes `download` serves. Cause: the pre-2026-11-03 tick overwrote files on
refetch, and sibling URLs of one case shared one slug file. The originals
are unrecoverable (hash-scanned the whole 20 GB store 2026-11-09: 0/106
found), so option A ("serve the bytes that match") is impossible and this
script takes their option B: re-fetch each URL and let the record carry the
NEW capture's own hash.

Per row (only rows with original_sha256 != sha256):
  - fetched through court_scraper.fetch (the lane's own UA + politeness);
  - bytes stored via court_scraper.store_bytes — immutable: differing
    content goes to a sha-suffixed sibling, no overwrite can recur;
  - row rewritten in place, records.jsonl.bak-<date> first (same pattern as
    reconcile_records.py): sha256/bytes/path/http_status/fetched_at describe
    the new capture (the promise for the served bytes), the lost capture
    keeps original_sha256 + original_fetched_at, `recaptured_at` stamps the
    repair. Record ids and seqs untouched.
  - a URL that no longer answers 200 is left exactly as it was and reported.
    Nothing is faked.

Usage: python3 recapture_drifted.py [--dry-run]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
RECORDS_F = os.path.join(BASE, "records.jsonl")
sys.path.insert(0, BASE)
import court_scraper as cs  # noqa: E402


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

    targets = [r for r in rows
               if r.get("original_sha256")
               and r.get("original_sha256") != r.get("sha256")]
    print(f"rows to recapture: {len(targets)}", flush=True)
    if args.dry_run:
        return 0

    done = failed = 0
    for i, r in enumerate(targets, 1):
        url = r["url"]
        cs.polite_sleep(url)
        try:
            status, body, ctype = cs.fetch(url)
        except Exception as exc:  # noqa: BLE001 — a failure is a report line
            print(f"[{i}/{len(targets)}] ERROR {url} {exc}", flush=True)
            failed += 1
            continue
        if status != 200 or not body:
            print(f"[{i}/{len(targets)}] HTTP {status} {url} (left as-is)",
                  flush=True)
            failed += 1
            continue
        sha = hashlib.sha256(body).hexdigest()
        rel = cs.store_bytes(r.get("path") or f"pages/recapture-{sha[:16]}.html",
                             body)
        r["original_fetched_at"] = r.get("fetched_at")
        r["original_bytes"] = r.get("bytes")
        r["sha256"] = sha
        r["bytes"] = len(body)
        r["path"] = rel
        r["http_status"] = status
        if ctype:
            r["content_type"] = ctype
        r["fetched_at"] = cs.now_iso()
        r["recaptured_at"] = r["fetched_at"]
        done += 1
        print(f"[{i}/{len(targets)}] ok {sha[:12]} {url[:90]}", flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    shutil.copyfile(RECORDS_F, f"{RECORDS_F}.bak-{stamp}")
    with open(RECORDS_F, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"DONE recaptured={done} failed={failed} "
          f"(backup records.jsonl.bak-{stamp})", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
