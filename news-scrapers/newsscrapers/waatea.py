"""waateanews.com — Waatea News (Radio Waatea, Auckland urban Māori): iwi orgs,
Māori trusts, kaupapa politics — the §9 blind-spot pair with Te Ao Māori News.
WordPress, clean robots. Generic RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "waateanews.com"
discover = genericrss.make_discover("https://waateanews.com/feed/")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 84 sub-sitemaps, posts back to 2013 (corpus floor was 2026-07).
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://waateanews.com/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
