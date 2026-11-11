"""Overseas Investment Office decision summaries (linz.govt.nz) — HTML-only
decision pages (recon 2026-07-26: Drupal ?page= pagination, ~48 pages, case
numbers in the path e.g. /decisions/2026-05/202600361). Foreign-ownership
transaction edges: applicant, vendor, consideration, land involved.

Monthly release cadence (last working day), so the front listing page is a
sufficient incremental window."""
from . import htmlsource

SOURCE = "linz.govt.nz"

_BASE = "https://www.linz.govt.nz"

discover = htmlsource.make_discover(
    listings=htmlsource.paged(
        f"{_BASE}/our-work/overseas-investment-regulation/decisions?page={{n}}"),
    link_re=r'href="(/our-work/overseas-investment-regulation/decisions/\d{4}-\d{2}/[A-Za-z0-9]+)"',
    url_base=_BASE,
)
# decision summaries are TABLES inside <main> (no Drupal body wrapper on
# this theme) — htmlsource serializes the container when <p> harvest is thin
extract = htmlsource.make_extract(category="decision", selector="main")
