"""times.co.nz — Times Online (East Auckland / Howick): local body + business
coverage. robots allows the general agent (named AI-training crawlers blocked;
ai-train=no satisfied — we extract at inference, not train). RSS at /feed/ for
discovery; article pages 403 curl-class clients (Cloudflare TLS fingerprint)
so they render through the headless browser like stoppress."""
from __future__ import annotations
from . import genericrss

SOURCE = "times.co.nz"
discover = genericrss.make_discover("https://www.times.co.nz/feed/")


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    from . import browserfetch
    return await browserfetch.render_all(urls, settle_ms=5000)


extract = genericrss.extract


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 54 sub-sitemaps back to 2018.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.times.co.nz/sitemap_index.xml",
    "sitemap_re": r"/post-sitemap",
}

# C215 (2026-10-08): LAND IN CHUNKS, because this source renders through a
# headless browser at ~5 s a page and the coverage service caps an archive
# slice at 8 minutes. `fetch_all` used to be atomic over the whole discovered
# set, so the slice cap killed the render before anything landed — this walk
# ran on 10-05, 10-06, 10-07 and 10-08 and landed NOTHING each time while
# reporting rc 0. 40 pages is ~3.5 min, so a chunk completes inside the slice
# and the next run's pre-fetch dedup skips what this one banked.
FETCH_CHUNK = 40
