"""fridayoffcuts.com — Friday Offcuts, the weekly Australasian forestry trade
digest (Innovatek; trade-press wave tier 1, 2026-07-25). Mills, log markets,
company moves — feeds the agent-built Forestry watchlist. NB woodweek.com now
301s straight here, so the todo's two forestry weeklies are ONE scraper.

Legacy ColdFusion pages. Discovery: the homepage is the current issue and
links every story as dsp_article.cfm?id={issue}&date={YYYY-MM-DD}&aid={story}
(the date param is the issue date — used as published_at since article pages
render only a display date). Extraction: table-era markup — title in the lone
<h2>, body is <br>-separated loose HTML between the gray date <b> and the
"Return to Newsletter" link, so paragraph-density heuristics don't work and
the body is cut by string landmarks instead of a CSS selector. Headlines are
tagged [NZ]/[Aus]/[Int]…; the tag rides through in the title and non-NZ
dilution is left to the extractor's NZ-entity focus (the digest is majority
NZ; per-tag filtering would drop trans-Tasman stories that name NZ firms).
robots blocks only /admin /private /cgi-bin /logs /pix.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import base

SOURCE = "fridayoffcuts.com"
_HOME = "https://fridayoffcuts.com"
_ART = re.compile(
    r"dsp_article\.cfm\?id=(\d+)&(?:amp;)?date=(\d{4}-\d{2}-\d{2})&(?:amp;)?aid=(\d+)")


async def discover(client) -> list[base.FeedItem]:
    home = (await base.fetch(client, _HOME + "/")).text
    items: dict[str, base.FeedItem] = {}
    for issue, date, aid in _ART.findall(home):
        url = f"{_HOME}/dsp_article.cfm?id={issue}&date={date}&aid={aid}"
        if url in items:
            continue
        try:
            pub = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pub = None
        items[url] = base.FeedItem(url=url, published_at=pub)
    return sorted(items.values(), key=lambda i: i.url)


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2")
    if h2 is None:
        return None
    title = " ".join(h2.get_text().split())
    # body = everything in the story <td> after the h2, minus the boilerplate
    # tail (Return to Newsletter / AddThis / Disqus live in later siblings or
    # recognisable text). Take text node-wise so <br> runs become breaks.
    td = h2.find_parent("td")
    if td is None:
        return None
    for bad in td.select("script, style, #disqus_thread, .addthis_default_style"):
        bad.decompose()
    raw = td.get_text("\n")
    lines = [" ".join(l.split()) for l in raw.split("\n")]
    body: list[str] = []
    started = False
    for l in lines:
        if not l:
            continue
        if not started:
            # skip up to and including the display-date line under the title
            if l == title or re.fullmatch(
                    r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day \d{1,2} \w+ \d{4}", l):
                started = l != title or started
                continue
            started = True
        if l.startswith(("Return to Newsletter", "Share |", "Comment on story",
                         "Copyright 20")):
            break
        body.append(l)
    text = "\n\n".join(body)
    if not title or len(text) < 200:
        return None
    return base.Extracted(title=title, text=text, author=None,
                          published_at=None, categories=[])
