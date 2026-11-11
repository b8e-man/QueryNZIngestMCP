"""localmatters.co.nz — Local Matters (Rodney/Hibiscus Coast): where district
council stories break (§9 community network). WordPress, robots open, generous
100-item feed."""
from __future__ import annotations
from . import genericrss
SOURCE = "localmatters.co.nz"
discover = genericrss.make_discover("https://www.localmatters.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 63 sub-sitemaps back to 2022.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.localmatters.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
