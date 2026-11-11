"""1news.co.nz — 1News (TVNZ): broad national coverage. Arc/Fusion. robots
allows general crawl (Allow:); AI-training bots (GPTBot/CCBot) are blocked but
we extract, not train — Arthur approved 2026-07-17."""
from __future__ import annotations
from . import arc
SOURCE = "1news.co.nz"
discover = arc.make_discover("https://www.1news.co.nz/arc/outboundfeeds/news-sitemap-index/?outputType=xml")
extract = arc.extract
