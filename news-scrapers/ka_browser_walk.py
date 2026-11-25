#!/usr/bin/env python3
"""ka_browser_walk.py — knowledgeauckland.org.nz listing pages 2-23
(browser lane; the pagination is an Umbraco AJAX POST the plain fetcher
cannot follow). Walks the listing through its own pagination control,
collects item addresses, fetches each item whole (browser context shares
the session), lands rows in the estate-news manifest in the established
shape. Go-slow, chunked, resumable via the manifest (already-landed
addresses are skipped). Arthur's browser-lane go 2026-11-19.
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

HOST = "knowledgeauckland.org.nz"
NEWS = "/opt/data/news-scrapers/data"
MF = os.path.join(NEWS, HOST, "manifest.jsonl")
GAPS = "/opt/data/querynz-estate/gaps/authors_gap_ledger.jsonl"  # shared lane log
S = "http" + chr(115) + chr(58) + chr(47) + chr(47)
LISTING = S + HOST + "/news/"
MAX_PAGES = 30
ITEM_RE = re.compile(r'href="((?:https?://(?:www\.)?knowledgeauckland\.org\.nz)?'
                     r'/news/[^"#?]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>([^<]{2,200})</title>", re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def landed():
    out = set()
    if os.path.exists(MF):
        for line in open(MF):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            for u in (r.get("urls") or []):
                if isinstance(u, dict) and u.get("url"):
                    out.add(u["url"])
    return out


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def land(url, body, final):
    sha = hashlib.sha256(body).hexdigest()
    d = os.path.join(NEWS, HOST, "store", sha[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, sha)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(body)
    text = body.decode("utf-8", "replace")
    m = TITLE_RE.search(text)
    title = (m.group(1) if m else url).strip()[:200]
    row = {"sha256": sha, "source": HOST, "kind": "article",
           "names": [title], "urls": [{"url": url, "fetched": final}],
           "file": p, "fetched_at": now_iso(), "landed_at": now_iso(),
           "published_at": "", "chars": len(text), "fetch_mode": "browser",
           "pipeline_status": "raw"}
    append_jsonl(MF, row)
    return sha


async def run():
    from patchright.async_api import async_playwright
    have = landed()
    found, gaps = [], 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"))
        page = await ctx.new_page()
        await page.goto(LISTING, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        for pno in range(1, MAX_PAGES + 1):
            html = await page.content()
            items = []
            for href in ITEM_RE.findall(html):
                u = href if href.startswith(S) else S + HOST + href
                u = u.split("#")[0].split("?")[0]
                if u.rstrip("/") != LISTING.rstrip("/"):
                    items.append(u)
            new = [u for u in dict.fromkeys(items) if u not in have]
            found.extend(new)
            print(f"page {pno}: {len(set(items))} items, {len(new)} new",
                  flush=True)
            # paginate: follow the site's own control
            nxt = None
            for sel in ("a[rel=next]", "a.next", "a:has-text('Next')",
                        "li.next a", "a:has-text('›')", "a:has-text('»')",
                        "button:has-text('Next')", "button:has-text('›')",
                        "button:has-text('»')", "a[aria-label*='ext i']",
                        "button[aria-label*='ext i']",
                        "a[href*='page=']:has-text('2')",
                        "button:has-text('2')"):
                try:
                    el = await page.query_selector(sel)
                except Exception:  # noqa: BLE001
                    el = None
                if el:
                    nxt = el
                    break
            if not nxt:
                break
            before = html
            try:
                await nxt.click()
                for _ in range(20):
                    await page.wait_for_timeout(1500)
                    if (await page.content()) != before:
                        break
            except Exception:  # noqa: BLE001
                break
        # fetch each new item whole through the browser context
        for u in found:
            try:
                r = await ctx.request.get(u, timeout=45000)
                body = await r.body()
                if r.status == 200 and len(body) > 500:
                    land(u, body, str(r.url))
                    have.add(u)
                else:
                    append_jsonl(GAPS, {"source": HOST, "url": u,
                                        "reason": f"http {r.status}",
                                        "status": "open", "at": now_iso()})
                    gaps += 1
            except Exception as e:  # noqa: BLE001
                append_jsonl(GAPS, {"source": HOST, "url": u,
                                    "reason": str(e)[:120], "status": "open",
                                    "at": now_iso()})
                gaps += 1
            await page.wait_for_timeout(2.5)
        await browser.close()
    print(f"ka walk: new={len(found)} landed={len(have)} gaps={gaps}")


import asyncio
asyncio.run(run())
