#!/usr/bin/env python3
"""Repair pass for the 45 empty parliament-wayback records (estate-parliament-
empty-2026-11-15 / estate-improvements practice 1).

Append-only repair: re-runs the fixed ingest pipeline over every URL whose
manifest says kind=doc but no documents.jsonl row ever landed an ok capture.
The fixed ingest (a) tries the canonical address when the as-shared URL only
has challenge-era captures, and (b) lands a terminal row WITH a reason
(challenged / blocked / gone) instead of a bare kind=doc. Nothing existing
is edited; outcome rows are appended to documents.jsonl / manifest.jsonl.

Usage: python3 repair_empty_records.py [--dry]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_wayback_docs import OUT, ingest  # noqa: E402

DOCS_F = os.path.join(OUT, "documents.jsonl")
MAN_F = os.path.join(OUT, "manifest.jsonl")


def empty_doc_urls():
    ok = set()
    if os.path.exists(DOCS_F):
        with open(DOCS_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("status") == "ok":
                    ok.add(r.get("url"))
    last = {}
    with open(MAN_F) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") == "doc":
                last[r.get("url")] = r
    return [u for u, r in sorted(last.items())
            if u and u not in ok and not r.get("reason")]


def main():
    urls = empty_doc_urls()
    print(f"empty-documented kind=doc urls: {len(urls)}")
    for u in urls:
        print(" ", u[:120])
    if "--dry" in sys.argv or not urls:
        return 0
    docs_before = os.path.getsize(DOCS_F) if os.path.exists(DOCS_F) else 0
    ingest(urls, final_attempt=True)
    docs_after = os.path.getsize(DOCS_F)
    print(f"documents.jsonl {docs_before} -> {docs_after} bytes")
    # summary of outcomes for these urls
    os.makedirs(os.path.dirname(DOCS_F), exist_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
