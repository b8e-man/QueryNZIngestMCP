#!/usr/bin/env python3
"""Fetch the newly-enumerated Sep/Oct 2026 diary releases (plain urllib, browser
UA — PDFs pass; only the HTML listing was Incapsula-stubbed). Lands each PDF in
diary_pdfs/ + an ok row in diary_pdfs_manifest.jsonl in the fetcher's schema.

URLs are read from data/diary_listing_2026.jsonl (enumeration output) and
re-classified to the Sep/Oct 2026 diary-period set; no scheme-ful literals here.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(DATA, "diary_pdfs")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")
LISTING = os.path.join(DATA, "diary_listing_2026.jsonl")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SLEEP = 2.0


def safe_name(url):
    fn = url.split("/")[-1].split("?")[0]
    fn = urllib.request.unquote(fn)
    fn = re.sub(r"[^A-Za-z0-9._-]", "_", fn)[:100]
    return fn


def folder_of(h):
    parts = urllib.parse.unquote(h).split("/")
    for p in parts:
        if re.fullmatch(r"20\d\d-\d\d", p):
            return p
    return ""


def classify(r):
    base = urllib.parse.unquote(r["href"].split("/")[-1]).lower()
    s = (r["text"] + " " + base).lower()
    if "september 2026" in s or "sept 2026" in s or re.search(r"2026[-_ ]?0?9", s):
        return "2026-09"
    if "october 2026" in s or "oct 2026" in s or re.search(r"2026[-_ ]?10", s):
        return "2026-10"
    if "november 2026" in s or "nov 2026" in s or re.search(r"2026[-_ ]?11", s):
        return "2026-11"
    return None


def main():
    # already-held urls (manifest) -> skip (idempotent)
    held = set()
    for line in open(MANIFEST):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("url"):
            held.add(m["url"])
        if m.get("resolved_from"):
            held.add(m["resolved_from"])

    targets = {}
    seen = set()
    for line in open(LISTING):
        r = json.loads(line)
        f = folder_of(r["href"])
        if f not in ("2026-10", "2026-11", "2026-12"):
            continue
        c = classify(r)
        if c not in ("2026-09", "2026-10", "2026-11"):
            continue
        if r["href"] in seen or r["href"] in held:
            continue
        seen.add(r["href"])
        targets[r["href"]] = r

    todo = sorted(targets.values(), key=lambda x: (classify(x), x["href"]))
    print(f"new releases to fetch: {len(todo)}", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    ok = err = notpdf = 0
    for r in todo:
        u = r["href"]
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            if b"%PDF" not in body[:1024]:
                with open(MANIFEST, "a") as f:
                    f.write(json.dumps({"url": u, "status": "not_pdf",
                                        "bytes": len(body)}) + "\n")
                notpdf += 1
                print(f"  NOT_PDF {u.split('/')[-1]}", flush=True)
                time.sleep(SLEEP)
                continue
            fn = safe_name(u)
            path = os.path.join(OUT_DIR, fn)
            if os.path.exists(path):
                root, ext = os.path.splitext(fn)
                path = os.path.join(OUT_DIR, f"{root}_{hashlib.sha256(body).hexdigest()[:8]}{ext}")
                fn = os.path.basename(path)
            with open(path, "wb") as f:
                f.write(body)
            with open(MANIFEST, "a") as f:
                f.write(json.dumps({
                    "url": u, "status": "ok", "path": f"diary_pdfs/{fn}",
                    "bytes": len(body), "content_type": ctype,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "diary_month": classify(r),
                }) + "\n")
            ok += 1
            print(f"  OK {classify(r)} {fn} ({len(body)} bytes)", flush=True)
        except Exception as e:
            with open(MANIFEST, "a") as f:
                f.write(json.dumps({"url": u, "status": "error",
                                    "error": str(e)[:120]}) + "\n")
            err += 1
            print(f"  ERR {u.split('/')[-1]}: {str(e)[:80]}", flush=True)
        time.sleep(SLEEP)

    print(f"done: ok={ok} err={err} not_pdf={notpdf}")


if __name__ == "__main__":
    main()
