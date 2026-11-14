"""Newsroom: with the minted session, fetch a fresh article — gated teaser
or extract() bug? Print body text + markers + raw structure hints."""
import asyncio
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import base, newsroom  # noqa: E402


async def main():
    # discover a few fresh article urls via the site's RSS feed
    import httpx
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        rss = (await base.fetch(client, "https://newsroom.co.nz/feed/")).text
    items = base.parse_rss(rss)
    urls = [i.url for i in items[:3]]
    print("fresh urls:", urls)

    out = await newsroom.fetch_authenticated(urls)
    for url, html in out:
        print("==", url)
        print("   html len:", len(html))
        ex = newsroom.extract(html, url)
        if ex is None:
            print("   extract -> None")
        else:
            print("   title:", repr(ex.title[:80]))
            print("   text len:", len(ex.text), "head:", repr(ex.text[:180]))
        low = html.lower()
        for marker in ("subscribe to read", "this story is for subscribers",
                       "sign in to continue", "already a subscriber", "newsroom pro",
                       "become a member", "paywall", "meter"):
            c = low.count(marker)
            if c:
                print(f"   marker[{marker}]: {c}")
        # where does visible article text start?
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            art = soup.find("article") or soup.find("main")
            if art:
                t = " ".join(art.get_text().split())
                print("   <article>/<main> text len:", len(t), "head:", repr(t[:180]))
        except Exception as e:
            print("   soup err:", e)

asyncio.run(main())
