#!/usr/bin/env python3
"""Media release lane — courtsofnz.govt.nz communications (NOT judgments).

Media releases are a different doc type: press statements and per-judgment
release twins. Discovered via three channels:

1. /home/RSS — the site announcements feed -> announcement pages -> their
   PDFs (/assets/7-Publications/Announcements/*.pdf).
2. Twin probes — every judgment has a deterministic media-release twin URL
   (2026-NZSC-122-media-release.pdf). Only recent citations (from the JDO
   ticker/backwalk case_name fields) are probed — a few HEADs per run.
3. CDX history — Announcements tree + media-release filter on the cases
   tree (ledger+retry; Wayback flaky but this is backfill only).

Capture is the shared tick (kind=media_release, pdfs/media-releases/<year>/).
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
LEDGER_F = os.path.join(BASE, "media_cdx_done.json")
LOGS = os.path.join(BASE, "logs", "media_discover.log")
SITE = "https://www.courtsofnz.govt.nz"
CDX = "https://web.archive.org/cdx/search/cdx"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
PDF_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)
CITE_RE = re.compile(r"\[(\d{4})\] (NZ[A-Za-z]{2,8}) (\d{1,4})")
TWIN = SITE + "/assets/cases/{y}/{y}-{s}-{n}-media-release.pdf"

CDX_QUERIES = (
    ("announcements", "courtsofnz.govt.nz/assets/7-Publications/Announcements/"),
    ("twins", "courtsofnz.govt.nz/assets/cases/"),
)


def load_urls(path):
    urls = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    return urls


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def enqueue(new, known):
    if not new:
        return 0
    with open(QUEUE_F, "a") as f:
        for u in new:
            f.write(json.dumps({"url": u, "source": "media_release"}) + "\n")
    known.update(new)
    return len(new)


def channel_rss(known):
    added = []
    status, body = fetch(SITE + "/home/RSS")
    if status != 200:
        print(f"rss: http_{status}", flush=True)
        return 0
    try:
        root = ET.fromstring(body)
    except Exception as e:
        print(f"rss parse: {e}", flush=True)
        return 0
    pages = [(item.findtext("link") or "").strip()
             for item in root.iter("item")]
    for page in pages[:15]:
        if not page:
            continue
        time.sleep(1.5)
        st, html = fetch(page)
        if st != 200:
            continue
        for href in PDF_RE.findall(html.decode("utf-8", "replace")):
            u = urllib.parse.urljoin(page, href)
            if u not in known:
                added.append(u)
    return enqueue(added, known)


def channel_twins(known, max_probes=25):
    """Probe deterministic twin URLs for recent JDO citations (the
    jdo ticker/backwalk stash case_name with the neutral cite)."""
    cites = set()
    for fn in (QUEUE_F, DONE_F):
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # freshness window only (jdo ticker entries); history
                # twins are opportunistic (CDX + case-page drain)
                if rec.get("source") != "jdo_api":
                    continue
                m = CITE_RE.search(rec.get("case_name", ""))
                if m:
                    cites.add((m.group(1), m.group(2), m.group(3)))
    added = probes = 0
    for y, s, n in sorted(cites, reverse=True):
        if probes >= max_probes:
            break
        url = TWIN.format(y=y, s=s, n=n)
        if url in known:
            continue
        probes += 1
        st, _ = fetch(url, timeout=20)
        if st == 200:
            added += enqueue([url], known)
        time.sleep(1.5)
    print(f"twins: {probes} probed, {added} found", flush=True)
    return added


def channel_cdx(known):
    """History backfill via Wayback index (flaky — retried next run)."""
    ledger = set()
    if os.path.exists(LEDGER_F):
        try:
            ledger = set(json.load(open(LEDGER_F)))
        except Exception:
            ledger = set()
    added = 0
    for key, prefix in CDX_QUERIES:
        if key in ledger:
            continue
        q = urllib.parse.urlencode({
            "url": prefix, "matchType": "prefix", "output": "json",
            "fl": "original", "collapse": "urlkey",
            "filter": "statuscode:200", "limit": "50000"})
        if key == "twins":
            q += "&filter=original:.*media-release.*"
        try:
            req = urllib.request.Request(CDX + "?" + q,
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = [row[0] for row in json.loads(r.read())[1:]]
        except Exception as e:
            print(f"cdx {key}: {e}", flush=True)
            continue
        new = [u for u in rows
               if u.lower().endswith(".pdf") and u not in known]
        added += enqueue(new, known)
        ledger.add(key)
        json.dump(sorted(ledger), open(LEDGER_F, "w"))
        print(f"cdx {key}: {len(rows)} rows, {len(new)} new", flush=True)
        time.sleep(2)
    return added


def main():
    known = load_urls(QUEUE_F) | load_urls(DONE_F)
    before = len(known)
    channel_rss(known)
    channel_twins(known)
    channel_cdx(known)
    added = len(known) - before
    os.makedirs(os.path.dirname(LOGS), exist_ok=True)
    with open(LOGS, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                f"added={added}\n")
    if added:
        print(f"media lane: {added} new enqueued")


if __name__ == "__main__":
    main()
