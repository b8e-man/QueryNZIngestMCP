#!/usr/bin/env python3
"""Offline backfill of published_at/author on already-landed news captures
(estate-improvements practice 4, 2026-11-15: date/byline as the page prints
them, from article:published_time / datePublished / byline metadata).

No network. Walks every source manifest, and for rows missing published_at
or author whose raw store file is readable HTML, extracts the metadata with
newsscrapers.base.page_metadata and APPENDS a correction row (same sha256;
the MCP server merges later rows into missing fields only — the established
append-only-enrichment pattern, cf. GETS page_fields backfill 2026-11-03).

Usage: news_meta_backfill.py [--dry] [--source NAME ...]
"""
import argparse
import gzip
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from newsscrapers.base import page_metadata  # noqa: E402

ROOT = "/opt/data/news-scrapers/data"


def store_text(path):
    try:
        with open(path, "rb") as f:
            b = f.read(600000)
    except OSError:
        return None
    if b[:2] == b"\x1f\x8b":
        try:
            b = gzip.decompress(b)
        except OSError:
            return None
    if b"\x00" in b[:500]:
        return None            # binary (pdf/image) — no page metadata
    return b.decode("utf-8", "replace")


def latest_rows(manifest):
    last = {}
    with open(manifest) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("sha256"):
                last[r["sha256"]] = r
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--source", action="append", default=[])
    args = ap.parse_args()

    tot = {"rows": 0, "missing": 0, "no_file": 0, "no_meta": 0, "filled": 0,
           "pub_added": 0, "auth_added": 0}
    for mf in sorted(glob.glob(os.path.join(ROOT, "*", "manifest.jsonl"))):
        source = os.path.basename(os.path.dirname(mf))
        if args.source and source not in args.source:
            continue
        appends = []
        rows = latest_rows(mf)
        for r in rows.values():
            tot["rows"] += 1
            if r.get("published_at") and r.get("author"):
                continue
            tot["missing"] += 1
            html = store_text(r.get("file", ""))
            if not html:
                tot["no_file"] += 1
                continue
            pub, auth = page_metadata(html)
            fix = {}
            if pub and not r.get("published_at"):
                fix["published_at"] = pub.isoformat()
                tot["pub_added"] += 1
            if auth and not r.get("author"):
                fix["author"] = auth
                tot["auth_added"] += 1
            if not fix:
                tot["no_meta"] += 1
                continue
            nr = dict(r)
            nr.update(fix)
            appends.append(nr)
            tot["filled"] += 1
        if appends and not args.dry:
            with open(mf, "a") as f:
                for nr in appends:
                    f.write(json.dumps(nr, ensure_ascii=False) + "\n")
        print(f"{source}: rows={len(rows)} filled={len(appends)}")
    print("TOTAL:", " ".join(f"{k}={v}" for k, v in sorted(tot.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
