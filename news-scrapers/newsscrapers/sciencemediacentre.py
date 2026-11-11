"""sciencemediacentre.co.nz — expert reactions with named scientists + their
affiliations (WordPress). Tailor-made for person↔org claims. Clean robots.
Generic RSS scraper."""
from __future__ import annotations

from . import genericrss

SOURCE = "sciencemediacentre.co.nz"
discover = genericrss.make_discover("https://www.sciencemediacentre.co.nz/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 22 sub-sitemaps back to 2012.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.sciencemediacentre.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
