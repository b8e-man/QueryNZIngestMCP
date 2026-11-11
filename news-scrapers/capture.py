"""capture — the landing adapter (house capture convention).

The archive's land_document target (querynz.ingestion -> the retired v2
Postgres backlog) is not in this checkout. Per the data-gathering rule
(raw + notes only — transform is a later step), captures land as:

    <root>/<source>/manifest.jsonl        the landing log — one row per unique
                                          capture, idempotent on sha256/url
    <root>/<source>/store/<aa>/<sha256>   raw bytes as served (browser/batch
                                          sources store the returned HTML;
                                          fetch_mode says which)
    <root>/<source>/extracted.jsonl       the extract stage (title/text/...) —
                                          kept separate from capture

Row field names (sha256 / names / urls / kind / file / fetched_at / landed_at)
match the estate corpus manifests, so a source directory can be mounted in the
ingest MCP later without reshaping. seen_refs() reads the same manifest for
base.run_source's pre-fetch dedup — no separate state file to drift.

A landing run is one sequential sweep; appends are safe within it. Re-runs
land nothing twice (contract 1's idempotency, kept).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("NEWS_CAPTURE_ROOT", "/opt/data/news-scrapers/data"))

_HELD: dict[str, tuple[set[str], set[str]]] = {}  # source -> (sha set, url set)


def _manifest(source: str) -> Path:
    return ROOT / source / "manifest.jsonl"


def _held(source: str) -> tuple[set[str], set[str]]:
    if source not in _HELD:
        shas: set[str] = set()
        urls: set[str] = set()
        p = _manifest(source)
        if p.exists():
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    shas.add(row.get("sha256", ""))
                    for u in row.get("urls", []):
                        urls.add(u.get("url", "") if isinstance(u, dict) else str(u))
        _HELD[source] = (shas, urls)
    return _HELD[source]


def _read_jsonl(path: str):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    except OSError:
        return


# ── holdings check (Arthur, 2026-11-09: "only land what the claude estate
# doesn't hold") ──────────────────────────────────────────────────────────
# What the estate holds = every URL in its manifests
# (/opt/data/querynz-estate/sources/*/manifest.jsonl — the 21 estate-*
# corpora). The MCP's beehive corpus counts too: beehive-scraper is the
# byte-for-byte holder there and the registry's beehive module must not
# double-land it. Land only what NONE of them holds.

_HELD_URLS: set[str] | None = None


def _held_urls() -> set[str]:
    global _HELD_URLS
    if _HELD_URLS is None:
        held: set[str] = set()
        for mf in glob.glob("/opt/data/querynz-estate/sources/*/manifest.jsonl"):
            for row in _read_jsonl(mf):
                for u in row.get("urls") or []:
                    if isinstance(u, dict):
                        if u.get("url"):
                            held.add(u["url"])
                    elif u:
                        held.add(str(u))
        # the MCP's beehive corpus — captured by beehive-scraper (the holder)
        for row in _read_jsonl("/opt/data/beehive-scraper/done.jsonl"):
            if row.get("url"):
                held.add(row["url"])
        _HELD_URLS = held
    return _HELD_URLS


def already_held(url: str) -> bool:
    """True when the estate (or an existing MCP corpus) already holds this
    URL — such a record is counted `already_held` and never lands here."""
    return url in _held_urls()


def seen_refs(source: str, refs: list[str]) -> set[str]:
    """Subset of `refs` (urls) this source already holds — pre-fetch dedup."""
    _, urls = _held(source)
    return {r for r in refs if r in urls}


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def land(source: str, *, url: str, title: str | None, text: str,
         author: str | None, published_at, categories: list[str],
         raw: bytes | None, upstream_id: int, fetch_mode: str,
         pipeline_status: str) -> bool:
    """One capture -> store bytes + manifest row + extracted row.
    Returns False (writing nothing) when the source already holds these bytes
    (sha256) or this url — idempotent on re-runs."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if raw is None:
        raw = (text or "").encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    shas, urls = _held(source)
    if sha in shas or url in urls:
        return False
    d = ROOT / source
    (d / "store" / sha[:2]).mkdir(parents=True, exist_ok=True)
    store_path = d / "store" / sha[:2] / sha
    store_path.write_bytes(raw)
    row = {
        "sha256": sha,
        "source": source,
        "kind": "article",
        "names": [title] if title else [],
        "urls": [{"url": url}],
        "file": str(store_path),
        "fetched_at": now,
        "landed_at": now,
        "published_at": _iso(published_at),
        "author": author,
        "upstream_id": upstream_id,
        "chars": len(text or ""),
        "fetch_mode": fetch_mode,
        "pipeline_status": pipeline_status,
    }
    with _manifest(source).open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shas.add(sha)
    urls.add(url)
    with (d / "extracted.jsonl").open("a") as f:
        f.write(json.dumps({
            "sha256": sha, "url": url, "title": title, "text": text,
            "author": author, "published_at": _iso(published_at),
            "categories": categories or [], "extracted_at": now,
        }, ensure_ascii=False) + "\n")
    return True
