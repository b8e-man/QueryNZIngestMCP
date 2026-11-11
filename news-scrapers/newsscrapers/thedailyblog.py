"""thedailyblog.co.nz — NZ political/commentary blog (WordPress). Clean robots.
Generic RSS scraper."""
from __future__ import annotations
from . import genericrss
SOURCE = "thedailyblog.co.nz"
discover = genericrss.make_discover("https://thedailyblog.co.nz/feed/")
extract = genericrss.extract
