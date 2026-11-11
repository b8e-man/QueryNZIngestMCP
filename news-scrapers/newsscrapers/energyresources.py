"""energyresources.org.nz — Energy Resources Aotearoa, the oil/gas/energy
sector body's wire (trade-press wave tier 2, 2026-07-25). The real energy
trade organs (Energy News NZ, Inside Resources) are subscription-gated; this
is the free, high-authority, register-adjacent substitute the todo picked.
SilverStripe with a deep RSS (/news/rss, ~276 items). robots asks
Crawl-Delay: 10 — honored via the module POLITE_SLEEP override."""
from __future__ import annotations
from . import genericrss
SOURCE = "energyresources.org.nz"
POLITE_SLEEP = 10.0
discover = genericrss.make_discover("https://www.energyresources.org.nz/news/rss")
extract = genericrss.extract
