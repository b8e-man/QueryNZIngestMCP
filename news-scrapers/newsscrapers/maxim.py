"""maxim.org.nz — Maxim Institute (research-sector wave, 2026-07-25).
Social-policy essays. NB the main /feed/ is EMPTY — articles live on a
custom post type, hence the query-string feed URL."""
from __future__ import annotations
from . import genericrss
SOURCE = "maxim.org.nz"
discover = genericrss.make_discover("https://www.maxim.org.nz/feed/?post_type=article")
extract = genericrss.extract
