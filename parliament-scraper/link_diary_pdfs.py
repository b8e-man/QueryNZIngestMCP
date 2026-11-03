#!/usr/bin/env python3
"""Link retained diary PDFs into diaries_records.jsonl (provider Q35).

After diary_pdfs_fetch.py retains the PDFs, this adds a `path` field to
each diaries row whose source_url was fetched, so the MCP `download` tool
can serve every PDF (corpora.yaml declares path_root for the corpus).
Resumable/idempotent: rows already carrying `path` are left alone.
"""
import json, os

BASE = "/opt/data/parliament-scraper/data"
MANIFEST = os.path.join(BASE, "diary_pdfs_manifest.jsonl")
DIARIES = os.path.join(BASE, "diaries_records.jsonl")

paths = {}
for line in open(MANIFEST):
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if r.get("status") == "ok" and r.get("path"):
        paths[r["url"]] = r["path"]
print(f"manifest ok-paths: {len(paths)}")

linked = 0
tmp = DIARIES + ".tmp"
with open(DIARIES) as f, open(tmp, "w") as o:
    for line in f:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not r.get("path") and r.get("source_url") in paths:
            r["path"] = paths[r["source_url"]]
            linked += 1
        o.write(json.dumps(r, ensure_ascii=False) + "\n")
os.replace(tmp, DIARIES)
print(f"rows linked: {linked}")
