"""thestandard.nz — left-leaning NZ political blog (WordPress); balances
kiwiblog's lens. Clean robots. Generic RSS scraper. NB: the old
thestandard.org.nz 301-redirects here and its articles carry .nz URLs, so
SOURCE is the .nz content domain (matches the landed URL host)."""
from __future__ import annotations
from . import genericrss
SOURCE = "thestandard.nz"
discover = genericrss.make_discover("https://thestandard.nz/feed/")
extract = genericrss.extract
