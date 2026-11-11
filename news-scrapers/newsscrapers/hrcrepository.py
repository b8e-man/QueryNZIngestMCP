"""Health Research Council research repository (hrc.govt.nz) — funded-project
records: title, lay summary, PI, host organisation, budget, start year
(recon 2026-07-26: server-rendered, ?page=0..~66, detail-page hop).
Funder→institution→researcher money edges for the research arm."""
from . import htmlsource

SOURCE = "hrc.govt.nz"

_BASE = "https://www.hrc.govt.nz"

discover = htmlsource.make_discover(
    listings=htmlsource.paged(f"{_BASE}/resources/research-repository?page={{n}}"),
    link_re=r'href="(/resources/research-repository/[a-z0-9][a-z0-9-]+)"',
    url_base=_BASE,
)
extract = htmlsource.make_extract(category="funding", selector=".region-content")
