"""kanivatonga.co.nz — Kaniva Tonga: NZ Tongan community news (Pasifika blind
spot). WordPress; the pretty /feed paths 404 but the query form works. NB the
canonical article host is .co.nz (the bare .nz mirrors/redirects into it), so
SOURCE is the .co.nz domain the landed URLs actually carry."""
from __future__ import annotations
from . import genericrss
SOURCE = "kanivatonga.co.nz"
discover = genericrss.make_discover("https://kanivatonga.co.nz/?feed=rss2")
extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 107 sub-sitemaps back to 2023.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://kanivatonga.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
