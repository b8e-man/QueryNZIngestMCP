"""Newsroom: score the whole feed set — which urls are the permanently-thin trio?"""
import asyncio
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import base, newsroom  # noqa: E402


async def main():
    import httpx
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        rss = (await base.fetch(client, "https://newsroom.co.nz/feed/")).text
    items = base.parse_rss(rss)
    urls = [i.url for i in items[:15]]
    print("feed urls:", len(urls))

    out = await newsroom.fetch_authenticated(urls)
    for url, html in out:
        ex = newsroom.extract(html, url)
        ln = 0 if ex is None else len(ex.text)
        flag = "THIN" if ln < 200 else "ok"
        print(f"  {flag:4s} {ln:6d}  {url}")
        if ln < 200:
            print("        html len:", len(html))
            if ex is not None:
                print("        text:", repr(ex.text[:150]))
            low = html.lower()
            for marker in ("audio", "video", "live", "gallery", "not found", "404"):
                if marker in low[:5000]:
                    print("        marker:", marker)

asyncio.run(main())
