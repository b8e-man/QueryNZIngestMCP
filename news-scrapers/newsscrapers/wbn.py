"""wbn.co.nz — Waikato Business News (Good Local Media, with Te Awamutu News /
King Country News): Waikato business + local-body coverage. goodlocal.nz
redirects here. WordPress. Generic RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "wbn.co.nz"
discover = genericrss.make_discover("https://wbn.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 16 sub-sitemaps back to 2022.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://wbn.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
