#!/usr/bin/env python3
"""Beehive.govt.nz forward collector — zero-LLM, stdlib-only, VPS-safe.

Captures from launch forward (no backfill):
  * every new item: rss.xml (all-site) + speeches/feed + features/feed + sitemap tail
  * every page edit: sitemap lastmod diff (catches silent updates, e.g. Post-Cabinet
    transcripts whose feed date never changes)

Transport findings (2026-10-21, see README):
  * feed + sitemap XML endpoints: OK direct with a browser User-Agent
  * HTML page endpoints: JS-challenged from all datacenter fetchers (Incapsula).
    Bodies are therefore QUEUED to pending_pages.jsonl for Tier-2 capture
    (home-IP fetcher or authenticated Wayback SPN — see README).

Data conventions: raw only, no transformation. Every record appended to
manifest.jsonl; feed/sitemap XML snapshots saved under data/raw/.

Exit semantics (cron no_agent):
  * success -> empty stdout, exit 0 (silent)
  * source failure after retries -> exit 1 (scheduler raises an error alert)
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

BASE = os.environ.get("BEEHIVE_BASE", "/opt/data/beehive-scraper")
RAW = os.path.join(BASE, "data", "raw")
LOGS = os.path.join(BASE, "logs")
STATE_F = os.path.join(BASE, "state.json")
MANIFEST_F = os.path.join(BASE, "manifest.jsonl")
QUEUE_F = os.path.join(BASE, "pending_pages.jsonl")

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
# WAF allowlist on beehive.govt.nz (datacenter IPs): only /rss.xml and
# /sitemap.xml* are served; */feed and HTML pages are JS-challenged. So:
REQUIRED_FEEDS = {
    "all": "https://www.beehive.govt.nz/rss.xml",
}
# Optional depth sources: best-effort, single attempt, NEVER hard-fail.
# (Going-forward coverage does not depend on them: every new item appears in
# rss.xml's 30-item window for ~9 days, and the sitemap tail backstops roll-off.)
OPTIONAL_FEEDS = {
    "speeches": "https://www.beehive.govt.nz/speeches/feed",
    "features": "https://www.beehive.govt.nz/features/feed",
}
SITEMAP_INDEX = "https://www.beehive.govt.nz/sitemap.xml"
TAIL_PAGES = 2          # sitemap pages diffed for new items + edits
FRESH_HOURS = 48        # sitemap-only URLs older than this are archive -> no capture
RETRIES = 3
RETRY_SLEEP = 5
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
CHALLENGE_MARKERS = (b"_Incapsula_Resource", b"Incapsula incident", b"SWUDNSAI",
                     b"SWJIYLWA", b"Request unsuccessful", b"distil_referrer")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-NZ,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_xml(url):
    """Fetch an XML endpoint with retries. Returns bytes or None (never raises)."""
    for _ in range(RETRIES):
        body = None
        try:
            body = http_get(url)
        except Exception:
            pass
        if body and not any(m in body[:2048] for m in CHALLENGE_MARKERS):
            return body
        time.sleep(RETRY_SLEEP)
    return None


def http_get_or_none(url):
    """Single attempt, no retries. Returns bytes or None (never raises)."""
    try:
        return http_get(url)
    except Exception:
        return None


def parse_feed(xml_bytes):
    """RSS items: url, title, raw pubDate, teaser description. Raw strings only."""
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        if not link:
            continue
        items.append({
            "url": link,
            "title": (it.findtext("title") or "").strip(),
            "pub_date": (it.findtext("pubDate") or "").strip(),
            "description": (it.findtext("description") or "").strip()[:400],
        })
    return items


def parse_sitemap_index(xml_bytes):
    root = ET.fromstring(xml_bytes)
    return [(s.findtext(SITEMAP_NS + "loc") or "").strip()
            for s in root.iter(SITEMAP_NS + "sitemap")]


def parse_urlset(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = {}
    for u in root.iter(SITEMAP_NS + "url"):
        loc = (u.findtext(SITEMAP_NS + "loc") or "").strip()
        if loc:
            out[loc] = (u.findtext(SITEMAP_NS + "lastmod") or "").strip()
    return out


def item_type(url):
    for t in ("release", "speech", "feature"):
        if f"/{t}/" in url:
            return t
    return "page"


def load_state():
    try:
        with open(STATE_F) as f:
            return json.load(f)
    except Exception:
        return {"seen": {}, "lastmod": {}, "runs": 0, "consecutive_errors": 0,
                "last_success": None, "last_error": None, "totals": {}}


def save_snap(name, body, now):
    d = os.path.join(RAW, now.strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{now.strftime('%H%M%S')}-{name}.xml")
    with open(path, "wb") as f:
        f.write(body)
    return path


def main():
    now = now_utc()
    state = load_state()
    errors = []
    manifest_lines = []
    queue_lines = []
    counts = {"new_items": 0, "edits": 0}

    for d in (RAW, LOGS):
        os.makedirs(d, exist_ok=True)

    # queue dedupe: don't re-queue URLs already pending
    queued = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    queued.add(json.loads(line)["url"])
                except Exception:
                    pass

    def record(kind, url, meta):
        """One manifest record + (for capturable kinds) one body-capture queue entry."""
        counts["new_items" if kind == "item" else "edits"] += 1
        manifest_lines.append({
            "ts": iso(now), "kind": kind, "url": url, "type": item_type(url),
            "title": meta.get("title", ""), "pub_date": meta.get("pub_date", ""),
            "lastmod": meta.get("lastmod", ""),
            "description": meta.get("description", ""),
            "source": meta.get("source", ""),
        })
        if url not in queued:
            queued.add(url)
            queue_lines.append({"url": url, "kind": kind, "queued_at": iso(now),
                                "reason": meta.get("source", "sitemap")})

    # ---- 1. feeds: every new item -------------------------------------
    notes = []
    for name, url in list(REQUIRED_FEEDS.items()) + list(OPTIONAL_FEEDS.items()):
        required = name in REQUIRED_FEEDS
        body = fetch_xml(url) if required else http_get_or_none(url)
        if body is None or any(m in body[:2048] for m in CHALLENGE_MARKERS):
            if required:
                errors.append(f"feed {name} unreachable/challenged after {RETRIES} tries")
            else:
                notes.append(f"optional feed {name} unavailable (WAF-challenged)")
            continue
        save_snap(f"feed-{name}", body, now)
        try:
            items = parse_feed(body)
        except Exception as e:
            if required:
                errors.append(f"feed {name} parse error: {e}")
            else:
                notes.append(f"optional feed {name} parse error: {e}")
            continue
        for it in items:
            if it["url"] in state["seen"]:
                continue
            state["seen"][it["url"]] = iso(now)
            it["source"] = name
            record("item", it["url"], it)

    # ---- 2. sitemap tail: new items (incl. backdated inserts) + edits --
    idx = fetch_xml(SITEMAP_INDEX)
    if idx is None:
        errors.append("sitemap index unreachable/challenged")
    else:
        save_snap("sitemap-index", idx, now)
        try:
            pages = parse_sitemap_index(idx)[-TAIL_PAGES:]
        except Exception as e:
            errors.append(f"sitemap index parse error: {e}")
            pages = []
        cutoff = now - timedelta(hours=FRESH_HOURS)
        for p in pages:
            b = fetch_xml(p)
            if b is None:
                errors.append(f"sitemap page unreachable: {p}")
                continue
            save_snap("sitemap-" + p.rstrip("/").split("=")[-1], b, now)
            try:
                urlset = parse_urlset(b)
            except Exception as e:
                errors.append(f"sitemap page parse error {p}: {e}")
                continue
            for u, lm in urlset.items():
                prev = state["lastmod"].get(u)
                if prev is None:
                    state["lastmod"][u] = lm
                    if u not in state["seen"]:
                        # archive URL (old lastmod) = mark seen, skip capture
                        fresh = False
                        try:
                            fresh = bool(lm) and datetime.fromisoformat(lm) >= cutoff
                        except Exception:
                            fresh = False
                        if fresh:
                            state["seen"][u] = iso(now)
                            record("item", u, {"lastmod": lm, "source": "sitemap"})
                elif prev != lm:
                    state["lastmod"][u] = lm
                    record("edit", u, {"lastmod": lm, "source": "sitemap"})

    # ---- 3. persist ----------------------------------------------------
    if manifest_lines:
        with open(MANIFEST_F, "a") as f:
            for m in manifest_lines:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
    if queue_lines:
        with open(QUEUE_F, "a") as f:
            for q in queue_lines:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")

    state["runs"] += 1
    state["last_attempt"] = iso(now)
    if errors:
        state["consecutive_errors"] += 1
        state["last_error"] = "; ".join(errors)[:500]
    else:
        state["consecutive_errors"] = 0
        state["last_success"] = iso(now)
        state["last_error"] = None
    state["totals"] = {
        "items": state["totals"].get("items", 0) + counts["new_items"],
        "edits": state["totals"].get("edits", 0) + counts["edits"],
    }
    with open(STATE_F, "w") as f:
        json.dump(state, f, ensure_ascii=False)

    with open(os.path.join(LOGS, "collect.log"), "a") as f:
        f.write(f"{iso(now)} items={counts['new_items']} edits={counts['edits']} "
                f"errors={len(errors)} seen={len(state['seen'])} "
                f"queued_total={len(queued)}"
                f"{' ERR: ' + '; '.join(errors) if errors else ''}"
                f"{' NOTE: ' + '; '.join(notes) if notes else ''}\n")

    if errors:
        print(f"beehive collector FAILED: {'; '.join(errors)}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
