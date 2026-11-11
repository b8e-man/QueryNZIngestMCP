"""nzinitiative.org.nz — The New Zealand Initiative (research-sector wave,
2026-07-25). Opinion/media/reports name its economists, ministers, and
policy targets. SilverStripe, /rss 404: listing discovery over the
reports-and-media hub. 2026-11-09: the listing 301s to /reports-and-media and
article hrefs lost their trailing slash — the old pattern required one and
matched nothing (the quote class is \x22 so the raw string stays escaping-free)."""
from __future__ import annotations
from . import genericrss
SOURCE = "nzinitiative.org.nz"
discover = genericrss.make_listing_discover(
    "https://www.nzinitiative.org.nz/reports-and-media/",
    r'href="(/reports-and-media/[a-z-]+/[^/\x22?#]+)/?"',
    "https://www.nzinitiative.org.nz")
extract = genericrss.extract
