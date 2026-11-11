"""interest.co.nz — NZ business/finance news (banking, property, markets, company
results). Very entity-dense; free. robots.txt is the generic Drupal boilerplate
(no AI/commercial restriction). Added 2026-07-16 (source-expansion §9).

Discovery: the site RSS (https://www.interest.co.nz/rss) — title, link, author
(dc:creator), and pubDate in interest's own "16th Jul 26, 3:00pm" format
(Pacific/Auckland). Content: Drupal markup with no stable body class on some
templates, so extraction prefers the known field wrappers and falls back to the
densest paragraph container.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "interest.co.nz"
FEEDS = ["https://www.interest.co.nz/rss"]

_NZ = ZoneInfo("Pacific/Auckland")
# "16th Jul 26, 3:00pm"  /  "1st Jul 26, 11:26am"
_DATE_RE = re.compile(r"(\d{1,2})\w{0,2}\s+(\w{3})\s+(\d{2}),\s+(\d{1,2}):(\d{2})\s*([ap]m)",
                      re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_date(s: str | None) -> datetime | None:
    """interest.co.nz's RSS pubDate — its own '16th Jul 26, 3:00pm' shape."""
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    day, mon, yy, hh, mm, ampm = m.groups()
    month = _MONTHS.get(mon.title())
    if not month:
        return None
    hour = int(hh) % 12 + (12 if ampm.lower() == "pm" else 0)
    try:
        return datetime(2000 + int(yy), month, int(day), hour, int(mm), tzinfo=_NZ)
    except ValueError:
        return None


async def discover(client) -> list[base.FeedItem]:
    """RSS discovery with interest's own pubDate format (base.parse_rss only
    knows RFC-2822, so it would drop every date and defeat recency filtering)."""
    # regex over the RSS (no lxml/xml tree builder in the venv; the feed is
    # simple and stable): one <item> block at a time.
    xml = (await base.fetch(client, FEEDS[0])).text
    items: list[base.FeedItem] = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):
        lm = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
        url = (lm.group(1).strip() if lm else "")
        if not url:
            continue
        tm = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        pm = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
        title = re.sub(r"<!\[CDATA\[|\]\]>", "", tm.group(1)).strip() if tm else None
        items.append(base.FeedItem(
            url=url, title=title,
            published_at=parse_date(pm.group(1).strip() if pm else None)))
    return items


def _densest_body(soup: BeautifulSoup) -> str:
    """Fallback body extraction: the container with the most direct-<p> text."""
    best_text, best_len = "", 0
    for div in soup.find_all(["div", "article", "section"]):
        ps = div.find_all("p", recursive=False)
        if len(ps) < 3:
            continue
        parts = [" ".join(p.get_text().split()) for p in ps]
        joined = "\n\n".join(p for p in parts if p)
        if len(joined) > best_len:
            best_text, best_len = joined, len(joined)
    return best_text


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.title, h1")
    if title_el is None:
        return None
    title = " ".join(title_el.get_text().split())

    body_el = soup.select_one(
        ".field-name-body, .field--name-body, .field-type-text-with-summary")
    if body_el is not None:
        paras = [" ".join(p.get_text().split()) for p in body_el.find_all("p")]
        text = "\n\n".join(p for p in paras if p)
    else:
        text = _densest_body(soup)

    if not title or len(text) < 200:
        return None
    return base.Extracted(title=title, text=text, author=None,
                          published_at=None, categories=[])
