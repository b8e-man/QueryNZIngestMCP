"""helenclark.foundation — The Helen Clark Foundation (research-sector wave,
2026-07-25). Low volume, report + news items with author names.
Server-rendered Next/Sanity site, no feed: listing discovery."""
from __future__ import annotations
from . import genericrss
SOURCE = "helenclark.foundation"
discover = genericrss.make_listing_discover(
    "https://helenclark.foundation/news", r'href="(/news/[^"?#]+)"',
    "https://helenclark.foundation")
extract = genericrss.extract
