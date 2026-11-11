"""Serious Fraud Office media releases + case pages (sfo.govt.nz) — listing
is JS-injected but the SilverStripe sitemap enumerates every detail URL
(recon 2026-07-26). Sitemap-diff discovery, same as RBNZ."""
from . import htmlsource

SOURCE = "sfo.govt.nz"

discover = htmlsource.make_sitemap_discover(
    "https://www.sfo.govt.nz/sitemap.xml",
    include_re=r"/media-cases/(?:media-releases|cases)/[a-z0-9-]+$",
)
extract = htmlsource.make_extract(category="release",
                                  selector="article, .content, main")
