"""guardianonline.co.nz — Ashburton Guardian, an independent mid-Canterbury
daily (Ghost CMS). Clean robots (sitemap only). Generic RSS scraper."""
from __future__ import annotations

from . import genericrss

SOURCE = "guardianonline.co.nz"
discover = genericrss.make_discover("https://guardianonline.co.nz/rss/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): posts sitemap back to ~2026-06.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://guardianonline.co.nz/sitemap.xml",
    "sitemap_re": r"/sitemap-posts",
}
