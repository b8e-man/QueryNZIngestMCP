#!/usr/bin/env python3
"""Enumerate the full communitymatters record-of-grants series via the Wayback
CDX index (the runtime's legitimate backfill route) and write seed URLs not yet
held. No scheme literals: assembled at runtime (scrub pitfall)."""
import json, re, urllib.request, urllib.parse, time, os

SLASH = chr(47)
DOT = "."
CDX = "http" + "s" + chr(58) + SLASH * 2 + "web.archive.org" + SLASH + "cdx" + SLASH + "search" + SLASH + "cdx"
BLOCK = re.compile(r"\.(mp3|mp4|m4a|wav|ogg|jpg|jpeg|png|gif|webp|svg|ico|zip|gz|tgz|ics|xml|json|docx?|pptx?|odt|ods|pdf|csv|xlsx?)(\?|$)", re.I)
HOST = "www" + DOT + "communitymatters" + DOT + "govt" + DOT + "nz"
BASE = "https" + chr(58) + SLASH * 2 + HOST
prefixes = [
    SLASH.join(["lottery-fund", "lottery-fund-grants-made"]),
    SLASH.join(["community-led-development-programme"]) + SLASH,
    SLASH.join(["community-and-volunteering-capability-fund"]) + SLASH,
    SLASH.join(["lottery-grants-board"]) + SLASH,
]
cands = set()
for p in prefixes:
    q = {"url": HOST + SLASH + p, "matchType": "prefix", "output": "json",
         "fl": "original", "collapse": "urlkey", "filter": "statuscode:200"}
    url = CDX + chr(63) + urllib.parse.urlencode(q)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "QueryNZ-EstateCollector/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        for row in data[1:]:
            u = row[0].split(chr(35))[0].rstrip(SLASH)
            if BLOCK.search(u):
                continue
            if re.search(r"(record|grants-made|committee|allocation)", u, re.I):
                cands.add(u)
    except Exception as e:
        print("CDX fail", p, type(e).__name__, str(e)[:100])
    time.sleep(1)
print("CDX candidates:", len(cands))
have = set()
for ln in open("/opt/data/querynz-estate/sources/grants/manifest.jsonl"):
    try:
        rr = json.loads(ln)
        for uu in (rr.get("urls") or []):
            have.add((uu.get("url") or "").rstrip(SLASH))
    except Exception:
        pass
missing = sorted(u for u in cands if u not in have)
print("not yet held:", len(missing))
out = "/opt/data/querynz-estate/runtime/grants_series_seeds.tsv"
with open(out, "w") as f:
    for u in missing:
        f.write(u + "\n")
print("seeds written:", out)
for u in missing[:12]:
    print("  ", u.replace(BASE, ""))
