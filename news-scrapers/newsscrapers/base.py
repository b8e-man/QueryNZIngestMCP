"""newsscrapers — direct-to-backlog NZ news scrapers (ports of the Java
scraper-service in ops/scraper-service-standalone).

Design (kept from the Java framework): per-source module with two phases —
DISCOVERY (RSS/sitemap → candidate items) and CONTENT (fetch page → extract
title/body/author/date). The persistence differs deliberately: instead of the
dashboard's Postgres+ES, every article lands in OUR backlog via
querynz.ingestion.land_document (contract 1, idempotent on upstream_id) — these
ports REPLACE the stalled dashboard as the fresh-news path. Parking (A0.4) and
content-dedup apply at land time exactly as for dashboard rows.

Each source module provides:
    FEEDS: list[str]                      (RSS/atom URLs)
    def extract(html: str, url: str) -> Extracted | None   (pure — golden-testable)
    optionally discover() for non-RSS sources.

Politeness: one fetch at a time per host, POLITE_SLEEP between requests.
"""
from __future__ import annotations

import asyncio
import email.utils
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import ssl

import httpx

POLITE_SLEEP = 2.0
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"

# Some hosts (rnz.co.nz) fingerprint the TLS handshake and 403 python's default
# cipher ordering; a Chrome-style cipher list passes. Applied to every client —
# harmless for hosts that don't care.
# FROZEN EXCEPTION on the TLS-handshake axis (Arthur 2026-09-04, ruling 169 —
# Muster 2 B4, audit A21), argued in SCRAPING_RULES §1 beside the browser-UA
# list: the cipher order is presentation, not identity — the UA on every
# request stays the honest, contactable one, and the list applies only where
# robots.txt permits (the same fetch path honours the same robots facts). It
# never justifies a CAPTCHA, a forged credential or an identity rotation.
# tests/test_boundaries.py pins this as the ONE cipher context in capture.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.set_ciphers(
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA")


def make_client(**kw) -> httpx.AsyncClient:
    """The client every runner should use (Chrome-cipher TLS context)."""
    return httpx.AsyncClient(verify=_SSL_CTX, **kw)


@dataclass
class Extracted:
    title: str
    text: str
    author: str | None = None
    published_at: datetime | None = None
    categories: list[str] = field(default_factory=list)


@dataclass
class FeedItem:
    url: str
    title: str | None = None
    published_at: datetime | None = None
    category: str | None = None


def parse_rss(xml_text: str) -> list[FeedItem]:
    """RSS 2.0 / Atom → FeedItems (stdlib only)."""
    root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items: list[FeedItem] = []
    for it in root.iter("item"):                       # RSS 2.0
        link = (it.findtext("link") or "").strip()
        if not link:
            continue
        pub = it.findtext("pubDate")
        items.append(FeedItem(
            url=link, title=(it.findtext("title") or "").strip() or None,
            published_at=_rfc2822(pub), category=(it.findtext("category") or "").strip() or None))
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):   # Atom
        link_el = it.find("a:link[@rel='alternate']", ns) or it.find("a:link", ns)
        link = (link_el.get("href") if link_el is not None else "") or ""
        if not link:
            continue
        pub = it.findtext("a:published", None, ns) or it.findtext("a:updated", None, ns)
        items.append(FeedItem(url=link.strip(),
                              title=(it.findtext("a:title", "", ns) or "").strip() or None,
                              published_at=_iso(pub)))
    return items


def _rfc2822(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        return None


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def clean_text(parts: list[str]) -> str:
    """Join paragraph strings into the golden-sample content shape."""
    out = [re.sub(r"[ \t ]+", " ", p).strip() for p in parts]
    return "\n\n".join(p for p in out if p)


# ── page-metadata fallback (estate-improvements practice 4, 2026-11-15) ──
# Fill published_at/author from the page's OWN printed metadata when the
# source module's extractor didn't: article:published_time / datePublished
# meta, JSON-LD, <time datetime>, byline meta tags. Never overrides what a
# module extracted; never scrapes prose (metadata layer only).
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w[\w:.-]*)\s*=\s*(["\'])(.*?)\2', re.I | re.S)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S)
_TIME_DT_RE = re.compile(
    r'<time\b[^>]*datetime=["\']([^"\']+)["\']', re.I | re.S)
_STYLE_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATELINE_RE = re.compile(
    r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s*,?\s*\d{4})")

_DATE_KEYS = {"article:published_time", "datepublished", "dc.date",
              "dcterms.date", "date", "parsely-pub-date", "sailthru.date",
              "og:published_time", "article:published"}
_AUTHOR_KEYS = {"author", "article:author", "dc.creator", "parsely-author",
                "sailthru.author", "byl", "twitter:creator"}


def _parse_pub(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    for fn in (lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
               email.utils.parsedate_to_datetime,
               lambda v: datetime.strptime(v.replace(",", ""), "%d %B %Y")):
        try:
            dt = fn(s)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _jsonld_meta(html: str) -> tuple[str | None, str | None]:
    pub = auth = None

    def walk(node):
        nonlocal pub, auth
        if isinstance(node, dict):
            dp = node.get("datePublished")
            if not pub and isinstance(dp, str):
                pub = dp
            a = node.get("author")
            if not auth:
                if isinstance(a, dict):
                    nm = a.get("name")
                    auth = nm if isinstance(nm, str) and nm else None
                    if not auth and isinstance(nm, list):
                        auth = " / ".join(x for x in nm if isinstance(x, str) and x) or None
                elif isinstance(a, list) and a:
                    names = [x.get("name") for x in a if isinstance(x, dict)]
                    names = [n for n in names if isinstance(n, str) and n]
                    if names:
                        auth = " / ".join(names[:3])
                elif isinstance(a, str):
                    auth = a or None
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    import json as _json
    for m in _JSONLD_RE.finditer(html):
        try:
            walk(_json.loads(m.group(1).strip()))
        except (ValueError, TypeError):
            continue
        if pub and auth:
            break
    return pub, auth


def page_metadata(html: str) -> tuple[datetime | None, str | None]:
    """(published_at, author) as the page itself prints them. Either None."""
    raw_date = raw_auth = None
    for tag in _META_TAG_RE.finditer(html[:200000]):
        attrs = {m.group(1).lower(): m.group(3)
                 for m in _ATTR_RE.finditer(tag.group(0))}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or ""
        val = (attrs.get("content") or "").strip()
        if not key or not val:
            continue
        key = key.lower()
        if not raw_date and key in _DATE_KEYS:
            raw_date = val
        elif not raw_auth and key in _AUTHOR_KEYS:
            raw_auth = val
    if not (raw_date and raw_auth):
        jd, ja = _jsonld_meta(html[:400000])
        raw_date = raw_date or jd
        raw_auth = raw_auth or ja
    if not raw_date:
        tm = _TIME_DT_RE.search(html[:200000])
        if tm:
            raw_date = tm.group(1)
    if not raw_date:
        # dateline as printed (practice 4 names "a dateline" explicitly):
        # strip style/script blobs and tags, then take the date ONLY if a
        # single distinct long-form date sits in the visible head. Two or
        # more distinct dates = ambiguous (event dates in body) -> None.
        t = _STYLE_SCRIPT_RE.sub(" ", html[:600000])
        t = _TAG_RE.sub(" ", t)
        t = re.sub(r"\s+", " ", t)[:5000]
        seen = []
        for m in _DATELINE_RE.finditer(t):
            canon = re.sub(r"\s*,?\s+", " ", m.group(1)).strip()
            if canon not in seen:
                seen.append(canon)
                if len(seen) > 1:
                    break
        if len(seen) == 1:
            raw_date = seen[0]
    pub = _parse_pub(raw_date or "")
    if isinstance(raw_auth, list):   # odd JSON-LD shapes ({name:[...]})
        raw_auth = " / ".join(str(x) for x in raw_auth if isinstance(x, str))
    auth = (raw_auth or "").strip() or None
    if auth and len(auth) > 200:
        auth = auth[:200]
    return pub, auth


async def fetch(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    # a module may declare USER_AGENT (run_source stamps it on the client):
    # infrastructure.org.nz's WAF 403s self-identified bots while its
    # robots.txt allows all — Arthur's ruling 2026-08-14: wear the disguise
    ua = getattr(client, "_querynz_ua", UA)
    r = await client.get(url, follow_redirects=True,
                         headers={"User-Agent": ua}, timeout=30, **kw)
    r.raise_for_status()
    return r


async def run_source(mod, *, hours: int = 48, limit: int = 200, dry: bool = False) -> dict:
    """Discovery → fetch → extract → land. Shared runner for every port."""
    from datetime import timedelta

    # landing via the capture adapter (manifest.jsonl + raw store + extracted
    # stage — see capture.py). The v2 land_document/backlog path is retired.
    import capture as _capture
    import proxies as _proxies
    from news.review_sources import held_reason, is_review_source

    # Muster 2 B4 (audit A22): every discovered item ends in EXACTLY one
    # bucket, and `reconcile(stats)` proves it — an uncounted drop was how
    # thin/auth-skipped/limit-cut articles vanished from the run report.
    stats = {"discovered": 0, "skipped_seen": 0, "limit_cut": 0, "auth_skip": 0,
             "fetched": 0, "thin": 0, "landed": 0, "dup_content": 0, "errors": 0,
             "already_held": 0}
    # robots Crawl-Delay honoring: a module may declare its own POLITE_SLEEP
    # (energyresources.org.nz asks for 10s)
    polite = getattr(mod, "POLITE_SLEEP", POLITE_SLEEP)
    parked = is_review_source([mod.SOURCE])
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with make_client(proxy=_proxies.httpx_proxy(mod.SOURCE)) as client:
        client._querynz_ua = getattr(mod, "USER_AGENT", UA)  # see fetch()
        items: list[FeedItem] = []
        if hasattr(mod, "discover"):
            items = await mod.discover(client)
        else:
            for feed in mod.FEEDS:
                try:
                    items += parse_rss((await fetch(client, feed)).text)
                except Exception as e:  # noqa: BLE001
                    print(f"  feed error {feed}: {type(e).__name__}: {e}")
                    stats["errors"] += 1
                await asyncio.sleep(polite)
        seen: set[str] = set()
        items = [i for i in items
                 if not (i.url in seen or seen.add(i.url))
                 and (i.published_at is None or i.published_at >= since)]
        stats["discovered"] = len(items)

        # PRE-FETCH dedup: drop URLs this source already ingested BEFORE fetching
        # (real runs only; parked sources own their own dedup). Saves the
        # expensive re-render for browser sources — beehive/businessdesk re-saw
        # the same ~10–30 articles every run. Content-hash dedup still runs after
        # fetch to catch cross-source syndication.
        if not dry and not parked and items:
            already = _capture.seen_refs(mod.SOURCE, [i.url for i in items])
            if already:
                kept = [i for i in items if i.url not in already]
                stats["skipped_seen"] = len(items) - len(kept)
                items = kept
        # LAND ONLY WHAT NOBODY HOLDS (Arthur, 2026-11-09): drop URLs the
        # estate's manifests (or the MCP's beehive corpus) already hold BEFORE
        # fetching — the news lane complements the holdings, it never
        # duplicates them. Real runs only, like the seen-dedup above.
        if not dry and items:
            mine = [i for i in items if not _capture.already_held(i.url)]
            stats["already_held"] = len(items) - len(mine)
            items = mine
        # `limit` bounds NEW fetches, applied AFTER the pre-fetch dedup
        # (2026-08-24, ruling 28): with the cut before it, an archive walk
        # whose first `limit` urls were already held did nothing each run and
        # never advanced into the part of the archive we do not hold.
        stats["limit_cut"] = max(0, len(items) - limit)
        items = items[:limit]

        # authenticated batch fetch (nbr/businessdesk): the module logs in once
        # and fetches every url in one browser context. Failure falls back to
        # plain fetches — the 200-char floor then drops the paywall teasers.
        #
        # CHUNKED, OPT-IN (C215, 2026-10-08). `fetch_all` was ATOMIC over the
        # whole discovered set, and for a browser source that is hours: the
        # archive walk discovers up to --limit 1500 urls and `render_all`
        # renders every one before the landing loop below begins. The coverage
        # service caps an archive slice at 8 MINUTES, so the process was killed
        # mid-render every single time and NOTHING landed — measured on
        # times.co.nz, which ran this walk on 10-05, 10-06, 10-07 and 10-08,
        # reported `0 sub-sitemaps already done` each run, exited rc 0, and
        # holds 719 records whose earliest post_date is 2026-07-16 against an
        # archive going back to 2018. Eight polite minutes a day against a real
        # publisher, for nothing, reported as success.
        #
        # So a module may declare `FETCH_CHUNK = n`: the batch is rendered and
        # LANDED n urls at a time, and a killed run keeps every completed
        # chunk. The next run's pre-fetch dedup then skips them, which is how
        # ruling 28 already intends progress to be measured — by what we hold.
        #
        # It is OPT-IN because the authenticated lanes log in once per
        # `fetch_all` call: chunking nbr or businessdesk would multiply that by
        # the chunk count, and thirty logins inside eight minutes against a
        # paywall is a different kind of request. Only the two lanes with no
        # login and a real archive declare it.
        chunk = getattr(mod, "FETCH_CHUNK", 0) or len(items) or 1
        html_by_url: dict[str, str] | None = None

        for _i, it in enumerate(items):
            if hasattr(mod, "fetch_all") and _i % chunk == 0:
                html_by_url = None
                try:
                    html_by_url = dict(await mod.fetch_all(
                        [x.url for x in items[_i:_i + chunk]]))
                except Exception as e:  # noqa: BLE001
                    print(f"  authenticated fetch failed ({type(e).__name__}: {e}) "
                          f"— plain fetch fallback")
            try:
                if html_by_url is not None:
                    maybe = html_by_url.get(it.url)
                    if maybe is None:
                        stats["auth_skip"] += 1
                        continue           # skipped by the auth fetch (redirect/paywall check)
                    html = maybe
                    raw_bytes, fetch_mode = html.encode("utf-8"), "batch"
                else:
                    _resp = await fetch(client, it.url)
                    html = _resp.text
                    raw_bytes, fetch_mode = _resp.content, "direct"
                ex = mod.extract(html, it.url)
                stats["fetched"] += 1
                if ex is None or len(ex.text) < 200:
                    stats["thin"] += 1
                    continue
                # practice 4 (estate-improvements, 2026-11-15): date/byline as
                # the page prints them, when the module didn't extract one.
                if ex.published_at is None or not ex.author:
                    m_pub, m_auth = page_metadata(html)
                    if ex.published_at is None:
                        ex.published_at = m_pub
                    if not ex.author:
                        ex.author = m_auth
                if dry:
                    print(f"  DRY {it.url} — {ex.title[:60]!r} ({len(ex.text)} chars)")
                    stats["landed"] += 1
                    continue
                import hashlib
                pub = ex.published_at or it.published_at
                # future-date sanity clamp (2026-07-20, crux incident: the
                # site's own JSON-LD carries wrong dates like 2026-10-01 on a
                # March article, and future dates pin the top of every
                # date-sorted feed) — an impossible date is worse than none.
                if pub is not None:
                    pd = pub.date() if isinstance(pub, datetime) else pub
                    if pd > (datetime.now(timezone.utc).date() + timedelta(days=1)):
                        pub = None
                # stable 63-bit URL hash — the idempotency-key parity field.
                upstream = int.from_bytes(
                    hashlib.sha1(it.url.encode()).digest()[:8], "big") >> 1
                # HELD (ruling 99/115): a source whose terms bar our
                # extraction (Waitangi Tribunal; NZME's ML prong) is captured
                # but never extracted. Checked per-URL: one Arc feed spans
                # many masthead domains. land() dedups on sha256/url
                # regardless of status (we hold one copy).
                held = held_reason([mod.SOURCE], it.url) is not None
                if _capture.land(
                        mod.SOURCE, url=it.url, title=ex.title, text=ex.text,
                        author=ex.author, published_at=pub,
                        categories=ex.categories, raw=raw_bytes,
                        upstream_id=upstream, fetch_mode=fetch_mode,
                        pipeline_status=("for_review" if parked
                                         else "held" if held else "ingested")):
                    stats["landed"] += 1
                else:
                    stats["dup_content"] += 1
            except Exception as e:  # noqa: BLE001
                print(f"  error {it.url}: {type(e).__name__}: {e}")
                stats["errors"] += 1
            await asyncio.sleep(polite)
    for line in reconcile(stats):
        print(f"  COUNT MISMATCH {mod.SOURCE}: {line}")
    return stats


def reconcile(stats: dict) -> list[str]:
    """The run's counting identities (audit A22). Empty = every discovered
    item is accounted for in exactly one bucket:
      discovered = skipped_seen + already_held + limit_cut + auth_skip + fetched + errors
      fetched    = thin + dup_content + landed
      (already_held = URLs the estate/MCP corpora hold — skipped by rule)
    (a feed error counts in `errors` before discovery, so errors may exceed
    the per-item count by the number of failed feeds — hence ≥ on the first.)"""
    g = lambda k: int(stats.get(k, 0))  # noqa: E731
    out = []
    lhs = g("discovered")
    rhs = (g("skipped_seen") + g("already_held") + g("limit_cut") + g("auth_skip")
           + g("fetched") + g("errors"))
    if rhs < lhs:
        out.append(f"discovered {lhs} > accounted {rhs} (seen+cut+auth_skip+fetched+errors) — an uncounted drop")
    if g("fetched") != g("thin") + g("dup_content") + g("landed"):
        out.append(f"fetched {g('fetched')} != thin {g('thin')} + dup {g('dup_content')} + landed {g('landed')}")
    return out
