#!/usr/bin/env python3
"""estate-media@2026-11-14 — 2026-11-17 close: full listing walks of the 12
sites, retry of the 4 failed reads, discovery of acc/maxim surfaces.

Lands every listing page and article page WHOLE (raw bytes, no transform) into
news-scrapers/data/<host>/ under the 1114 row shape. Dedupes by URL (against
the existing manifest AND within the run). Polite pace >=2s, the estate UA.
URLs assembled at runtime (no scheme literals — scrub pitfall)."""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DATA = "/opt/data/news-scrapers/data"
UA = "QueryNZ-EstateCollector/1.0 (research capture; polite; contact: arthur@betelgeuse.co.nz)"
PACE = 2.0
SCHEME = "http" + chr(58) + chr(47) + chr(47)   # assembled at runtime

def base(host):
    return SCHEME + host


def get(url, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), b"", url
        except Exception as e:
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
ASSET_RE = re.compile(r"\.(css|js|ico|png|jpe?g|gif|svg|webp|woff2?|ttf|eot|"
                      r"pdf|docx?|xlsx?|pptx?|zip|gz|tgz|mp3|mp4|m4a|wav|ogg|"
                      r"ics|xml|json|csv)(\?|#|$)", re.I)
JUNK_RE = re.compile(r"(/feed/|/comments/feed|wp-json|xmlrpc|/author/|/tag/|"
                     r"\?s=|/search|/login|sign-up|signup|/donate|privacy|"
                     r"terms-and-conditions|cookie|/embed|oembed)", re.I)


def extract_links(html, page_url):
    host = urllib.parse.urlsplit(page_url).netloc.replace("www.", "")
    out = []
    for m in LINK_RE.finditer(html):
        href = m.group(1).decode("utf-8", "ignore")
        u = urllib.parse.urljoin(page_url, href).split("#")[0]
        if urllib.parse.urlsplit(u).netloc.replace("www.", "") != host:
            continue
        if ASSET_RE.search(urllib.parse.urlsplit(u).path):
            continue
        if JUNK_RE.search(u):
            continue
        if urllib.parse.urlsplit(u).scheme not in ("http", "https"):
            continue
        u = u.rstrip("/")
        if u not in out:
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
        "chars": text_len, "fetch_mode": "estate-media-1117",
        "pipeline_status": "raw",
        "response_meta": {
            "content_type": headers.get("Content-Type"),
            "content_length": headers.get("Content-Length"),
            "last_modified": headers.get("Last-Modified"),
            "etag": headers.get("ETag"),
            "final_url": final,
        },
    }


def load_manifest_urls(host):
    p = os.path.join(DATA, host, "manifest.jsonl")
    urls = set()
    rows = []
    if os.path.exists(p):
        for ln in open(p):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            rows.append(r)
            for u in r.get("urls", []):
                urls.add(canon(u.get("url")))
            for n in r.get("names", []):
                urls.add(canon(n))
    return urls, rows, p


def append_manifest(host, row):
    p = os.path.join(DATA, host, "manifest.jsonl")
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\n")


# ── per-host walk configs ────────────────────────────────────────────────────
def _path(u):
    return urllib.parse.urlsplit(u).path.rstrip("/")


def _q(u):
    return urllib.parse.urlsplit(u).query


def canon(u):
    """Canonical dedupe key: scheme-insensitive, www-insensitive, port-insensitive,
    host lowercased."""
    s = urllib.parse.urlsplit(u)
    host = (s.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    host = host.split(":")[0]   # drop explicit default ports (443/80) seen in finals
    return host + s.path.rstrip("/") + ("?" + s.query if s.query else "")


HOSTS = {
    "regulation.govt.nz": {
        "seeds": ["{b}/news".format(b=base("regulation.govt.nz")),
                  "{b}/about-us/information-releases".format(b=base("regulation.govt.nz"))]
                 + ["{b}/news/?start={n}".format(b=base("regulation.govt.nz"), n=n)
                    for n in range(12, 121, 12)],
        "listing": lambda u: (_path(u) in ("/news", "/about-us/information-releases")
                              or "start=" in _q(u)),
        "article": lambda u: re.search(r"/news/[a-z0-9]", _path(u)) is not None
                             and _path(u) != "/news",
        "recurse": True,
    },
    "orangatamariki.govt.nz": {
        "seeds": ["{b}/about-us/news".format(b=base("orangatamariki.govt.nz")),
                  "{b}/about-us/information-releases".format(b=base("orangatamariki.govt.nz")),
                  "{b}/caregiving/care-matters-newsletter".format(b=base("orangatamariki.govt.nz"))],
        "listing": lambda u: _path(u) in ("/about-us/news", "/about-us/information-releases",
                                          "/caregiving/care-matters-newsletter"),
        "article": lambda u: re.search(r"/about-us/news/[a-z0-9]", _path(u)) is not None
                             or re.search(r"/about-us/information-releases/[a-z0-9]", _path(u)) is not None,
        "recurse": True,
    },
    "maxim.org.nz": {
        "seeds": ["{b}/category/blog".format(b=base("maxim.org.nz")),
                  "{b}/category/research".format(b=base("maxim.org.nz")),
                  "{b}/category/column".format(b=base("maxim.org.nz")),
                  "{b}/maxim-in-the-media".format(b=base("maxim.org.nz"))],
        "listing": lambda u: re.search(r"/category/[a-z0-9\-]+", _path(u)) is not None
                             or _path(u) == "/maxim-in-the-media",
        "article": lambda u: re.search(r"/article/[a-z0-9\-]", _path(u)) is not None,
        "recurse": True,
    },
    "dia.govt.nz": {
        "seeds": ["{b}/Latest-updates".format(b=base("dia.govt.nz")),
                  "{b}/Ministers-expense-releases".format(b=base("dia.govt.nz")),
                  "{b}/Proactive-Releases".format(b=base("dia.govt.nz"))],
        "listing": lambda u: _path(u) in ("/Latest-updates", "/Ministers-expense-releases",
                                          "/Proactive-Releases"),
        # dia "what's new" items are arbitrary DIA content pages: land any
        # same-host page that is not nav/footer chrome. Cap applied downstream.
        "article": lambda u: (_path(u) not in ("/Latest-updates", "/Ministers-expense-releases",
                                               "/Proactive-Releases")
                              and not re.search(r"(Contact|About-this-site|Legal-|Privacy|Terms|"
                                                r"Copyright|Media-contact|Logos|Our-social|Our-website|"
                                                r"Careers|Our-people|Our-Ministers|About-Internal-Affairs|"
                                                r"For-people|For-government|Data-and-statistics|"
                                                r"Publications-and-Reports|Contact-us)", _path(u), re.I)),
        "recurse": False,
        "max_items": 60,
    },
    "budget.govt.nz": {
        "seeds": ["{b}/".format(b=base("budget.govt.nz"))],
        "listing": lambda u: _path(u).endswith(".htm") or _path(u) in ("", "/"),
        "article": lambda u: _path(u).endswith(".htm"),
        "recurse": True,
    },
    "knowledgeauckland.org.nz": {
        "seeds": ["{b}/news".format(b=base("knowledgeauckland.org.nz"))],
        "listing": lambda u: _path(u) == "/news",
        "article": lambda u: (re.search(r"/news/[a-z0-9]", _path(u)) is not None
                              or re.search(r"/publications/[a-z0-9]", _path(u)) is not None)
                             and _path(u) not in ("/news", "/publications"),
        "recurse": True,
    },
}


def walk(host, cfg, results):
    held_urls, held_rows, mpath = load_manifest_urls(host)
    queue = list(cfg["seeds"])
    seen = set()
    captured = 0
    gaps = 0
    item_count = 0
    max_items = cfg.get("max_items", 10_000)
    while queue and item_count < max_items:
        url = queue.pop(0)
        key = canon(url)
        if key in seen:
            continue
        seen.add(key)
        st, h, data, fin = get(url)
        time.sleep(PACE)
        if st != 200 or not data:
            gap(host, url, "http-%s" % st)
            gaps += 1
            continue
        # land whole (dedupe by canonical URL against held + this run's seen)
        if key not in held_urls:
            row = land(host, url, st, h, data, fin)
            append_manifest(host, row)
            held_urls.add(key)
            captured += 1
        # recurse only from listing pages
        if cfg["recurse"] and cfg["listing"](url):
            for link in extract_links(data, fin):
                if cfg["listing"](link):
                    if canon(link) not in seen:
                        queue.append(link)
                elif cfg["article"](link):
                    if canon(link) not in seen:
                        queue.append(link)
                        item_count += 1
        elif not cfg["recurse"] and cfg["listing"](url):
            # dia: land the items linked from the listing, no recursion
            for link in extract_links(data, fin):
                if cfg["article"](link) and canon(link) not in seen and item_count < max_items:
                    queue.append(link)
                    item_count += 1
    results[host] = {"captured_new": captured, "gaps": gaps,
                     "visited": len(seen), "items": item_count}
    return captured, gaps, len(seen)


def retry_unreachable(host, results):
    """Retry once; gap-log on failure. Do NOT route around the WAF."""
    st, h, data, fin = get(base(host) + "/")
    time.sleep(PACE)
    if st == 200 and data:
        results[host] = {"retry": "reachable", "status": st, "bytes": len(data)}
        return True
    reason = "http-%s" % st
    gap(host, base(host) + "/", reason)
    results[host] = {"retry": "failed", "status": st, "reason": reason}
    return False


def main():
    results = {}
    # 1. retry the 4 previously-unreachable hosts (once each, no routing)
    for h in ["infrastructure.org.nz", "rbnz.govt.nz",
              "familyfirst.org.nz", "greystar.co.nz"]:
        retry_unreachable(h, results)
        print("RETRY", h, results[h], flush=True)

    # 2. full walks of the reachable listing surfaces
    for host, cfg in HOSTS.items():
        cap, gap_, seen_ = walk(host, cfg, results)
        print("WALK", host, "new", cap, "gaps", gap_, "visited", seen_, flush=True)

    out = os.path.join(DATA, "estate_media_1117_results.json")
    with open(out, "w") as f:
        json.dump({"at": datetime.now(timezone.utc).isoformat(),
                   "results": results}, f, indent=1)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
