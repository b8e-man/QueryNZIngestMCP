"""baybuzz.co.nz — BayBuzz: Hawke's Bay investigative magazine — council,
water, land-use politics. WordPress, standard robots. Generic RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "baybuzz.co.nz"
discover = genericrss.make_discover("https://baybuzz.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 9 sub-sitemaps; robots Crawl-delay 30.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://baybuzz.co.nz/sitemap.xml",
    "sitemap_re": r"/wp-sitemap-posts-post-",
    "polite": 30.0,
}
POLITE_SLEEP = 30.0   # robots Crawl-delay, binds article fetches too
