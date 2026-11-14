"""NBR: with the module's own logged-in jar, fetch one fresh article —
is the BODY served (extract bug) or a teaser (account/subscription)?"""
import asyncio
import json
import re
import sys

import httpx

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import base, nbr  # noqa: E402


async def main():
    # one fresh article url from the sitemap tail (lastmod today)
    async with httpx.AsyncClient(headers={"User-Agent": nbr._BROWSER_UA},
                                 follow_redirects=True, timeout=60) as client:
        idx = (await base.fetch(client, nbr.SITEMAP_INDEX)).text
    import xml.etree.ElementTree as ET
    root = ET.fromstring(idx.encode())
    sm = nbr._SM
    children = [(loc.text or "").strip() for s in root.iter(sm + "sitemap")
                for loc in s.iter(sm + "loc") if loc.text]
    target = None
    async with httpx.AsyncClient(headers={"User-Agent": nbr._BROWSER_UA},
                                 follow_redirects=True, timeout=60) as client:
        for child in reversed(children[-5:]):
            body = (await base.fetch(client, child)).text
            for u in ET.fromstring(body.encode()).iter(sm + "url"):
                lm = (u.findtext(sm + "lastmod") or "")
                loc = (u.findtext(sm + "loc") or "").strip()
                if lm >= "2026-11-10" and len(loc.rstrip("/").split("/")) >= 5:
                    target = loc
                    break
            if target:
                break
    print("target:", target)
    if not target:
        return

    # logged-in fetch through the module's fetch_all
    out = await nbr.fetch_all([target])
    for url, html in out:
        print("fetched len:", len(html))
        # signed-in marker?
        print("account icon present:", nbr.has_account_logged_icon(html))
        ex = nbr.extract(html, url)
        if ex is None:
            print("extract() -> None")
        else:
            print("extract title:", repr(ex.title[:80]))
            print("extract text len:", len(ex.text))
            print("extract text head:", repr(ex.text[:200]))
        # what does the raw page hold? teaser markers vs body-ish paragraphs
        for marker in ("subscribe", "Subscribe", "paywall", "premium", "Log in to read",
                       "Already a subscriber"):
            if marker.lower() in html.lower():
                print(f"marker[{marker}] count:", html.lower().count(marker.lower()))
        # long paragraphs present in raw html?
        paras = re.findall(r"<p[^>]*>(.{60,}?)</p>", html, re.S)
        print("long <p> count:", len(paras))
        for p in paras[:3]:
            txt = re.sub(r"<[^>]+>", "", p)
            print("  para:", repr(" ".join(txt.split())[:120]))

asyncio.run(main())
