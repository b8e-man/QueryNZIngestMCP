"""rbnz.govt.nz — Reserve Bank news releases: OCR decisions, speeches,
appointments, enforcement (bank/insurer conditions). Official source, no
robots restrictions. Feed at /feeds/news serves plain; the article pages 403
curl-class TLS (same WAF class as stoppress) — rendered through the headless
browser (hybrid RSS discovery + browser fetch)."""
from __future__ import annotations
from . import genericrss

SOURCE = "rbnz.govt.nz"
discover = genericrss.make_discover("https://www.rbnz.govt.nz/feeds/news")


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    from . import browserfetch
    return await browserfetch.render_all(urls, settle_ms=4000)


extract = genericrss.extract
