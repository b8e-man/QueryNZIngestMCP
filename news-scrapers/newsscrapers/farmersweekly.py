"""farmersweekly.co.nz — agri-business (WordPress). /rss.xml carries 50 items.
Clean robots. Generic RSS scraper."""
from __future__ import annotations
from . import genericrss
SOURCE = "farmersweekly.co.nz"
discover = genericrss.make_discover("https://www.farmersweekly.co.nz/rss.xml")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 46 sub-sitemaps; robots Crawl-delay 5.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.farmersweekly.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
    "polite": 5.0,
}
POLITE_SLEEP = 5.0   # robots Crawl-delay, binds article fetches too
