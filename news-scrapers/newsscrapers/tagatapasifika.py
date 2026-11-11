"""tpplus.co.nz — Tagata Pasifika (TP+): the long-running Pacific current-
affairs programme's news site — Pasifika leaders, churches, community orgs.
WordPress/Elementor, open robots. Generic RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "tpplus.co.nz"
discover = genericrss.make_discover("https://tpplus.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 13 sub-sitemaps back to 2016.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://tpplus.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
