#!/usr/bin/env python3
"""Capture the communitymatters.govt.nz record-of-grants pages (ask:
estate-grants-lottery@2026-11-14). Download-do-not-extract: whole bytes as
fetched + full manifest rows. Seeds + known addresses are read from the ask
body file; no URL literals live in this script (scrub pitfall)."""
import json, os, re, sys, time, hashlib, urllib.request, urllib.parse
from datetime import datetime, timezone

BODY = "/opt/data/qnz-mcp/channel/bodies/9b1baf45f6b1c3e0e6fdef123d778455a0ce4d00244af83ee6a8402ce097cdc6"
MANIFEST = "/opt/data/querynz-estate/sources/grants/manifest.jsonl"
STORE = "/opt/data/querynz-estate/store"
GAPS = "/opt/data/querynz-estate/sources/grants/gap-ledger.jsonl"
UA = "QueryNZ-EstateCollector/1.0 (research capture; polite; contact: arthur@betelgeuse.co.nz)"
PACE = 2.0
MAX_PAGES = 700

body = json.load(open(BODY))
seeds = []
for sec in body.get("sections", []):
    what = sec.get("what") or ""
    m = re.search(r"\S+communitymatters\S*", what)
    if m:
        seeds.append(m.group(0).rstrip("/"))
    for a in sec.get("known_addresses", []) or []:
        seeds.append(a.rstrip("/"))
start = seeds[0]
base = urllib.parse.urlsplit(start)
origin = base.scheme + "://" + base.netloc
seeds = list(dict.fromkeys(seeds))

def get(url, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read(), r.geturl()
        except Exception as e:
            last = e
            time.sleep(2)
    return None, {}, b"", url

# existing URL set (dedupe)
have = set()
rows_all = []
if os.path.exists(MANIFEST):
    for ln in open(MANIFEST):
        try:
            r = json.loads(ln)
            rows_all.append(r)
            for u in (r.get("urls") or []):
                have.add((u.get("url") or "").rstrip("/"))
        except Exception:
            pass
print("existing manifest rows:", len(rows_all), "unique urls:", len(have), flush=True)

def gap(url, reason):
    with open(GAPS, "a") as f:
        f.write(json.dumps({"source": "communitymatters.govt.nz", "url": url,
                            "reason": reason, "status": "failed-read", "at":
                            datetime.now(timezone.utc).isoformat()}) + "\n")

def kind_of(ctype, url):
    if "pdf" in ctype: return "pdf"
    if "html" in ctype: return "web-page"
    if "csv" in ctype: return "csv"
    if "sheet" in ctype or url.endswith(".xlsx"): return "xlsx"
    return "other"

def land(url, status, headers, data, final_url):
    sha = hashlib.sha256(data).hexdigest()
    d = os.path.join(STORE, sha[:2])
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sha)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    now = datetime.now(timezone.utc)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00"
    now_iso = now.isoformat()
    ctype = headers.get("Content-Type", "").split(";")[0].strip() or "application/octet-stream"
    row = {
        "sha256": sha, "size": len(data), "kind": kind_of(ctype, final_url),
        "content_type": ctype, "file": path,
        "urls": [{"url": url, "via": ["grants-lottery-record-capture"]}],
        "archive_replay_urls": [], "names": [url], "landings": 1,
        "first_landed": now_s, "last_landed": now_s,
        "fetched_at": now_iso, "landed_at": now_s,
        "withdrawn": False, "withdrawn_reason": None, "problem": None,
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "http_status": status,
        "response_meta": {
            "content_type": headers.get("Content-Type"),
            "content_length": headers.get("Content-Length"),
            "last_modified": headers.get("Last-Modified"),
            "etag": headers.get("ETag"),
            "final_url": final_url,
        },
        "listing_page": None,
    }
    return row

LINK_RE = re.compile(rb'href=["\']([^"\']+)["\']', re.I)
def links(html, page_url):
    out = []
    for m in LINK_RE.finditer(html):
        href = m.group(1).decode("utf-8", "ignore")
        u = urllib.parse.urljoin(page_url, href).split("#")[0]
        if "communitymatters.govt.nz" not in u:
            continue
        lu = u.lower()
        if "record-of-grants" in lu or "grants-made" in lu or "record-of-grant" in lu:
            out.append(u.rstrip("/"))
    return out

DOC_RE = re.compile(r"\.(pdf|csv|xlsx)(\?|$)", re.I)
def doc_links(html, page_url):
    out = []
    for m in LINK_RE.finditer(html):
        href = m.group(1).decode("utf-8", "ignore")
        u = urllib.parse.urljoin(page_url, href).split("#")[0]
        if "communitymatters.govt.nz" in u and DOC_RE.search(u):
            out.append(u)
    return out

queue = list(seeds)
seen = set(seeds)
landed = 0
skipped = 0
docs_queued = []
while queue and landed < MAX_PAGES:
    url = queue.pop(0)
    if url in have:
        skipped += 1
        continue
    status, hdrs, data, final = get(url)
    time.sleep(PACE)
    if status != 200 or not data:
        gap(url, "http-%s" % status)
        print("GAP", status, url, flush=True)
        continue
    ctype = hdrs.get("Content-Type", "")
    if "html" in ctype:
        for u in links(data, url):
            if u not in seen:
                seen.add(u)
                queue.append(u)
        for u in doc_links(data, url):
            if u not in seen:
                seen.add(u)
                docs_queued.append(u)
    row = land(url, status, hdrs, data, final)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(row) + "\n")
    have.add(url.rstrip("/"))
    landed += 1
    if landed % 25 == 0:
        print("landed", landed, "queue", len(queue), "docs", len(docs_queued), flush=True)

for url in docs_queued[:300]:
    if url in have:
        continue
    status, hdrs, data, final = get(url)
    time.sleep(PACE)
    if status != 200 or not data:
        gap(url, "http-%s" % status)
        continue
    row = land(url, status, hdrs, data, final)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(row) + "\n")
    have.add(url.rstrip("/"))
    landed += 1

print(json.dumps({"landed_now": landed, "skipped_held": skipped,
                  "queue_left": len(queue), "docs_left": max(0, len(docs_queued) - 300)}))
