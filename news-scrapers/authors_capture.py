#!/usr/bin/env python3
"""authors_capture.py — estate author/profile page collector
(ask estate-news-authors-2026-11-15).

For every site estate-news walks: each author / contributor / columnist /
reporter profile page the site publishes (the page a byline links to) and
any staff or contributors index that lists them. Whole as fetched with all
its metadata, no extraction. Rows land in the estate-news manifests:

  kind=author_page   a profile page; reached_from = the article address
                     whose byline led to it ("" where none)
  kind=author_index  a staff/contributors listing page

Enumeration (deterministic, from bytes we already hold): author links on
recent article pages (rel=author, author-shaped hrefs, class=author) +
index-shaped links (contributors/staff/columnists/people) whose pages are
then mined one hop deeper. Refresh: an existing page is refetched at most
once every 7 days (the walk's passing). Failures gap-listed and moved on.

Mangle-safe: no scheme-ful URL literals (scheme assembled at runtime).
"""
import argparse
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
POLITE = 4.0
NEWS = "/opt/data/news-scrapers/data"
GAPS = "/opt/data/querynz-estate/gaps/authors_gap_ledger.jsonl"
STATE = "/opt/data/news-scrapers/data-authors/.state.jsonl"
REFRESH_DAYS = 7

AUTHOR_HREF = re.compile(
    r'href="([^"]*(?:/author[s]?/|/users?/|/people/|/profile/|/writer/'
    r'|/columnist[s]?/)[^"]*)"[^>]*>([^<]{2,120})<', re.I)
AUTHOR_REL = re.compile(
    r'<a[^>]*rel="(?:author|me)[^"]*"[^>]*href="([^"]+)"[^>]*>\s*'
    r'([^<]{2,120}?)\s*</a>', re.I)
INDEX_HREF = re.compile(
    r'href="([^"]*(?:/contributor[s]?/|/staff/|/our-team/|/people/'
    r'|/authors/|/columnists?/)[^"]*)"[^>]*>\s*([^<]{2,80}?)\s*</a>', re.I)
TITLE_RE = re.compile(r"<title[^>]*>([^<]{2,200})</title>", re.I)
H1_RE = re.compile(r"<h1[^>]*>([^<]{2,200})</h1>", re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_last = [0.0]


def fetch(addr, timeout=30):
    wait = POLITE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(addr, headers={"User-Agent": UA,
                                                "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            _last[0] = time.time()
            return r.status, r.geturl(), body
    except urllib.error.HTTPError as e:
        _last[0] = time.time()
        return e.code, addr, (e.read() or b"")
    except Exception as e:  # noqa: BLE001
        _last[0] = time.time()
        return 0, addr, str(e).encode()


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def gap_row(host, addr, reason, status="open"):
    append_jsonl(GAPS, {"source": host, "url": addr, "reason": reason,
                        "status": status, "at": now_iso()})


def read_state():
    st = {}
    if os.path.exists(STATE):
        for line in open(STATE):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            st[r.get("url")] = r
    return st


def norm_addr(host, href):
    """Absolute, fragment-free page address for comparison and landing."""
    if href.startswith("/"):
        href = SCHEME + host + href
    elif not href.startswith(SCHEME):
        return None
    parts = urllib.parse.urlsplit(href)
    if parts.netloc != host and not parts.netloc.endswith("." + host):
        return None
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", "", ""))  # drop query+frag


def enumerate_host(host, state, sample=25):
    """Author/index candidates from the article bytes we already hold."""
    mf = os.path.join(NEWS, host, "manifest.jsonl")
    if not os.path.exists(mf):
        return {}
    rows = []
    for line in open(mf):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "article" and r.get("file") \
                and os.path.exists(r["file"]):
            rows.append(r)
    found = {}   # addr -> (kind, name, reached_from)
    for r in rows[-sample:]:
        try:
            t = open(r["file"], "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        art = ((r.get("urls") or [{}])[0] or {}).get("url", "")
        for cre, kind in ((AUTHOR_REL, "author_page"),
                          (AUTHOR_HREF, "author_page"),
                          (INDEX_HREF, "author_index")):
            for href, name in cre.findall(t):
                addr = norm_addr(host, html_mod.unescape(href))
                if not addr or addr in found:
                    continue
                name = html_mod.unescape(re.sub(r"\s+", " ", name)).strip()
                if len(name) < 2 or name.lower() in ("rss", "login", "search"):
                    continue
                found[addr] = (kind, name[:200], art)
    return found


def land(host, kind, addr, name, reached_from, body, final_addr, status):
    sha = hashlib.sha256(body).hexdigest()
    d = os.path.join(NEWS, host, "store", sha[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, sha)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(body)
    text = body.decode("utf-8", "replace")
    m = TITLE_RE.search(text) or H1_RE.search(text)
    title = html_mod.unescape((m.group(1) if m else name)).strip()[:200]
    row = {
        "sha256": sha,
        "source": host,
        "kind": kind,
        "names": [title or name],
        "urls": [{"url": addr, "fetched": final_addr}],
        "file": p,
        "fetched_at": now_iso(),
        "landed_at": now_iso(),
        "published_at": "",
        "author": name if kind == "author_page" else "",
        "reached_from": reached_from or "",
        "chars": len(text),
        "fetch_mode": "direct",
        "http_status": status,
        "pipeline_status": "ingested",
    }
    append_jsonl(os.path.join(NEWS, host, "manifest.jsonl"), row)
    return sha


def run_host(host, budget, state):
    found = enumerate_host(host, state)
    did = errs = 0
    fresh, todo = [], []
    for a, v in found.items():
        rec = state.get(a) or {}
        if rec.get("status") == "challenge":
            continue                      # never re-hammer a challenge
        if rec.get("status") == "captured":
            try:
                cap = datetime.fromisoformat(str(rec["captured_at"]))
                if cap.tzinfo is None:
                    cap = cap.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - cap).days < REFRESH_DAYS:
                    continue              # refreshed at most weekly
            except (KeyError, ValueError):
                pass
        todo.append((a, v))
    for addr, (kind, name, reached) in todo:
        if did >= budget:
            break
        st, final, body = fetch(addr)
        if st != 200:
            chal = st in (401, 403)
            gap_row(host, addr, f"http {st}", "challenge" if chal else "open")
            append_jsonl(STATE, {"url": addr, "captured_at": now_iso(),
                                 "status": "challenge" if chal else "failed",
                                 "reason": f"http {st}"})
            errs += 1
            continue
        land(host, kind, addr, name, reached, body, final, st)
        append_jsonl(STATE, {"url": addr, "captured_at": now_iso(),
                             "status": "captured", "kind": kind})
        state[addr] = {"status": "captured", "captured_at": now_iso()}
        did += 1
        # index pages list authors: mine one hop deeper
        if kind == "author_index":
            t = body.decode("utf-8", "replace")
            for href, nm in AUTHOR_HREF.findall(t):
                a2 = norm_addr(host, html_mod.unescape(href))
                if a2 and a2 not in state and a2 not in found:
                    found[a2] = ("author_page",
                                 html_mod.unescape(nm).strip()[:200], addr)
    return {"host": host, "found": len(found), "captured": did,
            "errors": errs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--budget", type=int, default=6,
                    help="max pages fetched per host per run")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    hosts = [args.host] if args.host else None
    if hosts is None:
        hosts = []
        for d in sorted(os.listdir(NEWS)):
            if os.path.exists(os.path.join(NEWS, d, "manifest.jsonl")):
                hosts.append(d)
    state = read_state()
    tot = {"found": 0, "captured": 0, "errors": 0}
    for h in hosts:
        r = run_host(h, args.budget, state)
        tot["found"] += r["found"]
        tot["captured"] += r["captured"]
        tot["errors"] += r["errors"]
        if args.dry or r["found"]:
            print(f"  {h}: found={r['found']} captured={r['captured']} "
                  f"errors={r['errors']}")
    print(f"authors capture: found={tot['found']} captured={tot['captured']} "
          f"errors={tot['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
