"""valleyprofile.co.nz — The Valley Profile: Thames Valley / Hauraki district
coverage (a coverage hole between Waikato and BoP). WordPress, open robots."""
from __future__ import annotations
from . import genericrss
SOURCE = "valleyprofile.co.nz"
discover = genericrss.make_discover("https://www.valleyprofile.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 8 sub-sitemaps.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.valleyprofile.co.nz/sitemap.xml",
    "sitemap_re": r"/wp-sitemap-posts-post-",
}
