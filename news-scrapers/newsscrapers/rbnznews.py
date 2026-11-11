"""RBNZ news + enforcement (rbnz.govt.nz) — the listing pages are Coveo/JS
shells, but sitemap.xml enumerates every detail URL (recon 2026-07-26), so
discovery is sitemap-diff: the ledger turns the full-history sitemap into an
incremental feed. Cloudflare UA-filters some fetchers; if our honest UA
starts 403ing, this becomes a browser-tier candidate."""
from . import htmlsource

SOURCE = "rbnz.govt.nz"

discover = htmlsource.make_sitemap_discover(
    "https://www.rbnz.govt.nz/sitemap.xml",
    include_re=r"/news-and-events/news/\d{4}/",
)
extract = htmlsource.make_extract(category="release",
                                  selector="article, .content, main")
