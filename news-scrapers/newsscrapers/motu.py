"""motu.nz — Motu Economic and Public Policy Research news (research-sector
wave, 2026-07-25). Named researchers, ETS/climate work. robots asks
Crawl-delay: 30 (honored via POLITE_SLEEP) and Disallows /feed AND
/find-publications — so the HTML news listing is the ONLY discovery
surface; the publications search stays untouched, absolutely (robots
absolutism; re-verified 2026-08-03).

Archive: offset pagination `?start=N` in steps of 10, walked by
discover_archive at the site's own 30s crawl delay — slow by their choice,
which we honour. Article pages carry NO date markup anywhere (probed
2026-08-03), so published_at stays honestly None."""
from __future__ import annotations
from . import genericrss

SOURCE = "motu.nz"
POLITE_SLEEP = 30.0
_LINK_RE = r'href="(/about-us/news/[^"?#]+)"'
_BASE = "https://www.motu.nz"

discover = genericrss.make_listing_discover(
    f"{_BASE}/about-us/news", _LINK_RE, _BASE)
discover_archive = genericrss.make_paged_listing_discover(
    lambda n: f"{_BASE}/about-us/news?start={n * 10}", _LINK_RE, _BASE,
    polite=POLITE_SLEEP)
extract = genericrss.extract
