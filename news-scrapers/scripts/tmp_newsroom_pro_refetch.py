"""Refetch the 8 Newsroom Pro-stub URLs under the signed-in session (measure)."""
import asyncio
import json
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import newsroom

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
PRO_MARKS = ("Exclusive subscriber-only emails", "Start 14-day free trial",
             "Corporate subscriptions also available")


async def main():
    out = await newsroom.fetch_authenticated(URLS)
    for url, html in out:
        ex = newsroom.extract(html, url)
        text = ex.text if ex else ""
        marks = [m for m in PRO_MARKS if m in html or m in text]
        print(f"{len(text):6d} chars | pro-markers {marks} | {url[-65:]}")


asyncio.run(main())
