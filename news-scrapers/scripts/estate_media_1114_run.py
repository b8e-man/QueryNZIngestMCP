#!/usr/bin/env python3
"""estate-media@2026-11-14: probe + first-pass capture of 12 sources into the
estate-news store (news-scrapers/data/<host>/). Hosts are read from the ask
body file; URLs are assembled at runtime (scrub pitfall). Download whole,
manifest rows match the fleet's existing row shape."""
import json, os, re, time, hashlib, urllib.request, urllib.parse
from datetime import datetime, timezone

BODY = "/opt/data/qnz-mcp/channel/bodies/5af2f6af53bedb0534ce7bf3257b43618e00d6ed0494600a67e95b5686a3b518"
DATA = "/opt/data/news-scrapers/data"
RESULTS = "/opt/data/news-scrapers/data/estate_media_1114_results.json"
UA = "QueryNZ-EstateCollector/1.0 (research capture; polite; contact: arthur@betelgeuse.co.nz)"
PACE = 2.0
MAX_ARTICLES = 15

body = json.load(open(BODY))
sources = body.get("sources", [])
print("hosts:", [s.get("source") for s in sources], flush=True)

def base_of(host):
    return "http" + chr(58) + "//" + host

def get(url, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, dict(r.headers), r.read(), r.geturl()
        except Exception as e:
            err = str(e)
            time.sleep(1)
    return None, {}, b"", url

def gap(host, url, reason):
    p = os.path.join(DATA, host, "gap-ledger.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"source": host, "url": url, "reason": reason,
                            "status": "failed-read",
                            "at": datetime.now(timezone.utc).isoformat()}) + "\n")

LINK_RE = re.compile(rb'href=["\']([^"\']+)["\']', re.I)
NEWS_PAT = re.compile(r"(news|media-release|media-releases|announcement|announcements|speech|speeches|update|updates|release|releases|newsroom|media-centre|media_center)", re.I)

def find_news_links(html, page_url):
    out, seen = [], set()
    for m in LINK_RE.finditer(html):
        href = m.group(1).decode("utf-8", "ignore")
        u = urllib.parse.urljoin(page_url, href).split("#")[0]
        if urllib.parse.urlsplit(u).netloc.replace("www.", "") != page_url.split("/")[2].replace("www.", ""):
            continue
        if not NEWS_PAT.search(urllib.parse.urlsplit(u).path):
            continue
        if re.search(r"\.(jpg|jpeg|png|gif|css|js|xml|zip)(\?|$)", u, re.I):
            continue
        u = u.rstrip("/")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def land(host, url, status, headers, data, final):
    sha = hashlib.sha256(data).hexdigest()
    d = os.path.join(DATA, host, "store", sha[:2])
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sha)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    text_len = len(re.sub(rb"<[^>]+>", b" ", data))
    return {
        "sha256": sha, "source": host,
        "kind": "article" if re.search(r"/\d{4}/|-\d{4,}$|/\d{4,}", url) else "web-page",
        "names": [url], "urls": [{"url": url}], "file": path,
        "fetched_at": now_iso, "landed_at": now_iso,
        "published_at": None, "author": None, "upstream_id": None,
        "chars": text_len, "fetch_mode": "estate-media-1114",
        "pipeline_status": "raw",
        "response_meta": {
            "content_type": headers.get("Content-Type"),
            "content_length": headers.get("Content-Length"),
            "last_modified": headers.get("Last-Modified"),
            "etag": headers.get("ETag"),
            "final_url": final,
        },
    }

results = {}
for s in sources:
    host = s.get("source")
    base = base_of(host)
    verdict = {"host": host, "note": s.get("note"), "held": s.get("held"),
               "latest_held": s.get("latest_held"), "captured": 0, "gaps": 0,
               "route": None, "robots": None}
    # robots
    st, h, data, fin = get(base + "/robots.txt")
    time.sleep(PACE)
    verdict["robots"] = st
    # sitemap
    st2, h2, data2, fin2 = get(base + "/sitemap.xml")
    time.sleep(PACE)
    verdict["sitemap"] = st2
    # homepage
    st3, h3, data3, fin3 = get(base + "/")
    time.sleep(PACE)
    verdict["homepage"] = st3
    if st3 != 200 or not data3:
        gap(host, base + "/", "http-%s" % st3)
        verdict["gaps"] += 1
        results[host] = verdict
        print("UNREACHABLE", host, st3, flush=True)
        continue
    cands = find_news_links(data3, base + "/")
    # dedupe listing-ish pages first
    listing = [u for u in cands if not re.search(r"-\d|/\d{4}/", u)][:3]
    arts = [u for u in cands if u not in listing][:MAX_ARTICLES]
    if not listing and cands:
        listing = cands[:1]
    verdict["route"] = "listing:" + (listing[0] if listing else "none")
    verdict["candidate_links"] = len(cands)
    # capture listing pages (they are the enumeration surface) + newest articles
    for u in listing + arts:
        st, h, data, fin = get(u)
        time.sleep(PACE)
        if st != 200 or not data:
            gap(host, u, "http-%s" % st)
            verdict["gaps"] += 1
            continue
        row = land(host, u, st, h, data, fin)
        mpath = os.path.join(DATA, host, "manifest.jsonl")
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        # dedupe by url
        if os.path.exists(mpath):
            if any(u in ln for ln in open(mpath)):
                continue
        with open(mpath, "a") as f:
            f.write(json.dumps(row) + "\n")
        verdict["captured"] += 1
    results[host] = verdict
    print("DONE", host, "captured", verdict["captured"], "gaps", verdict["gaps"], flush=True)

with open(RESULTS, "w") as f:
    json.dump({"at": datetime.now(timezone.utc).isoformat(), "results": results}, f, indent=1)
print(json.dumps({h: {"captured": v["captured"], "gaps": v["gaps"],
                     "route": v["route"]} for h, v in results.items()}, indent=1))
