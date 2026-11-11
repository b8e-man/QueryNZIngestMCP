"""NZME / NZ Herald network — CAPTURE-AND-HOLD (ruling 115, 2026-08-24).

NZME's robots.txt permits our honest UA on the article and Arc-feed paths
(the `User-agent: *` block disallows only /premium/, /my-account/, search and
query-junk; the blanket `Disallow: /` blocks are all NAMED AI/scraper bots —
ClaudeBot, GPTBot, CCBot, Scrapy, Python-urllib… — none of which we are).
Robots snapshot archived var/audits/source-policy/nzherald.co.nz-robots-2026-08-24.txt
(sha256 c09ee7e7…, ruling 79).

The restriction is the TERMS preamble: content not for "LLMs, machine learning
and/or AI ... and/or commercial purposes". So these articles are HELD, never
extracted: base.run_source lands NZME URLs as pipeline_status 'held'
(review_sources.HELD_SOURCE_DOMAINS → nzherald.co.nz), the extractor and the
embedder both exclude held, and no model of any kind touches the content until
an NZME licence lands. Semantic search is itself ML (embeddings), so it is
excluded too — holding means holding, not "serve it a different way".

One Arc/Fusion outbound feed per masthead (`_website=`) under nzherald.co.nz:
nzh (Herald) + 13 regionals/verticals (bay-of-plenty-times, hawkes-bay-today,
newstalk-zb, rotorua-daily-post, the-country, northern-advocate, northland-age,
waikato-news, whanganui-chronicle, gisborne-herald, viva, eatwell, the-listener).
The sitemap-index lists ~10k dated sub-sitemaps (one 'latest' + one per day back
years); each carries ~90 article URLs. Fresh capture reads 'latest'; the depth
lane (ARCHIVE) walks the dated ones oldest-first.

Body parsing is DETERMINISTIC (genericrss.extract = BeautifulSoup, no model) —
it only produces the text we STORE; nothing is extracted into the graph.
"""
from __future__ import annotations

import re

from . import base, genericrss

# THE LABEL IS THE HOST, NOT THIS MODULE'S NAME (C548, 2026-10-09).
#
# This was `"nzme"`, and the registry key for this lane is already the host
# (`"nzherald.co.nz": Entry("nzme", …)`). The label goes into `articles.sources`,
# which is the JOIN KEY to `v3.source_policy` — so 640,836 articles, 8.8% of the
# whole corpus, reached no policy row at all and no gate could confirm the
# disposition they were in fact honouring (C530, #4fc0a2).
#
# SAFE, AND MEASURED BEFORE IT WAS CHANGED. `mod.SOURCE` reaches two decisions:
#   held_reason([SOURCE], url) -> both labels return the SAME ruling-115 reason,
#       because `held_reason` substring-matches the url as well and
#       `nzherald.co.nz` is in HELD_SOURCE_DOMAINS;
#   is_review_source([SOURCE]) -> False for both, since no key of
#       DEDICATED_SOURCE_DOMAINS is a substring of either string.
# Verified by calling both functions with `nzme`, `nzherald.co.nz` and
# `www.nzherald.co.nz`: held=True / parked=False for all three.
#
# AND IT MAKES THE PROTECTION REDUNDANT INSTEAD OF URL-ONLY. Asked WITHOUT a url,
# `held_reason(["nzme"])` is **False** while `held_reason(["nzherald.co.nz"])` is
# True — so today the hold on 640,836 articles rests entirely on `news_url`. No
# live caller asks that way for this lane (`disposition_for` passes a host, and
# `base.py` passes the url), so the risk was latent; after this either signal
# alone suffices.
SOURCE = "nzherald.co.nz"
POLITE_SLEEP = 2.0                      # a large publisher; pace gently

WEBSITE = "nzh"                          # the Herald; other mastheads override
_INDEX = ("https://www.nzherald.co.nz/arc/outboundfeeds/sitemap-index/"
          "?outputType=xml&_website={site}")
_LATEST = ("https://www.nzherald.co.nz/arc/outboundfeeds/sitemap/latest/"
           "?outputType=xml&_website={site}")

# an NZME article URL ends in a 26-char Arc id; /premium/ is paywalled AND
# robots-disallowed for '*', so it is dropped at discovery.
# _ARC_TAIL is THE one Arc-id rule — the fresh path (_ARTICLE) and the archive
# path (ARCHIVE["article_re"]) both build from it, so they cannot drift apart
# (2026-08-30, the edited-together hazard folded; test_nzme_predicate pins the
# two paths' agreement).
_ARC_TAIL = r"/[A-Z0-9]{24,}/?$"
_ARTICLE = re.compile(r"^https?://www\.nzherald\.co\.nz/\S+" + _ARC_TAIL)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)


def _articles(xml: str) -> list[str]:
    out = []
    for raw in _LOC.findall(xml):
        u = raw.replace("&amp;", "&").strip()
        if "/premium/" in u:
            continue                    # paywalled + robots-disallowed
        if _ARTICLE.match(u):
            out.append(u)
    return out


def make_discover(site: str = WEBSITE):
    async def discover(client) -> list[base.FeedItem]:
        try:
            xml = (await base.fetch(client, _LATEST.format(site=site))).text
        except Exception as e:  # noqa: BLE001
            print(f"  nzme[{site}] latest sitemap error: {type(e).__name__}: {e}")
            return []
        seen: set[str] = set()
        items: list[base.FeedItem] = []
        for u in _articles(xml):
            if u in seen:
                continue
            seen.add(u)
            items.append(base.FeedItem(url=u))     # title/date come from the page
        return items
    return discover


discover = make_discover(WEBSITE)
extract = genericrss.extract

# the 14 mastheads, each its own Arc outbound feed (robots.txt Sitemap: lines).
MASTHEADS = ("nzh", "viva", "bay-of-plenty-times", "hawkes-bay-today",
             "newstalk-zb", "rotorua-daily-post", "the-country",
             "northern-advocate", "northland-age", "waikato-news",
             "whanganui-chronicle", "eatwell", "the-listener", "gisborne-herald")

# Depth lane (ruling 28 / ruling 115 "get it all"): walk EVERY masthead's
# sitemap-index, oldest sub-sitemap first, resuming across the whole network
# (sub-sitemap URLs carry _website= so one `done` set spans all 14). /premium/
# is dropped by article_re + the _articles filter at fetch. The nzme-archive-
# backfill timer runs this in bounded chunks until the ~140k dated sub-sitemaps
# are exhausted.
ARCHIVE = {
    "index": [_INDEX.format(site=s) for s in MASTHEADS],
    # the deep archive is `sitemap3/YYYY-MM-DD/` (10,171 dated sub-sitemaps per
    # masthead, back to 1998-10-12); `sitemap`/`sitemap2` are only the last few
    # days. `sitemap\d?` matches all three shapes — an earlier `sitemap2?`
    # silently dropped the entire back-catalogue.
    "sitemap_re": r"/sitemap\d?/\d{4}-\d{2}-\d{2}/",
    # ends in a 26-char Arc id AND is not under /premium/ (paywalled + robots-
    # disallowed for '*'): the negative lookahead drops premium in the archive
    # path, matching _articles() on the fresh path — the Arc-id tail is the
    # SHARED _ARC_TAIL constant, so the two paths cannot drift.
    "article_re": r"^(?!.*/premium/).*" + _ARC_TAIL,
    "polite": POLITE_SLEEP,
    # NEWEST sub-sitemap first: the deep archive's pre-2005 dates are mostly
    # empty (regionals did not exist; even nzh's 1998 sub-sitemaps are empty),
    # so oldest-first would burn weeks of 2s listing fetches before any content
    # lands. Newest-first lands the dense recent history (which fresh capture
    # does NOT hold beyond the last day) from the first tick and works back to
    # 1998. "Get it all" is unchanged — every sub-sitemap is still walked.
    "oldest_first": False,
}
