#!/usr/bin/env python3
"""Parliament Wayback document harvester — INGEST side (chunky single-doc runs).

For ONE url: resolve its snapshot list (self CDX, collapse=timestamp:8),
download snapshots oldest->newest, SKIP nothing during ingest (raw only),
write records to data/wayback_docs/{documents.jsonl,manifest.jsonl}.

Per record (raw capture, transformation is a LATER stage):
  url, doc_type, ts, fetched_at, snapshot_url, path, sha256, bytes,
  html_title, status ('ok' | 'failed: ...')
The raw HTML body lands at data/wayback_docs/pages/{ts}-{slug}.html verbatim
(id_ endpoint = original HTML, no Wayback rewriting).

Self-test mode (--self-test) is the SANDBOX: runs the full ingest pipeline on
a scratch URL in /tmp, prints results, cleans up. Never touches the real
output dir. Run before batching.

Usage:
  ingest_wayback_docs.py URL [URL...]      # ingest these docs' snapshots
  ingest_wayback_docs.py --self-test       # sandbox verification
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "wayback_docs")
PAGES = os.path.join(OUT, "pages")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
CDX = "https://web.archive.org/cdx/search/cdx"

SKIP_TYPES = {"calendar/ical", "alerts/maintenance", "ajax/"}


def doc_type(url):
    path = url.split("://", 1)[-1].split("/", 1)[-1].lower()
    for s in SKIP_TYPES:
        if s in path:
            return "skip"
    for key in ("hansard-debates", "bills-and-laws", "order-paper-questions",
                "daily-progress-in-the-house", "members-of-parliament",
                "mps-expenses", "electorate-profiles", "library-research-papers",
                "features", "topics", "the-week-in-parliament", "get-involved"):
        if key in path:
            return key
    return "other"


def decompress(body):
    """id_ captures preserve original Content-Encoding — analyze inside it."""
    if body[:2] == b"\x1f\x8b":
        import gzip
        try:
            return gzip.decompress(body)
        except Exception:
            return body
    return body


class BudgetExceeded(BaseException):
    """Tick budget exhausted — unwind past `except Exception` handlers."""


def snapshots(url, deadline=None):
    q = urllib.parse.urlencode({
        "url": url, "output": "json", "fl": "timestamp,statuscode",
        "collapse": "timestamp:8", "filter": "statuscode:200", "limit": "200"})
    for i in range(3):
        try:
            to = 60 if not deadline else max(10, min(60, int(deadline - time.time())))
            with urllib.request.urlopen(urllib.request.Request(CDX + "?" + q, headers=UA),
                                        timeout=to) as r:
                data = json.loads(r.read())
            return [row[0] for row in data[1:]]
        except Exception:
            if deadline and time.time() + 13 > deadline:
                raise BudgetExceeded()
            time.sleep(3)
    return None


USE_PROXY = [False]   # flips on 429/connection burn; proxy env checked once
_PROXY = [None]


def _proxy_handler():
    """IPRoyal residential fallback (creds in beehive proxy.json, never inline)."""
    if _PROXY[0] is None:
        import base64
        cfg = json.load(open("/opt/data/beehive-scraper/proxy.json"))
        import secrets
        sess = "s" + secrets.token_hex(5)
        user = base64.b64decode(cfg["username_b64"]).decode()
        pw = (base64.b64decode(cfg["password_base_b64"]).decode()
              + f"_country-nz_session-{sess}_lifetime-30m")
        _PROXY[0] = urllib.request.build_opener(urllib.request.ProxyHandler({
            "http": f"http://{user}:{pw}@geo.iproyal.com:12321",
            "https": f"http://{user}:{pw}@geo.iproyal.com:12321"}))
    return _PROXY[0]


def fetch(url, tries=3, deadline=None):
    """curl-based: urllib gets spurious 429s from web.archive.org where curl
    gets 200 (header/window discrimination, observed 2026-10-22).
    deadline: bound every call so the 120s cron kill can never fire."""
    import subprocess
    for i in range(tries):
        if deadline:
            rem = deadline - time.time()
            if rem < 10:
                raise BudgetExceeded()
            mt = str(int(max(15, min(90, rem))))
        else:
            mt = "90"
        r = subprocess.run(
            ["curl", "-sf", "--max-time", mt, "-A", UA["User-Agent"], url],
            capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        err = r.stderr.decode()[:100] if r.stderr else f"empty/rc={r.returncode}"
        if i == tries - 1:
            raise RuntimeError(err)
        if deadline and time.time() + 40 > deadline:
            raise BudgetExceeded()
        time.sleep(30)


def ingest(urls, out_dir=OUT, deadline=None):
    pages_dir = os.path.join(out_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    docs_f = os.path.join(out_dir, "documents.jsonl")
    man_f = os.path.join(out_dir, "manifest.jsonl")
    for url in urls:
        if deadline and time.time() > deadline - 8:
            return
        dtype = doc_type(url)
        if dtype == "skip":
            continue
        ts_list = snapshots(url, deadline=deadline)
        if ts_list is None:
            with open(man_f, "a") as f:
                f.write(json.dumps({"url": url, "kind": "cdx-failed",
                                    "ts": datetime.now(timezone.utc).isoformat(
                                        timespec="seconds")}) + "\n")
            continue
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", url.split("/")[-1])[:60] or "index"
        # newest first: save the LATEST snapshot that holds REAL content.
        # Wayback's own crawler gets Radware-challenged on recent captures
        # (118KB 'Radware Page' stubs) — pre-challenge-era captures are real.
        saved = challenged_any = any_failed = False
        for ts in sorted(ts_list, reverse=True):
            if deadline and time.time() > deadline - 8:
                return   # unmanifested on purpose: retried next tick
            snap = f"https://web.archive.org/web/{ts}id_/{url}"
            rec = {"url": url, "doc_type": dtype, "ts": ts,
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "snapshot_url": snap}
            try:
                body = fetch(snap, deadline=deadline)
                view = decompress(body)
                m = re.search(rb"<title[^>]*>(.*?)</title>", view[:50000], re.S | re.I)
                title = (m.group(1).decode("utf-8", "replace").strip()[:200]
                         if m else "")
                challenged = (title == "Radware Page"
                              or b"validate.perfdrive" in view[:3000]
                              or b"SWUDNSAI" in view[:3000])
                rec.update(sha256=hashlib.sha256(body).hexdigest(),
                           bytes=len(body), html_title=title,
                           content_encoding="gzip" if view is not body else "identity")
                if challenged:
                    challenged_any = True
                    rec["status"] = "challenged_snapshot"   # stub, body not saved
                elif saved:
                    rec["status"] = "skipped_older"         # real but not latest
                else:
                    fname = f"{ts}-{slug}.html"
                    with open(os.path.join(pages_dir, fname), "wb") as f:
                        f.write(body)
                    rec.update(status="ok", path=f"pages/{fname}")
                    saved = True
            except Exception as e:
                any_failed = True
                rec.update(status=f"failed: {str(e)[:100]}")
            with open(docs_f, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            time.sleep(1.2)
            if saved and rec.get("status") == "ok":
                break    # latest real capture stored; older ones not needed raw
        if deadline and time.time() > deadline - 3:
            return   # unmanifested on purpose: retried next tick
        # terminal "doc" only when we proved the outcome; all-throttle passes
        # get "attempt" so a 429 storm can never silently burn a URL
        terminal = saved or (challenged_any and not any_failed)
        with open(man_f, "a") as f:
            f.write(json.dumps({"url": url,
                                "kind": "doc" if terminal else "attempt",
                                "doc_type": dtype,
                                "snapshots": len(ts_list),
                                "ts": datetime.now(timezone.utc).isoformat(
                                    timespec="seconds")}) + "\n")


def self_test():
    """SANDBOX: full pipeline on scratch URLs in /tmp, nothing in the real out."""
    import shutil
    tmp = "/tmp/wb_sandbox"
    shutil.rmtree(tmp, ignore_errors=True)
    urls = [
        # 2020-era captures = real HTML
        ("https://www.parliament.nz/en/mps-and-electorates/"
         "members-of-parliament/goldsmith-paul/", "real"),
        # 2026 captures = Radware challenge stubs -> must be filtered
        ("https://www.parliament.nz/en/mps-and-electorates/"
         "members-of-parliament/goldsmith-paul/Trident/", "challenged"),
    ]
    print("sandbox:", [u.rsplit("/", 2)[-2] for u, _ in urls])
    ingest([u for u, _ in urls], out_dir=tmp)
    docs = os.path.join(tmp, "documents.jsonl")
    if not os.path.exists(docs):
        print("SELF-TEST FAIL: no documents.jsonl")
        return 1
    rows = [json.loads(l) for l in open(docs)]
    ok = [r for r in rows if r["status"] == "ok"]
    stubs = [r for r in rows if r["status"] == "challenged_snapshot"]
    print(f"records: {len(rows)} | ok: {len(ok)} | challenged-filtered: {len(stubs)}")
    for r in rows[:5]:
        print(f"  {r['ts']} {r['status']:20} {r.get('bytes','-')}B "
              f"title={r.get('html_title','')[:40]!r}")
    if not ok:
        print("SELF-TEST FAIL: zero real captures")
        return 1
    body = decompress(open(os.path.join(tmp, ok[0]["path"]), "rb").read())
    checks = {
        "raw_html": b"<html" in body[:2000].lower(),
        "size": len(body) > 5000,
        "real_title": ok[0].get("html_title", "") not in ("", "Radware Page"),
        "no_challenge_markers": b"validate.perfdrive" not in body[:3000],
        "challenge_filter_worked": any(
            r["status"] == "challenged_snapshot" and "Radware" in r.get("html_title", "")
            for r in rows),
    }
    print("checks:", checks)
    if not all(checks.values()):
        print("SELF-TEST FAIL: body sanity")
        return 1
    print("SELF-TEST PASS")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--self-test":
        sys.exit(self_test())
    ingest(sys.argv[1:])
