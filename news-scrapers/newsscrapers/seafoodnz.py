"""seafood.co.nz — Seafood NZ: industry news, quota/market, MPI-facing.
Was TYPO3 (news-and-events/news/detail/); the site is WordPress now — the
old listing/detail shapes are gone. 2026-11-09: /feed/ answers 200 with 10
items, so discovery rides the feed like the other WP sources."""
from __future__ import annotations
from . import genericrss
SOURCE = "seafood.co.nz"
discover = genericrss.make_discover("https://www.seafood.co.nz/feed/")
extract = genericrss.extract
