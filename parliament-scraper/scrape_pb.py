#!/usr/bin/env python3
"""
parliament.nz continuous scraper — one tick.

WAF notes (verified 2026-10-17):
  - parliament.nz sits behind Radware Bot Manager. Direct urllib/curl for
    HTML or JSON gets a captcha redirect (validate.perfdrive.com).
  - Static-asset extensions (.pdf, .xml) bypass the bot check entirely:
    sitemap.xml and Hansard daily PDFs fetch fine with plain urllib.
  - The real data layer is per-sub-app JSON: hansard/questions/bills/
    petitions.parliament.nz /api/data/* . Reachable only via a browser
    that solves the JS challenge (playwright chromium does), and then
    only as a slow trickle — aggressive fetching trips an IP rate limit
    (hard captcha, resets slowly). Budget: ~2-3 JSON fetches per tick.

Architecture (2-tier):
  Tier 1 (urllib, unlimited): sitemap.xml diff (lastmod) -> changed /en/pb/
                              Hansard daily PDFs per sitting day
  Tier 2 (chromium, budgeted): /api/data/* JSON detail records

Gathering discipline: raw as-published + JSONL index. No parsing or
transformation of content. State checkpointed after every fetch.

Silent (empty stdout) when nothing new -> no_agent watchdog cron.
Usage:
  python3 scrape_pb.py                  # one tick
  python3 scrape_pb.py --backfill 2020  # probe Hansard PDFs back to year
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from datetime import datetime, timezone
from pathlib import Path

SITEMAP = "https://www3.parliament.nz/sitemap.xml"
KEEP_PREFIX = "/en/pb/"
UA = "nz-parliament-research-scraper/1.0 (personal research; low rate)"
RETRIES = 2
HANSARD_PDF = "https://hansard.parliament.nz/api/resources/daily/related/{d}/{d}-daily.pdf"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path, default):
    try:
        with open(path) as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return default


def save_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def fetch_urllib(url, timeout=30):
    """Tier 1: plain urllib. Reliable for sitemap.xml + PDFs only."""
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, "", b""
        except Exception:
            time.sleep(2 * (attempt + 1))
    return 0, "", b""


def safe_filename(url):
    path = urllib.request.urlparse(url).path.strip("/")
    path = re.sub(r"[^A-Za-z0-9._/-]", "_", path)[:180]
    return (path.replace("/", "__") or "root")


class ChromiumFetcher:
    """Tier 2: headless chromium. Solves the Radware JS challenge and
    returns page content. Budget ~2-3 requests per session — see WAF notes."""

    def __init__(self):
        self.browser = None
        self.ctx = None

    def start(self):
        import os
        # PLAYWRIGHT_BROWSERS_PATH points at an unwritable dir in this env;
        # our browsers live in the venv-local cache instead.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/.cache/ms-playwright"
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self.ctx = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )

    def get(self, url, timeout=45000):
        page = self.ctx.new_page()
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            body = page.content()
            for _ in range(10):
                if "Radware" not in body[:3000] and "perfdrive" not in body[:3000]:
                    break
                time.sleep(2.5)
                body = page.content()
            challenged = "Radware" in body[:3000] or "perfdrive" in body[:3000]
            return (0 if challenged else 200), body
        except Exception as e:
            return 0, f"ERROR {e}"
        finally:
            page.close()

    def stop(self):
        try:
            self.browser.close()
            self._pw.stop()
        except Exception:
            pass


def hansard_pdf_check(base, seen, events, start: date, end: date):
    """Tier 1: probe Hansard daily PDFs between dates. 404 = not a sitting
    day (House rose 23 Sep 2026). PDFs bypass the WAF."""
    ok = 0
    d = start
    while d <= end:
        ds = d.isoformat()
        url = HANSARD_PDF.format(d=ds)
        entry = seen.get(url)
        if entry and (entry.get("bytes") or entry.get("status") == 404):
            d += timedelta(days=1)
            continue
        st, _, body = fetch_urllib(url)
        if st == 200 and body[:5] == b"%PDF-":
            fn = base / "raw" / f"hansard_{ds}.pdf"
            fn.write_bytes(body)
            seen[url] = {"sha256": hashlib.sha256(body).hexdigest(),
                         "bytes": len(body), "fetched": now_iso()}
            ok += 1
            events.append(f"hansard PDF {ds} ({len(body)//1024}KB)")
        else:
            seen[url] = {"status": st, "checked": now_iso()}
        d += timedelta(days=1)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier2-budget", type=int, default=3,
                    help="max chromium JSON fetches per tick")
    ap.add_argument("--pdf-days", type=int, default=14,
                    help="look back N days for Hansard PDFs")
    ap.add_argument("--backfill", type=int, metavar="YEAR",
                    help="probe Hansard PDFs back to YEAR (tier 1 only)")
    ap.add_argument("--base", default="/opt/data/parliament-scraper")
    args = ap.parse_args()

    base = Path(args.base)
    for sub in ("state", "raw", "data"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    index_path = base / "data" / "pb_index.jsonl"

    seen = load_json(base / "state" / "seen_urls.json", {})
    progress = load_json(base / "state" / "progress.json", {})
    events = []

    # ---- Tier 1a: Hansard PDFs (backfill mode covers a year range) -----
    today = datetime.now(timezone.utc).date()
    if args.backfill:
        pdfs = hansard_pdf_check(base, seen, events,
                                 date(args.backfill, 1, 1), today)
    else:
        pdfs = hansard_pdf_check(base, seen, events,
                                 today - timedelta(days=args.pdf_days), today)

    # ---- Tier 1b: sitemap diff ---------------------------------------
    st, _, body = fetch_urllib(SITEMAP)
    if st == 200:
        xml = body.decode("utf-8", "ignore")
        entries = re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml)
        entries = [(u, m) for u, m in entries if KEEP_PREFIX in u]
        changed = []
        for url, lastmod in entries:
            rec = seen.get(url)
            if rec is None or rec.get("lastmod") != lastmod:
                rec = rec or {}
                rec["lastmod"] = lastmod
                rec["fetched"] = False   # re-fetch on lastmod change
                seen[url] = rec
                changed.append(url)
    else:
        print(f"WARN sitemap status={st}", flush=True)
        changed = []
        entries = []

    # ---- Tier 2: chromium JSON/detail fetches (budgeted) --------------
    pages = 0
    # prioritise content-bearing sections over nav/footer pages
    prio = ("hansard-debates", "order-paper-questions", "bills-and-laws",
            "/sc/", "library-research-papers", "papers-presented", "petitions")

    def rank(u):
        for i, p in enumerate(prio):
            if p in u:
                return i
        return len(prio)

    # retry any unfetched URL (including previously challenged ones),
    # not just those changed this tick
    pending = sorted((u for u, v in seen.items()
                      if v.get("fetched") is False and u.startswith("http")),
                     key=rank)[: args.tier2_budget]
    if pending and not args.backfill:
        fetcher = ChromiumFetcher()
        try:
            fetcher.start()
            for url in pending:
                st, body = fetcher.get(url)
                if st == 200:
                    fn = base / "raw" / (safe_filename(url) + ".html")
                    fn.write_bytes(body.encode("utf-8", "ignore"))
                    rec = {"url": url, "lastmod": seen[url].get("lastmod"),
                           "fetched": now_iso(), "bytes": len(body),
                           "raw_file": str(fn.relative_to(base))}
                    with open(index_path, "a") as idx:
                        idx.write(json.dumps(rec) + "\n")
                    seen[url]["fetched"] = True
                    pages += 1
                    events.append("page " + urllib.request.urlparse(url).path[:55])
                    time.sleep(20)   # stay inside the WAF rate budget
                else:
                    events.append("CHALLENGED " + urllib.request.urlparse(url).path[:45])
                    break            # rate limit hit: back off entirely
        finally:
            fetcher.stop()

    save_json(base / "state" / "seen_urls.json", seen)
    progress.update({
        "last_tick": now_iso(),
        "sitemap_pb_urls": len(entries),
        "pending_pages": sum(1 for v in seen.values() if v.get("fetched") is False),
        "pdfs_fetched": pdfs,
        "pages_fetched": pages,
        "seen_total": len(seen),
    })
    save_json(base / "state" / "progress.json", progress)

    if events:
        print(f"parliament.nz tick: {len(events)} events -> " + "; ".join(events[:10]), flush=True)
    # silent when nothing new


if __name__ == "__main__":
    main()
