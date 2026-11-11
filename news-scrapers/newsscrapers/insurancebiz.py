"""insurancebusinessmag.com/nz — Insurance Business NZ (Key Media): insurer
appointments, broker M&A, regulatory actions. Same Key Media platform and
permission posture as NZ Lawyer (robots clean, terms not locatable — re-verify
at commercialisation). NZ-section RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "insurancebusinessmag.com"
discover = genericrss.make_discover("https://www.insurancebusinessmag.com/nz/rss")
extract = genericrss.extract
