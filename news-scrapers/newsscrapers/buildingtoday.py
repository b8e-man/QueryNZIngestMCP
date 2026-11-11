"""buildingtoday.co.nz — Building Today, the Registered Master Builders
Association's official magazine (WordPress; trade-press wave tier 1,
2026-07-25). Projects, contractors, consents. Empty robots. Generic RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "buildingtoday.co.nz"
discover = genericrss.make_discover("https://www.buildingtoday.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 11 sub-sitemaps back to 2019.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://buildingtoday.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
