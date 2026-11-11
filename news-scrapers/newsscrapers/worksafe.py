"""worksafe.govt.nz — WorkSafe NZ media releases: prosecutions, enforceable
undertakings, sentencing — company names + directors, very register-dense.
Official source, open robots. RSS under /about-us/news-and-media/rss."""
from __future__ import annotations
from . import genericrss
SOURCE = "worksafe.govt.nz"
discover = genericrss.make_discover("https://www.worksafe.govt.nz/about-us/news-and-media/rss")
extract = genericrss.extract
