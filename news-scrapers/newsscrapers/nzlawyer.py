"""thelawyermag.com/nz — NZ Lawyer (Key Media): legal-sector trade — partner
moves, firm mergers, discipline, in-house appointments. Entity-dense for the
legal vertical. robots clean; publisher terms not locatable after reasonable
search (no explicit AI/LLM clause found) — re-verify at commercialisation,
same posture as the general licence review. NZ-section RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "thelawyermag.com"
discover = genericrss.make_discover("https://www.thelawyermag.com/nz/rss")
extract = genericrss.extract
