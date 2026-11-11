"""nzpam.govt.nz — New Zealand Petroleum & Minerals, the Crown minerals
regulator (trade-press wave tier 2, 2026-07-25). Low volume, high authority:
permitting decisions, reservations, regulator's updates — register-adjacent
signal for the mining/energy hole. SilverStripe, no RSS: discovery scrapes
the /about/news listing; extraction takes <main>'s paragraphs (Regulator's
Update teaser pages fall under the 200-char floor and drop out — their
substance arrives via the linked detail pages when published as articles).
Date is a "Publish date: 15 July 2026" text line, no machine-readable meta.
robots blocks admin/security/pdf-generation paths only."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import base

SOURCE = "nzpam.govt.nz"
_HOME = "https://www.nzpam.govt.nz"
_DETAIL = re.compile(r"/about/news/[a-z0-9-]+")
_PUBDATE = re.compile(r"Publish date:\s*(\d{1,2} \w+ \d{4})")


async def discover(client) -> list[base.FeedItem]:
    listing = (await base.fetch(client, _HOME + "/about/news/")).text
    urls = {_HOME + m for m in _DETAIL.findall(listing)}
    return [base.FeedItem(url=u) for u in sorted(urls)]


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    main = soup.find("main")
    if h1 is None or main is None:
        return None
    title = " ".join(h1.get_text().split())
    paras = [" ".join(p.get_text().split()) for p in main.find_all("p")]
    # the publish-date line renders inside main; keep it out of the body
    paras = [p for p in paras if p and not p.startswith("Publish date:")
             and not p.startswith("Last updated:")]
    text = "\n\n".join(paras)
    if not title or len(text) < 200:
        return None
    published = None
    dm = _PUBDATE.search(main.get_text(" ", strip=True))
    if dm:
        try:
            published = datetime.strptime(dm.group(1), "%d %B %Y").replace(
                tzinfo=timezone.utc)
        except ValueError:
            pass
    return base.Extracted(title=title, text=text, author=None,
                          published_at=published, categories=[])
