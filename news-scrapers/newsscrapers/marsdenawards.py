"""Marsden Fund awarded grants (royalsociety.org.nz) — one HTML table page
per year (2012→current: project ID, panel, title, PI, organisation, amount;
recon 2026-07-26). Each year page lands as one table-shaped article; the
htmlsource container fallback serializes the table. Annual cadence."""
from . import htmlsource

SOURCE = "royalsociety.org.nz"

_BASE = "https://www.royalsociety.org.nz"

discover = htmlsource.make_discover(
    listings=[f"{_BASE}/what-we-do/funds-and-opportunities/marsden/awarded-grants/"],
    # 2026-11-09: the year pages come in two shapes — marsden-awards-YYYY
    # (2012–2017) and marsden-fund-awards-YYYY (2018+) — the old pattern only
    # matched the second and missed the first era.
    link_re=r'href="(/what-we-do/funds-and-opportunities/marsden/awarded-grants/marsden-(?:fund-)?awards-\d{4}/?)"',
    url_base=_BASE,
)
extract = htmlsource.make_extract(category="funding", selector="main, article, body",
                                  min_chars=400)
