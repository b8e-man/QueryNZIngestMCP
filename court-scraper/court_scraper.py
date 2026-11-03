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


def safe_name(name, url):
    """ext4 NAME_MAX = 255 bytes; long case-name slugs broke file writes with
    Errno 36 (2026-10-30). Sanitize, then clamp to 100 chars + a URL hash so
    names stay unique and classification prefixes (mr-) survive the cut."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name) or "doc"
    if len(name.encode("utf-8", "replace")) > 100:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        name = name[:88].rstrip(". ") + "-" + h
    return name

CITE_RE = re.compile(r"\[(\d{4})\] ([A-Z]{2,6}) (\d+)(?:-\d+)?")
JDATE_RE = re.compile(r"\[(\d{1,2} \w+ \d{4})\]\s*$")
COURT_BY_CITE = {
    "NZSC": "supreme-court", "NZCA": "court-of-appeal", "NZHC": "high-court",
    "NZDC": "district-court", "NZFC": "family-court", "NZYC": "youth-court",
    "NZEnvC": "environment-court", "NZEmpC": "employment-court",
    "NZACC": "accidents-compensation-tribunal", "NZIPT": "immigration-protection-tribunal",
    "NZTT": "tenancy-tribunal", "NZDT": "disputes-tribunal",
    "NZSSC": "social-security-appeal-authority", "NZLCDT": "lawyers-conveyancers-tribunal",
    "NZREADT": "real-estate-agents-tribunal", "NZARLA": "alcohol-licensing-authority",
    "NZMVDT": "motor-vehicle-disputes-tribunal", "NZTDT": "teachers-tribunal",
    "NZHRRT": "human-rights-review-tribunal", "NZCorC": "coroners-court",
    "NZWTO": "waitangi-tribunal", "NZERA": "era", "NZHPDT": "hpdt",
}
TRIB_SLUGS = {
    "human-rights-review-tribunal": "human-rights-review-tribunal",
    "tenancy-tribunal": "tenancy-tribunal", "tenancy-tribunals": "tenancy-tribunal",
    "immigration-and-protection-tribunal": "immigration-protection-tribunal",
    "lawyers-and-conveyancers-disciplinary-tribunal": "lawyers-conveyancers-tribunal",
    "teachers-disciplinary-tribunal": "teachers-tribunal",
    "real-estate-agents-disciplinary-tribunal": "real-estate-agents-tribunal",
    "motor-vehicle-disputes-tribunal": "motor-vehicle-disputes-tribunal",
    "motor-vehicle-disputes-tribunals": "motor-vehicle-disputes-tribunal",
    "alcohol-regulatory-and-licensing-authority": "alcohol-licensing-authority",
    "disputes-tribunal": "disputes-tribunal",
    "social-security-appeal-authority": "social-security-appeal-authority",
}


def classify(rec, url):
    """(court, doc_date, citation) from queue-row metadata + case name +
    URL host/path. Court resolution chain: row tag -> citation code ->
    host map -> tribunal URL slug. doc_date is the judgment's own date
    (provider ask 2026-11-03), parsed from the JDO case-name bracket."""
    name = rec.get("case_name", "")
    court = rec.get("court", "") or ""
    doc_date = rec.get("judgment_date", "")
    citation = rec.get("citation", "")
    m = CITE_RE.search(name)
    if m:
        citation = citation or f"[{m.group(1)}] {m.group(2)} {m.group(3)}"
        court = court or COURT_BY_CITE.get(m.group(2), "")
    d = JDATE_RE.search(name)
    if d and not doc_date:
        try:
            from datetime import datetime as _dt
            doc_date = _dt.strptime(d.group(1), "%d %B %Y").date().isoformat()
        except ValueError:
            pass
    if not court:
        p = urllib.parse.urlparse(url).path
        for slug, tag in TRIB_SLUGS.items():
            if f"/{slug}" in p:
                court = tag
                break
    if not court:
        court = COURT_BY_HOST.get(urllib.parse.urlparse(url).netloc, "")
        if court == "tribunals":
            court = ""  # generic bucket is what produced 'tribunals/unknown'
    return court, doc_date, citation


def store_bytes(rel, body):
    """Byte-safe store: a refetched URL must never overwrite a different
    earlier capture at the same path (107 record/file sha mismatches,
    measured 2026-11-03). Same bytes = same path; different bytes get a
    sha-suffixed sibling so every record's sha matches its own file."""
    full = os.path.join(BASE, "data", rel)
    if os.path.exists(full):
        with open(full, "rb") as f:
            if f.read() == body:
                return rel
        stem, ext = os.path.splitext(rel)
        rel2 = f"{stem}-{hashlib.sha256(body).hexdigest()[:8]}{ext}"
        full = os.path.join(BASE, "data", rel2)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(body)
        return rel2
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(body)
    return rel


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


LAST_HEADERS = {}      # selected response headers of the last fetch (Q5)
KEEP_HEADERS = ("Content-Type", "Content-Length", "Last-Modified", "ETag",
                "Date", "Content-Encoding", "Cache-Control")


def fetch(url, timeout=30):
    """GET -> (status, body_bytes, content_type). Raises on network errors."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            LAST_HEADERS.clear()
            LAST_HEADERS.update({k: v for k, v in r.headers.items()
                                 if k.title() in KEEP_HEADERS})
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
        # merge with rows appended by the discoverers while we ran (they write
        # to QUEUE_F concurrently); rows known to this tick win on conflict
        known = {r["url"] for r in queued}
        merged = list(queued)
        try:
            with open(QUEUE_F) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("url") and r["url"] not in known:
                        known.add(r["url"])
                        merged.append(r)
        except FileNotFoundError:
            pass
        with open(QUEUE_F, "w") as f:
            for rec in merged:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def record_doc(url, kind, body, content_type, path, case_slug, court,
                   discovered_via, case_name="", doc_date="", citation=""):
        sha = hashlib.sha256(body).hexdigest()
        out = {
            "url": url, "kind": kind, "fetched_at": now_iso(),
            "http_status": 200, "sha256": sha, "path": path,
            "bytes": len(body), "content_type": content_type,
            "http_headers": dict(LAST_HEADERS),   # Q5: response headers kept
            "case_slug": case_slug, "court": court,
            "case_name": case_name,
            "discovered_via": discovered_via,
        }
        if doc_date:
            out["doc_date"] = doc_date   # the judgment's own date
        if citation:
            out["citation"] = citation
        with open(RECORDS_F, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
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
                raw_fname = urllib.parse.unquote(url.rstrip("/").split("/")[-1])
                fname = safe_name(raw_fname, url)
                court, doc_date, citation = classify(rec, url)
                year = year_of(raw_fname, url, doc_date, citation)
                # media releases are a different doc type (communications,
                # not judgments) — own lane, own storage, own record kind.
                # courtsofnz names twins both 'MR-<cite>.pdf' and
                # '<cite>-media-release.pdf' (2026-10-29).
                is_media = (source == "media_release"
                            or "-media-release" in raw_fname.lower()
                            or raw_fname.lower().startswith("mr-")
                            or "/7-publications/announcements/" in url.lower())
                if is_media:
                    kind, rel = "media_release", os.path.join(
                        "pdfs", "media-releases", year, fname)
                else:
                    kind = "judgment_pdf"
                    rel = os.path.join("pdfs", court or "misc", year, fname)
                # explicit doc-type hint from the discovering lane wins
                # (e.g. Waitangi Tribunal reports are not judgments)
                if rec.get("kind"):
                    kind = rec["kind"]
                    if kind == "report":
                        rel = os.path.join("pdfs", "reports", year, fname)
                rel = store_bytes(rel, pb)
                record_doc(url, kind, pb, pct, rel,
                           "", court, source or "cdx_index",
                           case_name=rec.get("case_name", ""),
                           doc_date=doc_date, citation=citation)
                record_done(url, "ok", sha256=hashlib.sha256(pb).hexdigest())
                added_docs += 1
            except Exception as e:
                failed += 1
                fails.append(f"{url}: {e}"[:120])
                record_done(url, f"failed: {e}"[:100])
            continue

        slug_m = SLUG_RE.search(url)
        slug = safe_name(
            slug_m.group(1) if slug_m else url.rstrip("/").split("/")[-1], url)
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
            # raw case page (byte-exact; earlier decode-write corrupted
            # non-UTF8 bytes — provider matched by sha256)
            court, doc_date, citation = classify(rec, url)
            page_path = store_bytes(os.path.join("pages", slug + ".html"), body)
            record_doc(url, rec.get("kind") or "case_page", body, ctype, page_path,
                       slug, court, rec.get("source") or "queue",
                       case_name=rec.get("case_name", ""),
                       doc_date=doc_date, citation=citation)
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
                    raw_fname = purl.rstrip("/").split("/")[-1]
                    fname = safe_name(raw_fname, purl)
                    p_court, p_date, p_cite = classify(rec, purl)
                    year_m = re.search(r"/cases/(\d{4})/", purl)
                    year = (year_m.group(1) if year_m
                            else year_of(raw_fname, purl, p_date, p_cite))
                    if ("-media-release" in raw_fname.lower()
                            or raw_fname.lower().startswith("mr-")):
                        kind = "media_release"
                        rel = os.path.join("pdfs", "media-releases", year,
                                           fname)
                    else:
                        kind = "judgment_pdf"
                        rel = os.path.join("pdfs", year, fname)
                    rel = store_bytes(rel, pb)
                    record_doc(purl, kind, pb, pct, rel,
                               slug, p_court, "case_page",
                               doc_date=p_date, citation=p_cite)
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
