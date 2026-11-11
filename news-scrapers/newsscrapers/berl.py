"""berl.co.nz — BERL economic insights (research-sector wave, 2026-07-25).
Budget/sector commentary naming NZ orgs. Drupal, no feed: listing
discovery. robots: Cloudflare content-signal ai-train=no + named-AI-bot
blocks — the general agent is allowed (`User-agent: * / Allow: /`,
re-verified 2026-08-03) and we do inference-time extraction, not training
(the 1news/sunlive stance).

Archive: Drupal pagination `?page=N`, walked by discover_archive (institute
backwalk, 2026-08-03). Dates live in the Drupal date field, not meta tags —
the generic extractor returned published_at=None on every article."""
from __future__ import annotations

from bs4 import BeautifulSoup

from . import base, genericrss

SOURCE = "berl.co.nz"
_LINK_RE = r'href="(/economic-insights/[^"?#]+)"'
_BASE = "https://www.berl.co.nz"

discover = genericrss.make_listing_discover(
    f"{_BASE}/economic-insights", _LINK_RE, _BASE)
discover_archive = genericrss.make_paged_listing_discover(
    lambda n: f"{_BASE}/economic-insights?page={n}", _LINK_RE, _BASE)


def extract(html: str, url: str) -> base.Extracted | None:
    ex = genericrss.extract(html, url)
    if ex is None or ex.published_at is not None:
        return ex
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".field--name-field-date .field__item, "
                         ".field--name-field-date")
    when = genericrss.month_name_date(el.get_text(" ", strip=True)) if el else None
    return base.Extracted(title=ex.title, text=ex.text, author=ex.author,
                          published_at=when, categories=ex.categories)
