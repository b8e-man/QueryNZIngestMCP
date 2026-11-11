"""Insolvency & Trustee Service public notices (insolvency.govt.nz) —
monthly liquidation / bankruptcy notice pages, plain HTML rows of
"Company Name | date" (recon 2026-07-26; rolling 3-month window, older
months live in the Gazette which we already capture). The register proper
is a React SPA + approval-gated API — recorded on the board, not scraped."""
from . import htmlsource

SOURCE = "insolvency.govt.nz"

_BASE = "https://www.insolvency.govt.nz"

discover = htmlsource.make_discover(
    listings=[f"{_BASE}/about/public-notices"],
    link_re=r'href="(/about/public-notices/[a-z]+-\d{4}-[a-z-]*notices[^"]*)"',
    url_base=_BASE,
)
extract = htmlsource.make_extract(category="notice", selector="main, article, body")
