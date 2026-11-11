"""phcc.org.nz — Public Health Communication Centre weekly Briefings
(research-sector wave, 2026-07-25). Every briefing names NZ public-health
academics + agencies — the highest-value non-feed source in the wave.
Drupal, no RSS: listing discovery over /briefing."""
from __future__ import annotations
from . import genericrss
SOURCE = "phcc.org.nz"
discover = genericrss.make_listing_discover(
    "https://www.phcc.org.nz/briefing", r'href="(/briefing/[^"?#]+)"',
    "https://www.phcc.org.nz")
extract = genericrss.extract
