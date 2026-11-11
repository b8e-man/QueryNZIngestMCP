"""ruralnewsgroup.co.nz — Rural News Group (Rural News + Dairy News):
agri-business, co-ops, processors, land (Joomla). ruralnews.co.nz redirects
here; the real feed is /feed (50 items). Clean robots. Generic RSS scraper."""
from __future__ import annotations

from . import genericrss

SOURCE = "ruralnewsgroup.co.nz"
discover = genericrss.make_discover("https://www.ruralnewsgroup.co.nz/feed")
extract = genericrss.extract
