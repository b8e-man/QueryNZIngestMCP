"""royalsociety.org.nz — Royal Society Te Apārangi news (research-sector
wave, 2026-07-25). Fellowship/award announcements are dense lists of NZ
researcher names. SilverStripe, no feed: listing discovery."""
from __future__ import annotations
from . import genericrss
SOURCE = "royalsociety.org.nz"
discover = genericrss.make_listing_discover(
    "https://www.royalsociety.org.nz/news", r'href="(/news/[^"?#]+)"',
    "https://www.royalsociety.org.nz")
extract = genericrss.extract
