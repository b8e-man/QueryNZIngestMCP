#!/usr/bin/env python3
"""NZ court judgments capture tick (courtsofnz.govt.nz).

Per tick:
1. Refresh the three per-court RSS feeds (SC/CA/HC) -> enqueue new case URLs.
2. Drain the queue: fetch each case page raw, extract judgment PDF links,
   fetch each PDF raw. All bytes stored exact; every capture recorded with
   provenance in records.jsonl.

Raw-first: no text extraction at gather time. Terminal outcomes (ok,
http_404, http_410) are final; transient failures retry with 3 strikes.

Exit semantics (cron no_agent): silent + exit 0 on success/nothing to do;
stderr + exit 1 only when the tick achieved nothing AND had failures.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
RECORDS_F = os.path.join(BASE, "records.jsonl")
PAGES = os.path.join(BASE, "data", "pages")
PDFS = os.path.join(BASE, "data", "pdfs")
LOGS = os.path.join(BASE, "logs", "tick.log")

SITE = "https://www.courtsofnz.govt.nz"
# PARKED 2026-10-29: RSS freshness superseded by the JDO JSON ticker
# (jdo_new.py — upstream of courtsofnz's selection, ALL courts). The tick
# survives as the shared queue drain for every lane (courtsofnz backfill,
# tribunals, JDO PDFs). Restore the feeds dict to re-enable RSS discovery.
FEEDS = {}
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
PDF_RE = re.compile(r'href="([^"]+\.pdf[^"]*)"')
SLUG_RE = re.compile(r"/cases/([^/?#]+)")

TERMINAL = ("ok", "http_404", "http_410")
SLEEP = 1.0        # politeness between requests (govt site, ~1 req/s max)
# justice.govt.nz /robots.txt disallows /assets/ — user directed direct fetch
# anyway ("proceed politely anyway"): extra-gentle cadence for that host.
POLITE_SLEEP = {"www.justice.govt.nz": 2.5, "justice.govt.nz": 2.5}
COURT_BY_HOST = {
    "www.justice.govt.nz": "tribunals",
    "justice.govt.nz": "tribunals",
    "www.employmentcourt.govt.nz": "employment-court",
    "employmentcourt.govt.nz": "employment-court",
    "www.environmentcourt.govt.nz": "environment-court",
    "environmentcourt.govt.nz": "environment-court",
    "coronerscourt.govt.nz": "coroners-court",
}
YEAR_RE = re.compile(r"(19|20)\d{2}")


def polite_sleep(url):
    host = urllib.parse.urlparse(url).netloc
    time.sleep(POLITE_SLEEP.get(host, SLEEP))


def year_of(*parts):
    for p in parts:
        m = YEAR_RE.search(p)
        if m:
            return m.group(0)
    return "unknown"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=30):
    """GET -> (status, body_bytes, content_type). Raises on network errors."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=80)
    ap.add_argument("--limit", type=int, default=40,
                    help="max case pages per tick")
    args = ap.parse_args()
    t0 = time.time()
    deadline = t0 + args.time_budget

    # ---- state -------------------------------------------------------
    done = {}          # url -> attempts count; terminal URLs are in TERMINAL
    if os.path.exists(DONE_F):
        with open(DONE_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done[r["url"]] = r
                except Exception:
                    pass
    queued = []          # full queue records (url, source, case_name, ...)
    queued_set = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    u = rec["url"]
                    if u not in queued_set:
                        queued.append(rec)
                        queued_set.add(u)
                except Exception:
                    pass

    def terminal(url):
        r = done.get(url)
        return bool(r) and (r.get("status") in TERMINAL
                            or r.get("attempts", 0) >= 3)

    def record_done(url, status, **extra):
        r = done.get(url, {"url": url, "attempts": 0})
        r["attempts"] = r.get("attempts", 0) + 1
        r.update(status=status, last_try=now_iso(), **extra)
        done[url] = r
        with open(DONE_F, "a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def flush_queue():
        with open(QUEUE_F, "w") as f:
            for rec in queued:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def record_doc(url, kind, body, content_type, path, case_slug, court,
                   discovered_via, case_name=""):
        sha = hashlib.sha256(body).hexdigest()
        with open(RECORDS_F, "a") as f:
            f.write(json.dumps({
                "url": url, "kind": kind, "fetched_at": now_iso(),
                "http_status": 200, "sha256": sha, "path": path,
                "bytes": len(body), "content_type": content_type,
                "case_slug": case_slug, "court": court,
                "case_name": case_name,
                "discovered_via": discovered_via,
            }, ensure_ascii=False) + "\n")
        return sha

    def enqueue(u):
        if u not in queued_set and not terminal(u):
            queued.append({"url": u})
            queued_set.add(u)

    ok = failed = added_docs = 0
    fails = []

    # ---- phase 1: RSS freshness -------------------------------------
    for court, feed_url in FEEDS.items():
        try:
            status, body, _ = fetch(feed_url)
            if status != 200:
                fails.append(f"rss {court}: http_{status}")
                continue
            root = ET.fromstring(body)
            for item in root.iter("item"):
                link = (item.findtext("link") or "").strip()
                if "/cases/" in link:
                    enqueue(link)
        except Exception as e:
            fails.append(f"rss {court}: {e}"[:120])

    # ---- phase 2: queue drain (case pages -> PDFs) -------------------
    os.makedirs(PAGES, exist_ok=True)
    batch = [r for r in queued if not terminal(r["url"])][:args.limit]
    for rec in batch:
        url = rec["url"]
        source = rec.get("source", "")
        if time.time() > deadline:
            break
        polite_sleep(url)

        # ---- direct PDF queue entries (tribunal/court CDX seeds) ----
        if urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
            try:
                st, pb, pct = fetch(url, timeout=60)
                if st in (404, 410):
                    record_done(url, f"http_{st}")
                    continue
                if st != 200:
                    failed += 1
                    fails.append(f"{url}: http_{st}")
                    record_done(url, f"http_{st}")
                    continue
                fname = urllib.parse.unquote(url.rstrip("/").split("/")[-1])
                court = COURT_BY_HOST.get(urllib.parse.urlparse(url).netloc, "")
                year = year_of(fname, url)
                # media releases are a different doc type (communications,
                # not judgments) — own lane, own storage, own record kind.
                # courtsofnz names twins both 'MR-<cite>.pdf' and
                # '<cite>-media-release.pdf' (2026-10-29).
                is_media = (source == "media_release"
                            or "-media-release" in fname.lower()
                            or fname.lower().startswith("mr-")
                            or "/7-publications/announcements/" in url.lower())
                if is_media:
                    kind, rel = "media_release", os.path.join(
                        "pdfs", "media-releases", year, fname)
                else:
                    kind = "judgment_pdf"
                    rel = os.path.join("pdfs", court or "misc", year, fname)
                os.makedirs(os.path.dirname(os.path.join(BASE, "data", rel)),
                            exist_ok=True)
                with open(os.path.join(BASE, "data", rel), "wb") as f:
                    f.write(pb)
                record_doc(url, kind, pb, pct, rel,
                           "", court, source or "cdx_index",
                           case_name=rec.get("case_name", ""))
                record_done(url, "ok", sha256=hashlib.sha256(pb).hexdigest())
                added_docs += 1
            except Exception as e:
                failed += 1
                fails.append(f"{url}: {e}"[:120])
                record_done(url, f"failed: {e}"[:100])
            continue

        slug_m = SLUG_RE.search(url)
        slug = slug_m.group(1) if slug_m else url.rstrip("/").split("/")[-1]
        try:
            status, body, ctype = fetch(url)
            if status in (404, 410):
                record_done(url, f"http_{status}")
                continue
            if status != 200:
                failed += 1
                fails.append(f"{url}: http_{status}")
                record_done(url, f"http_{status}")
                continue
            # raw case page
            page_path = os.path.join("pages", slug + ".html")
            with open(os.path.join(BASE, "data", page_path), "w",
                      encoding="utf-8") as f:
                f.write(body.decode("utf-8", errors="replace"))
            record_doc(url, "case_page", body, ctype, page_path,
                       slug, "", "rss/queue")
            ok += 1

            # PDFs on the case page
            html = body.decode("utf-8", errors="replace")
            seen_pdfs = set()
            for href in PDF_RE.findall(html):
                if time.time() > deadline:
                    break
                purl = urllib.parse.urljoin(SITE, href)
                if purl in seen_pdfs or terminal(purl):
                    continue
                seen_pdfs.add(purl)
                polite_sleep(purl)
                try:
                    st, pb, pct = fetch(purl, timeout=60)
                    if st != 200:
                        record_done(purl, f"http_{st}")
                        continue
                    fname = purl.rstrip("/").split("/")[-1]
                    year_m = re.search(r"/cases/(\d{4})/", purl)
                    year = year_m.group(1) if year_m else "unknown"
                    if ("-media-release" in fname.lower()
                            or fname.lower().startswith("mr-")):
                        kind = "media_release"
                        rel = os.path.join("pdfs", "media-releases", year,
                                           fname)
                    else:
                        kind = "judgment_pdf"
                        rel = os.path.join("pdfs", year, fname)
                    os.makedirs(os.path.dirname(os.path.join(BASE, "data", rel)),
                                exist_ok=True)
                    with open(os.path.join(BASE, "data", rel), "wb") as f:
                        f.write(pb)
                    record_doc(purl, kind, pb, pct, rel,
                               slug, "", "case_page")
                    record_done(purl, "ok", sha256=hashlib.sha256(pb).hexdigest())
                    added_docs += 1
                except Exception as e:
                    fails.append(f"{purl}: {e}"[:120])
                    record_done(purl, f"failed: {e}"[:100])
            record_done(url, "ok")
        except Exception as e:
            failed += 1
            fails.append(f"{url}: {e}"[:120])
            record_done(url, f"failed: {e}"[:100])

    flush_queue()

    os.makedirs(os.path.dirname(LOGS), exist_ok=True)
    with open(LOGS, "a") as f:
        f.write(f"{now_iso()} pages_ok={ok} pages_failed={failed} "
                f"pdfs_added={added_docs} queue={len(queued)} "
                f"secs={time.time()-t0:.0f}\n")

    if not ok and not added_docs and fails:
        print(f"court scraper: 0 captured, {len(fails)} failures. "
              f"Errors: {'; '.join(fails[:5])}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
