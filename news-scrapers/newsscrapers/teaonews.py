"""teaonews.co.nz — Te Ao Māori News (Whakaata Māori): iwi orgs, Māori trusts,
te ao Māori coverage — a mainstream blind spot. Arc/Fusion. Clean robots."""
from __future__ import annotations
from . import arc
SOURCE = "teaonews.co.nz"
discover = arc.make_discover("https://www.teaonews.co.nz/arc/outboundfeeds/sitemap-news/latest/?outputType=xml")
extract = arc.extract
