"""Privacy Commissioner decision corpora (privacy.org.nz) — case notes,
tribunal/court decisions, decision notes and advisory opinions, published as
HTML pages (recon 2026-07-26: robots-clean, ?start= pagination at 20/page,
slug-borne identifiers like case-note-329275-2025-nz-priv-cmr-2-…).

robots crawl-delay 10 → POLITE_SLEEP 11. All five sections swept; the front
page of each is the incremental window (HTMLSOURCE_PAGES deepens the
back-catalogue at cluster time)."""
from . import htmlsource

SOURCE = "privacy.org.nz"
POLITE_SLEEP = 11.0

_BASE = "https://www.privacy.org.nz"
_SECTIONS = [
    "case-notes-and-court-decisions",
    "tribunal-decisions",
    "court-decisions",
    "decision-notes",
    "advisory-opinions",
]

discover = htmlsource.make_discover(
    listings=[u for s in _SECTIONS for u in htmlsource.paged(
        f"{_BASE}/resources-and-learning/{s}/?start={{n}}", step=20)],
    link_re=(r'href="(/resources-and-learning/(?:' + "|".join(_SECTIONS) +
             r')/[a-z0-9][a-z0-9-]{8,}/?)"'),
    url_base=_BASE,
)
# case-note body lives in <article> with nested wrappers genericrss's
# densest-direct-<p> heuristic misses
extract = htmlsource.make_extract(category="decision", selector="article")
