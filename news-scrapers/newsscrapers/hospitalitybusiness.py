"""hospitalitybusiness.co.nz — Hospitality Business magazine (WordPress;
trade-press wave tier 1, 2026-07-25). Operator + venue entities. Yoast robots
allow-all. Generic RSS."""
from __future__ import annotations
import re
from . import genericrss
SOURCE = "hospitalitybusiness.co.nz"
discover = genericrss.make_discover("https://www.hospitalitybusiness.co.nz/feed/")
_SUFFIX = re.compile(r"\s*-\s*Hospitality Business( Magazine)?\s*$")


def extract(html, url):
    ex = genericrss.extract(html, url)
    if ex is not None:
        ex.title = _SUFFIX.sub("", ex.title)  # og:title carries the site name
    return ex


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 30 sub-sitemaps back to 2016.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.hospitalitybusiness.co.nz/sitemap_index.xml",
    "sitemap_re": r"/post-sitemap",
}
