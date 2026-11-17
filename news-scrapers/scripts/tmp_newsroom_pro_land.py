"""Land the 8 Newsroom Pro-stub refetches as NEW rows (append-only)."""
import asyncio
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
sys.path.insert(0, "/opt/data/news-scrapers/ingestion/scripts")
from newsscrapers import newsroom
from stub_refetch import land_replacement

URLS = [
    "https://newsroom.co.nz/2026/11/11/how-to-use-mowbray-brash-campaign-as-catalyst-to-fix-mmp/",
    "https://newsroom.co.nz/2026/11/12/act-and-nz-first-set-to-take-the-wheel-as-development-law-overtakes-bishop/",
    "https://newsroom.co.nz/2026/11/12/animal-welfare-codes-extremely-vulnerable-to-court-challenge/",
    "https://newsroom.co.nz/2026/11/12/opportunity-was-the-overhangs-biggest-loser/",
    "https://newsroom.co.nz/2026/11/12/peters-keeps-his-head-while-all-about-him-lose-theirs/",
    "https://newsroom.co.nz/2026/11/12/rooftop-solar-demand-surge-risks-consumer-exposure-to-cowboy-operators/",
    "https://newsroom.co.nz/2026/11/12/there-wasnt-just-one-poll-that-mattered/",
    "https://newsroom.co.nz/2026/11/16/fishing-sector-trying-to-steer-bottom-trawling-discussion-as-coalition-talks-loom/",
]


async def main():
    out = await newsroom.fetch_authenticated(URLS)
    for url, html in out:
        ex = newsroom.extract(html, url)
        if ex is None or len(ex.text) < 200:
            print("SKIP (still thin):", url)
            continue
        row = land_replacement(
            "newsroom.co.nz", url=url, title=ex.title, text=ex.text,
            author=ex.author, published_at=ex.published_at,
            categories=ex.categories, raw=html.encode("utf-8"),
            fetch_mode="refetch-pro")
        print(f"landed {len(ex.text):6d} chars sha {row['sha256'][:12]} | "
              f"{url[-60:]}")


asyncio.run(main())
