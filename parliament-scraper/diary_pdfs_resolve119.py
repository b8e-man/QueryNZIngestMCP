#!/usr/bin/env python3
"""Resolve the 119 bare-filename diary releases (provider Q35 follow-up).

The extraction-era rows carry source_url = bare filename (e.g. 'April 2019.pdf')
instead of a full URL; diary_pdfs_fetch.py recorded them as 'unknown url type'
errors and never fetched them. This resolves each name to its real Beehive URL
via the Wayback CDX basename index (/tmp/beehive_pdfs_cdx.txt), fetches the PDF
byte-exact from live Beehive (browser UA), and appends ok rows to the manifest
in the fetcher's schema. Wayback id_ replay is the fallback when live 404s.

Then re-run diary_pdfs_link.py to attach `path` to the affected rows.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(DATA, "diary_pdfs")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")
CDX = "/tmp/beehive_pdfs_cdx.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def safe_name(name):
    fn = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100]
    return fn


def fetch(url, ua=True):
    h = {"User-Agent": UA} if ua else {"User-Agent": "qnz-diary-link/1.0"}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get("Content-Type", "")


# 1. the bare names (manifest error rows)
names = []
for line in open(MANIFEST):
    m = json.loads(line)
    if m.get("status") == "error" and "unknown url type" in str(m.get("error", "")):
        names.append(m["error"].split("'")[1])
names = sorted(set(names))

# idempotency: names already resolved in a previous run
done = set()
for line in open(MANIFEST):
    m = json.loads(line)
    if m.get("status") == "ok" and m.get("resolved_from"):
        done.add(m["resolved_from"])
names = [n for n in names if n not in done]

# 2. CDX basename index
idx = {}
for line in open(CDX):
    u = line.strip()
    if not u:
        continue
    b = urllib.parse.unquote(u.split("/")[-1].split("?")[0])
    idx.setdefault(b.lower(), u)
print(f"bare names: {len(names)}  cdx index: {len(idx)}")

os.makedirs(OUT_DIR, exist_ok=True)
res = {"resolved": 0, "unresolved": [], "errors": []}
for name in names:
    key = re.sub(r"_\d+$", "", os.path.splitext(name)[0]).lower()
    hit = idx.get(name.lower())
    if not hit:
        cands = [u for k2, u in idx.items()
                 if re.sub(r"_\d+$", "", os.path.splitext(k2)[0]) == key]
        hit = cands[0] if cands else None
    if not hit:
        # live probe: Beehive file tree is /files/YYYY-MM/<name>; the name
        # encodes its diary month, publication lands +/- months
        toks = re.findall(r"(January|February|March|April|May|June|July|"
                          r"August|September|October|November|December)\s+(\d{4})", name)
        if toks:
            mons = ["January", "February", "March", "April", "May", "June", "July",
                    "August", "September", "October", "November", "December"]
            mi = mons.index(toks[-1][0]) + 1
            yr = int(toks[-1][1])
            stem = os.path.splitext(name)[0]
            variants = [name, stem + "_0.pdf", name.replace(" - ", " \u2013 ")]
            for dm in (-2, -1, 0, 1, 2, 3, 4):
                y, mm = yr + (mi + dm - 1) // 12, (mi + dm - 1) % 12 + 1
                for vn in variants:
                    cu = (f"https://www.beehive.govt.nz/sites/default/files/"
                          f"{y:04d}-{mm:02d}/{urllib.parse.quote(vn)}")
                    try:
                        b, _ = fetch(cu)
                        if b"%PDF" in b[:1024]:
                            hit = cu
                            break
                    except Exception:
                        pass
                    time.sleep(0.3)
                if hit:
                    break
    if not hit:
        res["unresolved"].append(name)
        continue
    body = ctype = None
    for attempt in (hit, f"https://web.archive.org/web/2024id_/{hit}"):
        try:
            body, ctype = fetch(attempt)
            if b"%PDF" in body[:1024]:
                break
        except Exception:
            body = None
    if body is None or b"%PDF" not in body[:1024]:
        res["errors"].append(f"{name} <- {hit}")
        continue
    fn = safe_name(name)
    path = os.path.join(OUT_DIR, fn)
    if os.path.exists(path):
        root, ext = os.path.splitext(fn)
        path = os.path.join(OUT_DIR, f"{root}_{hashlib.sha256(body).hexdigest()[:8]}{ext}")
        fn = os.path.basename(path)
    with open(path, "wb") as f:
        f.write(body)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps({"url": hit, "status": "ok",
                            "path": f"diary_pdfs/{fn}",
                            "resolved_from": name,
                            "bytes": len(body), "content_type": ctype,
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    res["resolved"] += 1
    time.sleep(0.4)

print(f"resolved: {res['resolved']}  unresolved: {len(res['unresolved'])}  "
      f"fetch errors: {len(res['errors'])}")
for x in res["unresolved"][:15]:
    print("  unresolved:", x)
for x in res["errors"][:10]:
    print("  error:", x)
