"""infrastructure.org.nz — Infrastructure New Zealand, the sector body
(research-sector wave, 2026-07-25). Firms, ministers, project names.
WP feed, robots allow-all.

Their WAF 403s any self-identified bot UA (the declared QueryNZ UA and
"Mozilla/5.0 (compatible; …)" variants blocked, plain browser UAs pass —
tested 2026-08-14) while robots.txt disallows nothing. Arthur's ruling
2026-08-14: wear the disguise."""
from __future__ import annotations
from . import genericrss

SOURCE = "infrastructure.org.nz"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
discover = genericrss.make_discover("https://infrastructure.org.nz/feed/")
extract = genericrss.extract
