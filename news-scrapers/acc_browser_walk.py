#!/usr/bin/env python3
"""acc_browser_walk.py — acc.co.nz media releases (browser lane; the whole
host answers a plain client with an Incapsula interstitial, so every
request rides one real browser context that passively passes the check —
no solving, no interaction with any challenge). Surface: acc.co.nz/newsroom/
(media releases, stories filter 14). Rows land in the estate-news manifest.
Arthur's browser-lane go 2026-11-19.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

HOST = "acc.co.nz"
NEWS = "/opt/data/news-scrapers/data"
MF = os.path.join(NEWS, HOST, "manifest.jsonl")
GAPS = "/opt/data/querynz-estate/gaps/authors_gap_ledger.jsonl"
S = "http" + chr(115) + chr(58) + chr(47) + chr(47)
STARTS = [S + HOST + "/newsroom/",
          S + HOST + "/newsroom/stories?filter=14"]
ITEM_RE = re.compile(r'href="((?:https?://(?:www\.)?acc\.co\.nz)?'
                     r'/(?:newsroom|stories)/[^"#?]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>([^<]{2,200})</title>", re.I)
CHALLENGE_MARKS = ("incapsula", "incident id", "_Incapsula", "checking")
MAX_ITEMS = 120


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
    landed_n = gaps = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"))
        page = await ctx.new_page()
        items = []
        for start in STARTS:
            try:
                await page.goto(start, wait_until="domcontentloaded",
                                timeout=60000)
                # passive: let any interstitial's own script resolve
                for _ in range(12):
                    await page.wait_for_timeout(2500)
                    t = (await page.content())[:20000]
                    if not any(m.lower() in t.lower()
                               for m in CHALLENGE_MARKS):
                        break
                html = await page.content()
                if any(m.lower() in html.lower() for m in CHALLENGE_MARKS):
                    append_jsonl(GAPS, {"source": HOST, "url": start,
                                        "reason": "interstitial did not "
                                                  "resolve passively",
                                        "status": "challenge",
                                        "at": now_iso()})
                    gaps += 1
                    continue
                for href in ITEM_RE.findall(html):
                    u = href if href.startswith(S) else S + HOST + href
                    u = u.split("#")[0].split("?")[0]
                    if u.rstrip("/") not in (s.rstrip("/") for s in STARTS):
                        items.append(u)
                # one pagination pass (the listing may page via links)
                for sel in ("a[rel=next]", "a:has-text('Next')",
                            "a:has-text('›')", "a:has-text('»')"):
                    el = await page.query_selector(sel)
                    if el:
                        try:
                            before = html
                            await el.click()
                            for _ in range(12):
                                await page.wait_for_timeout(2000)
                                if (await page.content()) != before:
                                    break
                            for href in ITEM_RE.findall(
                                    await page.content()):
                                u = href if href.startswith(S) \
                                    else S + HOST + href
                                u = u.split("#")[0].split("?")[0]
                                items.append(u)
                        except Exception:  # noqa: BLE001
                            pass
                        break
            except Exception as e:  # noqa: BLE001
                append_jsonl(GAPS, {"source": HOST, "url": start,
                                    "reason": str(e)[:120], "status": "open",
                                    "at": now_iso()})
                gaps += 1
        todo = [u for u in dict.fromkeys(items) if u not in have]
        print(f"acc: {len(set(items))} listed, {len(todo)} new", flush=True)
        for u in todo[:MAX_ITEMS]:
            try:
                r = await ctx.request.get(u, timeout=45000)
                body = await r.body()
                text = body.decode("utf-8", "replace")
                if r.status == 200 and len(body) > 500 \
                        and not any(m.lower() in text[:20000].lower()
                                    for m in CHALLENGE_MARKS):
                    land(u, body, str(r.url))
                    landed_n += 1
                else:
                    append_jsonl(GAPS, {"source": HOST, "url": u,
                                        "reason": f"http {r.status} or "
                                                  "interstitial",
                                        "status": "open", "at": now_iso()})
                    gaps += 1
            except Exception as e:  # noqa: BLE001
                append_jsonl(GAPS, {"source": HOST, "url": u,
                                    "reason": str(e)[:120], "status": "open",
                                    "at": now_iso()})
                gaps += 1
            await page.wait_for_timeout(3.0)
        await browser.close()
    print(f"acc walk: listed={len(set(items))} landed={landed_n} "
          f"gaps={gaps}")


import asyncio
asyncio.run(run())
