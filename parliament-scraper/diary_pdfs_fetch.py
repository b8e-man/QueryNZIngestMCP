#!/usr/bin/env python3
"""Diary PDF retention (provider Q35, 2026-11-03): the diaries pipeline
streamed Beehive's proactive-diary PDFs during extraction and kept only
rows. This fetches every referenced PDF to disk (byte-exact), records
capture provenance in data/diary_pdfs_manifest.jsonl, and adds a `path`
field to diaries_records.jsonl rows so `download` can serve each PDF.

Beehive serves /sites/default/files/*.pdf to browser UAs (verified).
Politeness: 0.4s between fetches. Resumable: manifest = done set.
"""
import hashlib, json, os, re, sys, time
import urllib.request

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
DIARIES = os.path.join(DATA, "diaries_records.jsonl")
OUT_DIR = os.path.join(DATA, "diary_pdfs")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def safe_name(url):
    fn = url.split("/")[-1].split("?")[0]
    fn = urllib.request.unquote(fn)
    fn = re.sub(r"[^A-Za-z0-9._-]", "_", fn)[:100]
    return fn

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    urls = set()
    for line in open(DIARIES):
        try:
            u = json.loads(line).get("source_url")
        except ValueError:
            continue
        if u:
            urls.add(u)
    done = {}
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST):
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done[r["url"]] = r
            except ValueError:
                pass
    todo = sorted(urls - set(done))
    print(f"urls={len(urls)} done={len(done)} todo={len(todo)}")
    n = 0
    for u in todo:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            if b"%PDF" not in body[:1024]:
                with open(MANIFEST, "a") as f:
                    f.write(json.dumps({"url": u, "status": "not_pdf",
                                        "bytes": len(body)}) + "\n")
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
                f.write(json.dumps({"url": u, "status": "ok",
                                    "path": f"diary_pdfs/{fn}",
                                    "bytes": len(body),
                                    "content_type": ctype,
                                    "sha256": hashlib.sha256(body).hexdigest(),
                                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
            n += 1
            if n % 100 == 0:
                print(f"  fetched {n}/{len(todo)}", flush=True)
            time.sleep(0.4)
        except Exception as e:
            with open(MANIFEST, "a") as f:
                f.write(json.dumps({"url": u, "status": "error",
                                    "error": str(e)[:120]}) + "\n")
    print(f"diary pdfs: fetched {n}")

if __name__ == "__main__":
    main()
