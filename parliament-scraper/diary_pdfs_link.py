#!/usr/bin/env python3
"""Diary PDF linkage (companion to diary_pdfs_fetch.py).

The fetcher records url -> path provenance in data/diary_pdfs_manifest.jsonl
but never wrote the `path` field into diaries_records.jsonl (its docstring
promised it; the code didn't). This builds the linkage:

  manifest ok rows:  url -> "diary_pdfs/<file>"
  diaries rows:      source_url == manifest url   -> add `path`
                     source_url == bare filename  -> match manifest basename

Idempotent: re-run after manifest growth (e.g. bare-filename resolution).
"""
import collections
import json
import os
import urllib.parse

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
DIARIES = os.path.join(DATA, "diaries_records.jsonl")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")

by_url = {}
by_base = {}
by_resolved = {}
meta = {}       # path -> (sha256, fetched_at) from the capture manifest
missing_on_disk = 0
for line in open(MANIFEST):
    m = json.loads(line)
    if m.get("status") != "ok":
        continue
    p = m["path"]
    if not os.path.exists(os.path.join(DATA, p)):
        missing_on_disk += 1
        continue
    by_url[m["url"]] = p
    by_base[urllib.parse.unquote(os.path.basename(m["url"].split("?")[0]))] = p
    # every served file carries the sha256 it was captured by + fetched_at
    # (estate-improvements practice 3, 2026-11-15)
    if m.get("sha256"):
        meta[p] = (m["sha256"], m.get("fetched_at") or "")
    if m.get("resolved_from"):
        by_resolved[m["resolved_from"]] = p

stats = collections.Counter()
rows = []
for line in open(DIARIES):
    r = json.loads(line)
    u = r.get("source_url", "")
    if r.get("path") and not os.path.exists(os.path.join(DATA, r["path"])):
        del r["path"]          # stale (purged file) — re-link below
        stats["stale_cleared"] += 1
    if r.get("path"):
        stats["already"] += 1
    elif u in by_url:
        r["path"] = by_url[u]
        stats["linked_url"] += 1
    elif u in by_resolved:
        r["path"] = by_resolved[u]
        stats["linked_resolved"] += 1
    elif os.path.basename(u) in by_base:
        r["path"] = by_base[os.path.basename(u)]
        stats["linked_basename"] += 1
    else:
        stats["unlinked"] += 1
    mm = meta.get(r.get("path", ""))
    if mm:
        if not r.get("sha256"):
            r["sha256"] = mm[0]
            stats["sha_added"] += 1
        if mm[1] and not r.get("pdf_fetched_at"):
            r["pdf_fetched_at"] = mm[1]
            stats["fetched_added"] += 1
    rows.append(r)

tmp = DIARIES + ".tmp"
with open(tmp, "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
os.replace(tmp, DIARIES)

print(f"manifest ok urls: {len(by_url)} unique files: {len(set(by_url.values()))} "
      f"missing_on_disk: {missing_on_disk}")
print(f"records: {len(rows)} " + " ".join(f"{k}={v}" for k, v in sorted(stats.items())))
