#!/usr/bin/env python3
"""backfill_gap — slow, polite back-fill collector for the estate-news gap audit.

Reply to request estate-news-gaps@2026-11-21 (message out-73317b06d0a8da41,
posted 2026-11-24). Three lanes, one script, shared rate limiter:

  lane 1  old-only address waves (CSV state "old only", never not_collectable)
          wave 1 party sites + action./assets./shop./cdn./merch. + shared
                 asset hosts   (first landings committed 2026-11-26)
          wave 2 agencies             (first landings committed 2026-11-28)
          wave 3 remaining            (first landings committed 2026-11-30)
  lane 2  date-hole backwalks — enumerate via sitemap/wayback then fetch:
          constructionnews.co.nz 2026-08-20..2026-11-20
          thespinoff.co.nz       2026-10-04..2026-11-06
          worksafe.govt.nz       2026-10-30..2026-11-16
          nzier.org.nz           2026-11-02..2026-11-18
                                        (first landings committed 2026-11-27)
  lane 3  undated-coverage walk-backs — CSV state "providing, gap" hosts
          plus motu-www.motu.org.nz (maps to motu.org.nz)
                                        (first landings committed 2026-11-28)

Contract (from the collect ask, binding):
  * every address fetched WHOLE and kept as fetched: bytes on disk, address,
    fetch time, sha256 of the bytes, HTTP status, content type, length,
    last-modified/ETag if present, final address after redirects. Nothing is
    extracted into fields. Landing rows carry the listing-page reference where
    one exists and both metadata blocks (site-stated + response-stated).
  * dedupe: addresses compare without tracking parameters, fragments, scheme,
    host case and trailing slash; one document behind several addresses is one
    record (sha256 of the bytes as fetched decides identity). Anything whose
    sha256 is already in the store is skipped.
  * every failed read (challenge / challenge page / error / robots-disallowed)
    appends one gap-ledger row per gap, ever, per source, and is never
    re-fetched in the same run. A challenge lists a gap and moves on. A listed
    URL is never re-hammered.
  * a host that refuses reads (403/challenge) is recorded and left alone —
    no proxies, no login, no routing around a block.
  * pacing: one request at a time, ~2.5 s minimum between requests to the
    same host, robots crawl-delay honoured when larger. Lanes share one
    limiter so a host is never parallel-hammered.

State: /opt/data/news-scrapers/data-backfill/.state.jsonl — one cursor row per
(lane, host). Landings follow the house capture convention (ingestion/
capture.py): <DATA>/<source>/manifest.jsonl + store/<aa>/<sha256>.

The daily tick wrapper (scripts/backfill_gap_tick.sh) runs this with a small
bounded budget (default 120 addresses/tick); nothing is scheduled from here.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import OrderedDict
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
CSV_PATH = Path("/opt/data/qnz-mcp/channel/attachments/"
                "b84186ca367b08365297e06fa97ecf55eefabcee58ab20a37a30d19517103aaa")
REPLY_BODY = Path("/opt/data/querynz-estate/gap-audit-2026-11-21/reply-body.json")
DATA_ROOT = Path("/opt/data/news-scrapers/data")
STATE_DIR = Path("/opt/data/news-scrapers/data-backfill")
STATE_FILE = STATE_DIR / ".state.jsonl"
ROBOTS_DIR = STATE_DIR / "robots"
GAP_LEDGER = Path("/opt/data/querynz-estate/gaps/backfill_gap_ledger.jsonl")

REQUEST_ID = "estate-news-gaps@2026-11-21"
UA = ("news-scrapers-backfill/1.0 (estate-news back-fill; slow polite collector; "
      "per-host pacing; robots honoured)")

# lane start dates — the daily tick makes the committed dates real
LANE_START = {
    "w1": dt.date(2026, 11, 24),   # wave 1 — land from now for the 11-26 commit
    "w2": dt.date(2026, 11, 26),   # wave 2 — first landings 2026-11-28
    "w3": dt.date(2026, 11, 28),   # wave 3 — first landings 2026-11-30
    "holes": dt.date(2026, 11, 26),  # lane 2 — first landings 2026-11-27
    "undated": dt.date(2026, 11, 27),  # lane 3 — first landings 2026-11-28
}
HOST_MIN_INTERVAL = 2.5       # s between requests to the same host
GLOBAL_MIN_INTERVAL = 0.4     # s between any two requests (one global limiter)
ROBOTS_TTL = 7 * 86400        # re-read robots.txt weekly
ROBOTS_BLOCK_RECHECK = 3 * 86400  # re-diagnose a robots-blocked host every 3 d
FETCH_TIMEOUT = 30
MAX_SITEMAPS_PER_HOST = 20
MAX_QUEUE_PER_HOLE = 5000

CHALLENGE_MARKS = (
    "just a moment", "cf-browser-verification", "cf_chl", "challenge-platform",
    "attention required", "ddos protection", "incapsula", "captcha",
    "request unsuccessful",
)
META_ALLOW = {
    "last-modified", "date", "article:published_time", "article:modified_time",
    "og:updated_time", "pubdate", "dc.date",
}

TODAY = dt.date.today()


# ── small helpers ────────────────────────────────────────────────────────────
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def url_key(url: str) -> str:
    """Canonical address key: no scheme, no fragment, lowercase host, no
    trailing slash, tracking parameters stripped."""
    s = urllib.parse.urlsplit(url.strip())
    host = s.netloc.lower()
    path = s.path or "/"
    path = path.rstrip("/") or "/"
    q = [(k, v) for k, v in urllib.parse.parse_qsl(s.query, keep_blank_values=True)
         if not k.lower().startswith(("utm_", "fbclid", "gclid", "mc_", "ref", "ref_src"))]
    return f"{host}{path}" + (("&" + urllib.parse.urlencode(sorted(q))) if q else "")


def source_for(host: str) -> str:
    """Landing source dir. motu-www.motu.org.nz is the same site as
    motu.org.nz (same_site_mapping) and lands under the real host."""
    if host == "motu-www.motu.org.nz":
        return "motu.org.nz"
    return host


def wave_label(lane: str) -> str:
    return {"w1": "wave 1", "w2": "wave 2", "w3": "wave 3",
            "holes": "date-hole", "undated": "undated-coverage"}.get(lane, lane)


# ── reply-body.json — wave plans, not_collectable, hole list, undated hosts ──
def load_plan() -> dict:
    body = json.loads(REPLY_BODY.read_text())
    sec_old = next(s for s in body["sections"] if s["section"] == "old-only-backfill")
    sec_holes = next(s for s in body["sections"] if s["section"] == "date-holes")
    sec_undated = next(s for s in body["sections"] if s["section"] == "undated-coverage")
    not_collectable = {e["host"]: e.get("reason", "") for e in sec_old["not_collectable"]}
    waves = []  # [(wave_key, [host,...] most-addresses-first)]
    for w in sec_old["waves"]:
        hosts = [h["host"] for h in sorted(w["hosts"], key=lambda h: -h["addresses"])]
        waves.append((f"w{w['wave']}", hosts))
    holes = [(h["host"], h["from"], h["to"]) for h in sec_holes["holes"]]
    undated = [h["host"] for h in sec_undated["hosts"]]
    if "motu-www.motu.org.nz" not in undated:
        undated.append("motu-www.motu.org.nz")
    return {"not_collectable": not_collectable, "waves": waves,
            "holes": holes, "undated": undated}


# ── address CSV ──────────────────────────────────────────────────────────────
def load_csv() -> dict[str, list[str]]:
    """host -> [url, ...] in CSV order, states 'old only' + 'providing, gap'."""
    per_host: dict[str, list[str]] = {}
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            per_host.setdefault(row["host"].strip().lower(), []).append(row["url"].strip())
    return per_host


# ── state (one cursor row per lane/host) ─────────────────────────────────────
def load_state() -> dict:
    state: dict = {}
    if STATE_FILE.exists():
        for line in STATE_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                state[row["key"]] = row
    return state


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        for row in state.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(STATE_FILE)


def cursor(state: dict, key: str, kind: str) -> dict:
    if key not in state:
        state[key] = {"key": key, "kind": kind, "next": 0, "done": [],
                      "updated_at": now_iso()}
        if kind == "holes":
            state[key].update({"enum": "pending", "queue": []})
    return state[key]


def mark_done(cur: dict, key: str) -> None:
    cur["done"].append(key)
    cur["updated_at"] = now_iso()


# ── gap ledger (one row per gap, ever, per source) ───────────────────────────
def load_ledger_keys() -> set:
    keys: set = set()
    if GAP_LEDGER.exists():
        for line in GAP_LEDGER.read_text().splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                keys.add(url_key(row.get("url", "")))
    return keys


def gap_row(source: str, url: str, reason: str, status, note: str | None = None) -> dict:
    return {"source": source, "url": url, "reason": reason, "status": status,
            "at": now_iso(), "note": note}


class Gaps:
    def __init__(self) -> None:
        self.seen = load_ledger_keys()
        self.pending: list[dict] = []

    def add(self, source: str, url: str, reason: str, status,
            note: str | None = None) -> bool:
        k = url_key(url)
        if k in self.seen:
            return False  # one row per gap, ever
        self.seen.add(k)
        self.pending.append(gap_row(source, url, reason, status, note))
        return True

    def flush(self) -> None:
        if not self.pending:
            return
        GAP_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with GAP_LEDGER.open("a") as f:
            for row in self.pending:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.pending = []


# ── store holdings (sha256 identity + held addresses) ────────────────────────
def load_held() -> tuple[set, dict[str, set]]:
    """One pass over the estate manifests: (held shas, held url_keys per
    source). Addresses compare without tracking parameters, fragments,
    scheme, host case and trailing slash (held_list_semantics)."""
    shas: set = set()
    url_keys: dict[str, set] = {}
    for mf in DATA_ROOT.glob("*/manifest.jsonl"):
        src = mf.parent.name
        keys = url_keys.setdefault(src, set())
        try:
            for line in mf.read_text().splitlines():
                if '"sha256"' not in line and '"urls"' not in line:
                    continue
                row = json.loads(line)
                if row.get("sha256"):
                    shas.add(row["sha256"])
                for u in row.get("urls") or []:
                    if isinstance(u, dict):
                        u = u.get("url")
                    if u:
                        keys.add(url_key(u))
        except (OSError, json.JSONDecodeError):
            continue
    return shas, url_keys


# ── global rate limiter (shared by all lanes) ────────────────────────────────
class Limiter:
    def __init__(self) -> None:
        self.last_by_host: dict[str, float] = {}
        self.last_any = 0.0
        self.crawl_delays: dict[str, float] = {}

    def wait(self, host: str) -> None:
        now = time.monotonic()
        delay = max(HOST_MIN_INTERVAL, self.crawl_delays.get(host, 0.0))
        last = self.last_by_host.get(host, 0.0)
        sleep_for = max(delay - (now - last),
                        GLOBAL_MIN_INTERVAL - (now - self.last_any), 0.0)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self.last_by_host[host] = time.monotonic()
        self.last_any = time.monotonic()

    def note_crawl_delay(self, host: str, seconds: float | None) -> None:
        if seconds and seconds > 0:
            self.crawl_delays[host] = min(float(seconds), 30.0)


# ── direct fetch (no proxy, no login — a block is a block) ───────────────────
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(url: str, lim: Limiter, host: str):
    """One polite GET. Returns (status, headers, bytes, final_url, err).
    status is None on transport failure; err carries the reason."""
    lim.wait(host)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip",
    })
    try:
        with _OPENER.open(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            return resp.status, resp.headers, raw, resp.geturl(), None
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(65536)
        except Exception:
            pass
        return e.code, e.headers, body, getattr(e, "url", url), None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return None, None, b"", url, str(e)


def looks_like_challenge(raw: bytes) -> bool:
    head = raw[:8192].lower()
    return any(m.encode() in head for m in CHALLENGE_MARKS)


# ── the ruled browser lane (Arthur, 2026-11-25) ─────────────────────────────
# worksafe.govt.nz serves the wall on every path (robots.txt included) to this
# runtime's egress identity; the shared browser lane (newsscrapers.browserfetch
# → render_all, IPRoyal session via its proxies opt-in) reads it fine. A lift
# case-by-case on Arthur's go — reviewed 2026-11-26.
BROWSER_HOSTS = {"worksafe.govt.nz"}


def browser_get(url: str, source: str):
    """One address through the shared browser lane. Returns (status, raw
    bytes, final_url, err). The bytes are the rendered DOM — the raw server
    response on this host is an 843-byte JS shell with no text (measured
    2026-11-25); land() records the render fetch_mode for honesty."""
    import asyncio
    try:
        from newsscrapers import browserfetch
        pairs = asyncio.run(browserfetch.render_all([url], source=source))
    except Exception as e:  # noqa: BLE001 — a failed read is a gap, not a crash
        return None, b"", url, f"{type(e).__name__}: {e}"
    if not pairs:
        return None, b"", url, "challenged or empty from the browser lane"
    return 200, pairs[0][1].encode("utf-8"), url, None


# ── robots.txt (one cached read per host; crawl-delay honoured) ──────────────
def ensure_robots(host: str, lim: Limiter, state: dict, gaps: Gaps) -> dict:
    """Fetch robots.txt once per host (cached in state with a TTL), store the
    parsed verdict + rules + crawl-delay. State keys for f'robots:{host}':
      verdict: allow | blocked | down
      rules:   raw robots lines for per-URL can_fetch
      crawl_delay: seconds (from robots, capped at 30)
    A host that refuses robots reads is 'blocked' — recorded once, never
    routed around, re-diagnosed at most every 3 days."""
    host_state = state.get(f"robots:{host}")
    now = time.time()
    if host_state:
        age = now - host_state.get("ts", 0)
        ttl = ROBOTS_BLOCK_RECHECK if host_state.get("verdict") == "blocked" \
            else (86400 if host_state.get("verdict") == "down" else ROBOTS_TTL)
        if age < ttl:
            return host_state
    url = f"https://{host}/robots.txt"
    status, _h, raw, _f, err = http_get(url, lim, host)
    entry = {"key": f"robots:{host}", "ts": now, "updated_at": now_iso()}
    if status is None:
        entry.update(verdict="down", note=err)
    elif status in (401, 403) or (status == 200 and looks_like_challenge(raw)):
        entry.update(verdict="blocked", status=status)
        gaps.add(host, url, "challenge", status,
                 note="robots.txt refused reads — host not routed around")
    elif status == 200:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(raw.decode("utf-8", "replace").splitlines())
        delay = rp.crawl_delay(UA) or rp.crawl_delay("*")
        if delay and delay > 0:
            entry["crawl_delay"] = min(float(delay), 30.0)
        entry.update(verdict="allow",
                     rules=raw.decode("utf-8", "replace").splitlines()[:4000])
    else:  # 404 etc — no robots restrictions known
        entry.update(verdict="allow")
    state[f"robots:{host}"] = entry
    if entry.get("crawl_delay"):
        lim.crawl_delays[host] = entry["crawl_delay"]
    return entry


# ── landing (house capture convention) ───────────────────────────────────────
META_RE = re.compile(
    r"<meta[^>]+(?:name|property|http-equiv)\s*=\s*[\"']([^\"']+)[\"']"
    r"[^>]*content\s*=\s*[\"']([^\"']*)[\"']", re.I)
META_RE2 = re.compile(
    r"<meta[^>]+content\s*=\s*[\"']([^\"']*)[\"']"
    r"[^>]*(?:name|property|http-equiv)\s*=\s*[\"']([^\"']+)[\"']", re.I)


def site_stated_meta(raw: bytes) -> dict:
    """The site-stated metadata block: raw meta name/content pairs from the
    document head, allowlisted keys, uninterpreted (extract nothing)."""
    head = raw[:65536].decode("utf-8", "replace")
    out: dict[str, str] = {}
    for rx in (META_RE, META_RE2):
        for name, content in rx.findall(head):
            k = name.strip().lower()
            if k in META_ALLOW and k not in out:
                out[k] = content
    return out


def land(source: str, url: str, raw: bytes, status: int, headers,
         final_url: str, listing_ref: str | None, lane: str, wave,
         held_shas: set, fetch_mode: str = "backfill") -> str:
    """Store bytes + manifest row. Returns 'landed' | 'dupe'."""
    sha = hashlib.sha256(raw).hexdigest()
    if sha in held_shas:
        return "dupe"
    d = DATA_ROOT / source
    (d / "store" / sha[:2]).mkdir(parents=True, exist_ok=True)
    store_path = d / "store" / sha[:2] / sha
    if not store_path.exists():
        store_path.write_bytes(raw)
    ct = (headers.get("Content-Type") if headers else None)
    clen = headers.get("Content-Length") if headers else None
    lm = headers.get("Last-Modified") if headers else None
    etag = headers.get("ETag") if headers else None
    response_stated = {"status": status, "content_type": ct,
                       "content_length": int(clen) if clen and clen.isdigit() else clen,
                       "last_modified": lm, "etag": etag,
                       "final_url": final_url, "fetched_at": now_iso()}
    row = {
        "sha256": sha, "source": source, "kind": "article", "names": [],
        "urls": [{"url": url}], "file": str(store_path),
        "fetched_at": response_stated["fetched_at"],
        "landed_at": response_stated["fetched_at"],
        "published_at": None, "author": None, "upstream_id": None,
        "chars": len(raw), "fetch_mode": fetch_mode, "pipeline_status": "captured",
        "capture": {"status": status, "content_type": ct,
                    "content_length": response_stated["content_length"],
                    "last_modified": lm, "etag": etag, "final_url": final_url,
                    "listing_ref": listing_ref},
        "meta": {"site_stated": site_stated_meta(raw),
                 "response_stated": response_stated},
        "backfill": {"lane": lane, "wave": wave, "request": REQUEST_ID,
                     "url_key": url_key(url)},
    }
    with (d / "manifest.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    held_shas.add(sha)
    return "landed"


# ── one address fetch-or-gap ─────────────────────────────────────────────────
def fetch_address(host: str, url: str, lim: Limiter, gaps: Gaps, state: dict,
                  held_shas: set, listing_ref: str | None,
                  lane: str, wave: str, self_held_keys: dict[str, set] | None = None,
                  ) -> str:
    """Returns 'landed' | 'dupe' | 'gap'. Never re-fetches a listed URL in
    the same run; a challenge lists a gap and moves on."""
    source = source_for(host)
    if url_key(url) in self_held_keys.get(source, set()):
        return "dupe"  # address already held (one record per address)
    if host in BROWSER_HOSTS:
        # robots.txt is behind the same wall (unreadable) — Arthur's
        # browser-lane ruling 2026-11-25 governs this host; the Limiter
        # still paces it.
        lim.wait(host)
        status, raw, final_url, err = browser_get(url, source)
        if status is None:
            gaps.add(source, url, "challenge", 0,
                     note=err or "browser lane refused")
            return "gap"
        return land(source, url, raw, status, None, final_url, listing_ref,
                    lane, wave, held_shas, fetch_mode="backfill-render")
    entry = ensure_robots(host, lim, state, gaps)
    if entry.get("verdict") == "blocked":
        gaps.add(source, url, "challenge", entry.get("status", 403),
                 note="host refuses reads — recorded, not routed around")
        return "gap"
    if entry.get("verdict") == "down":
        gaps.add(source, url, "unreachable", 0,
                 note="host unreachable at robots read")
        return "gap"
    if entry.get("rules"):
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(entry["rules"])
        if not rp.can_fetch(UA, url):
            gaps.add(source, url, "robots_disallowed", 0)
            return "gap"
    status, headers, raw, final_url, err = http_get(url, lim, host)
    if status is None:
        gaps.add(source, url, "unreachable", 0, note=err)
        return "gap"
    if status in (401, 403, 429):
        gaps.add(source, url, "challenge", status)
        return "gap"
    if looks_like_challenge(raw):
        gaps.add(source, url, "challenge", status,
                 note="challenge page served instead of content")
        return "gap"
    if status >= 400:
        gaps.add(source, url, "error", status)
        return "gap"
    if not raw:
        gaps.add(source, url, "error", status, note="empty body")
        return "gap"
    return land(source, url, raw, status, headers, final_url, listing_ref,
                lane, wave, held_shas)


# ── lane 2: enumeration (sitemap → wayback CDX) ──────────────────────────────
SITEMAP_LOC_RE = re.compile(r"<(?:loc|lastmod)>([^<]+)</(?:loc|lastmod)>", re.I)


def parse_sitemap(raw: bytes) -> tuple[list[str], list[tuple[str, str | None]]]:
    """Returns (child_sitemaps, [(url, lastmod|None)]) from one sitemap doc."""
    text = raw.decode("utf-8", "replace")
    if "<sitemapindex" in text.lower():
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text, re.I)
        return locs, []
    urls: list[tuple[str, str | None]] = []
    for block in re.findall(r"<url>(.*?)</url>", text, re.I | re.S):
        m = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block, re.I)
        if not m:
            continue
        lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block, re.I)
        urls.append((m.group(1), lm.group(1) if lm else None))
    if not urls:  # bare <loc> list
        urls = [(u, None) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text, re.I)]
    return [], urls


def enumerate_hole(host: str, d_from: str, d_to: str, lim: Limiter,
                   gaps: Gaps, state: dict) -> tuple[list[dict], str]:
    """Build a dated queue of candidate addresses for one date-hole.
    Returns (queue, ref). Tries sitemaps first, then wayback CDX for
    enumeration only (originals are fetched directly)."""
    # 1. sitemaps, via robots Sitemap: lines then conventional paths
    candidates: list[str] = []
    status, _h, raw, _f, _e = http_get(f"https://{host}/robots.txt", lim, host)
    if status == 200 and not looks_like_challenge(raw):
        for line in raw.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())
    candidates += [f"https://{host}/sitemap.xml",
                   f"https://{host}/sitemap_index.xml",
                   f"https://{host}/wp-sitemap.xml"]
    lo, hi = d_from.replace("-", ""), d_to.replace("-", "")

    def in_range(lastmod: str | None, url: str) -> bool:
        if lastmod:
            m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", lastmod)
            if m:
                ymd = "".join(m.groups())
                return lo[:4] <= ymd[:4] and lo <= ymd <= hi
        m = re.search(r"/(\d{4})/(\d{2})(?:/(\d{2}))?/", url)
        if m:
            ymd = m.group(1) + m.group(2) + (m.group(3) or "00")
            if len(ymd) == 8:
                return lo <= ymd <= hi or (ymd[6:] == "00" and lo[:6] <= ymd[:6] <= hi[:6])
        return False

    queue: list[dict] = []
    seen_urls: set[str] = set()
    tried = 0
    frontier = list(dict.fromkeys(candidates))
    while frontier and tried < MAX_SITEMAPS_PER_HOST and not queue:
        sm = frontier.pop(0)
        tried += 1
        st, _hh, sraw, _ff, _ee = http_get(sm, lim, host)
        if st != 200 or not sraw or looks_like_challenge(sraw):
            continue
        kids, urls = parse_sitemap(sraw)
        frontier.extend(kids[:MAX_SITEMAPS_PER_HOST])
        for u, lm in urls:
            k = url_key(u)
            if k in seen_urls:
                continue
            if in_range(lm, u):
                seen_urls.add(k)
                queue.append({"url": u, "date": lm, "ref": sm})
            if len(queue) >= MAX_QUEUE_PER_HOLE:
                break
    if queue:
        queue.sort(key=lambda e: e.get("date") or "")
        return queue, queue[0]["ref"]
    # 2. wayback CDX — enumeration only
    cdx = ("http://web.archive.org/cdx/search/cdx?"
           + urllib.parse.urlencode({
               "url": f"{host}/*", "from": lo, "to": hi, "fl": "original",
               "collapse": "urlkey", "filter": "statuscode:200",
               "limit": MAX_QUEUE_PER_HOLE, "output": "json"}))
    st, _hh, craw, _ff, _ee = http_get(cdx, lim, "web.archive.org")
    if st == 200 and craw:
        try:
            rows = json.loads(craw)
            for r in rows[1:]:
                u = r[0] if isinstance(r, list) else r
                k = url_key(u)
                if k not in seen_urls:
                    seen_urls.add(k)
                    queue.append({"url": u, "date": None, "ref": "wayback-cdx"})
        except (json.JSONDecodeError, IndexError, TypeError):
            pass
    return queue, ("wayback-cdx" if queue else "none")


# ── lane drivers ─────────────────────────────────────────────────────────────
class Runner:
    def __init__(self, budget: int, only_lane: str | None, smoke: bool,
                 dry: bool, ignore_dates: bool) -> None:
        self.budget = budget
        self.only_lane = only_lane
        self.smoke = smoke
        self.dry = dry
        self.ignore_dates = ignore_dates
        self.lim = Limiter()
        self.state = load_state()
        self.gaps = Gaps()
        self.held_shas, self.held_keys = (set(), {}) if dry else load_held()
        self.plan = load_plan()
        self.csv_hosts = load_csv()  # always loaded; dry just never fetches
        self.tally = {"landed": 0, "dupe": 0, "gap": 0, "skipped": 0}
        self.lane_notes: list[str] = []

    def eligible(self, lane: str) -> bool:
        if self.only_lane and lane != self.only_lane:
            return False
        if self.ignore_dates or self.smoke:
            return True
        return TODAY >= LANE_START.get(lane, dt.date(2026, 12, 31))

    def budget_left(self) -> int:
        return self.budget - (self.tally["landed"] + self.tally["gap"] + self.tally["dupe"])

    # lane 1 / lane 3 — direct CSV addresses, most-addresses-first
    def run_address_lane(self, lane_keys: list[tuple[str, str]], lane: str) -> None:
        """lane_keys: [(cursor_key, host)] in processing order."""
        for ckey, host in lane_keys:
            if self.budget_left() <= 0:
                return
            if host in self.plan["not_collectable"]:
                continue  # never fetched, ever
            urls = self.csv_hosts.get(host, [])
            if not urls:
                continue
            cur = None if self.dry else cursor(self.state, ckey, "addresses")
            i = cur["next"] if cur else 0
            done_set = set(cur["done"]) if cur else set()
            # fast-forward past work already done in earlier ticks
            while i < len(urls) and url_key(urls[i]) in done_set:
                i += 1
            processed = 0
            while i < len(urls) and (self.dry or self.budget_left() > 0):
                url = urls[i]
                k = url_key(url)
                if cur and k in done_set:
                    i += 1
                    continue
                if self.dry:
                    self.tally["skipped"] += 1
                    done_set.add(k)  # count in-host duplicates once
                else:
                    res = fetch_address(host, url, self.lim, self.gaps, self.state,
                                        self.held_shas, None, lane,
                                        wave_label(lane), self.held_keys)
                    self.tally[res if res in ("landed", "dupe") else "gap"] += 1
                    done_set.add(k)
                    mark_done(cur, k)
                    if res == "landed":
                        # visible to later lanes in the same run (motu-www
                        # runs in wave 3 AND the undated lane)
                        self.held_keys.setdefault(source_for(host), set()).add(k)
                i += 1
                processed += 1
                if processed % 25 == 0 and not self.dry:
                    save_state(self.state)
                    self.gaps.flush()
            if not self.dry:
                cur["next"] = i
                cur["updated_at"] = now_iso()
                if i >= len(urls):
                    cur["complete"] = True
                save_state(self.state)
                self.gaps.flush()

    def lane1(self) -> None:
        for wave_key, hosts in self.plan["waves"]:
            if not self.eligible(wave_key):
                continue
            keys = [(f"{wave_key}:{h}", h) for h in hosts]
            self.run_address_lane(keys, wave_key)
            if self.budget_left() <= 0:
                return

    def lane3(self) -> None:
        if not self.eligible("undated"):
            return
        hosts = [h for h in self.plan["undated"]
                 if h not in self.plan["not_collectable"]]
        keys = [(f"undated:{h}", h) for h in hosts]
        self.run_address_lane(keys, "undated")

    # lane 2 — enumerate then fetch
    def lane2(self) -> None:
        if not self.eligible("holes"):
            return
        for host, d_from, d_to in self.plan["holes"]:
            if self.budget_left() <= 0:
                return
            if host in self.plan["not_collectable"]:
                continue
            if self.dry:
                self.tally["skipped"] += 1
                continue
            cur = cursor(self.state, f"holes:{host}", "holes")
            cur["from"], cur["to"] = d_from, d_to
            if cur.get("enum") != "done":
                queue, ref = enumerate_hole(host, d_from, d_to, self.lim,
                                            self.gaps, self.state)
                cur["queue"] = queue
                cur["enum"] = "done" if queue else "empty"
                cur["ref"] = ref
                cur["next"] = 0
                cur["updated_at"] = now_iso()
                save_state(self.state)
                self.gaps.flush()
                if not queue:
                    continue
            queue = cur.get("queue", [])
            done_set = set(cur["done"])
            i = cur.get("next", 0)
            while i < len(queue) and self.budget_left() > 0:
                entry = queue[i]
                k = url_key(entry["url"])
                if k in done_set:
                    i += 1
                    continue
                res = fetch_address(host, entry["url"], self.lim, self.gaps,
                                    self.state, self.held_shas,
                                    entry.get("ref"), "holes", "date-hole",
                                    self.held_keys)
                self.tally[res if res in ("landed", "dupe") else "gap"] += 1
                mark_done(cur, k)
                i += 1
                if i % 25 == 0:
                    cur["next"] = i
                    save_state(self.state)
                    self.gaps.flush()
            cur["next"] = i
            cur["updated_at"] = now_iso()
            if i >= len(queue):
                cur["complete"] = True
            save_state(self.state)
            self.gaps.flush()

    def run(self) -> dict:
        if self.smoke:
            w1 = self.plan["waves"][0][1]
            self.run_address_lane([(f"w1:{h}", h) for h in w1], "w1")
        else:
            self.lane1()
            self.lane2()
            self.lane3()
        self.gaps.flush()
        save_state(self.state)
        return self.tally


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="estate-news gap back-fill runner")
    ap.add_argument("--budget", type=int, default=120,
                    help="max addresses fetched this tick (default 120)")
    ap.add_argument("--lane", choices=["w1", "w2", "w3", "holes", "undated"],
                    help="restrict to one lane/wave")
    ap.add_argument("--smoke", action="store_true",
                    help="25-address smoke batch from wave 1, date gates off")
    ap.add_argument("--dry", action="store_true",
                    help="plan only — no network, no writes")
    ap.add_argument("--ignore-dates", action="store_true",
                    help="run lanes before their committed start dates")
    args = ap.parse_args(argv)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        args.budget = 25
        args.lane = "w1"
    r = Runner(args.budget, args.lane, args.smoke, args.dry, args.ignore_dates)
    tally = r.run()

    # one summary line, only when something landed or failed
    if tally["landed"] or tally["gap"]:
        parts = [f"landed={tally['landed']}", f"dupes={tally['dupe']}",
                 f"gaps={tally['gap']}"]
        if r.state.get("_last_lane_note"):
            parts.append(r.state["_last_lane_note"])
        print("backfill-gap " + REQUEST_ID + ": " + " ".join(parts))
    elif args.dry:
        print(f"backfill-gap dry plan: would process {tally['skipped']} addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
