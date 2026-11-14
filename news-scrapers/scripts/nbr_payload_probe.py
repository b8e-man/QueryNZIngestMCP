"""NBR: is the article body in the served HTML's JSON payload, or truly JS-rendered?"""
import asyncio
import re
import sys

import httpx

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import nbr  # noqa: E402

URL = "https://www.nbr.co.nz/primary-industries/lucidome-bio-raises-9m-for-livestock-methane-vaccine/"


async def main():
    async with httpx.AsyncClient(headers={"User-Agent": nbr._BROWSER_UA},
                                 follow_redirects=True, timeout=60) as client:
        # reuse the cached session if the module has one
        cache = __import__("pathlib").Path.home() / ".querynz" / "nbr_cookies.json"
        try:
            import json as _json
            d = _json.loads(cache.read_text())
            for k, v in d["cookies"].items():
                client.cookies.set(k, v, domain="www.nbr.co.nz")
            print("cookies loaded:", sorted(d["cookies"].keys()))
        except Exception as e:
            print("no cache:", e)
        html = (await client.get(URL)).text

    print("html len:", len(html))
    # articleBody / JSON-LD?
    for m in re.findall(r'"articleBody"\s*:\s*".{0,150}', html)[:2]:
        print("JSON-LD articleBody:", repr(m[:160]))
    for m in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.{0,300})', html, re.S)[:3]:
        print("ld+json:", repr(m[:250]))
    # any window.__STATE__ / initial props?
    for m in re.findall(r'window\.__\w+__\s*=\s*.{0,120}', html)[:5]:
        print("state:", repr(m[:140]))
    # does the story lead exist anywhere in raw html? (first distinctive words)
    for probe in ("methane", "Lucidome", "vaccine", "million"):
        idx = html.lower().find(probe.lower())
        print(f"probe[{probe}] at:", idx)
        if idx > 0:
            print("   context:", repr(html[max(0, idx-100):idx+150]))
    # main/article tags and their content lengths
    for m in re.findall(r"<(main|article)[^>]*>", html)[:5]:
        print("tag:", m)

asyncio.run(main())
