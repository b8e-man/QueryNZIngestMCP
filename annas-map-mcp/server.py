#!/usr/bin/env python3
"""Anna's Archive Map — NZ book map over the LibGen compact catalog.

STANDALONE MCP — deliberately NOT part of the Query NZ (qnz) MCP. It is its
own service on its own port; nothing here mounts into qnz-mcp's corpora.

Source: Internet Archive metadata snapshot `libgen-meta-20230113`
(LibGen compact catalog, 2023-01-13), ingested raw with no transformation
(ingest_libgen.py). The NZ map (match_nz.py) is a scored selection where
EVERY match stores the signals that caused it — the filter's decisions are
inspectable, and what it excludes is stated in `stats()`.

Design language (same as qnz-mcp): measurements, not opinions. Signals and
thresholds are recorded per row; statistics report what the map holds and
what the matcher would miss. Nothing is silently dropped.

Transport: MCP Streamable HTTP on 0.0.0.0:8647/mcp.
"""

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "dumps", "libgen.db")
METER_F = os.path.join(BASE, "metering.jsonl")

SOURCE = {
    "name": "libgen-meta-20230113",
    "description": "LibGen compact catalog metadata snapshot",
    "snapshot_date": "2023-01-13",
    "origin": "https://archive.org/download/libgen-meta-20230113/",
    "ingest_note": ("3,600,823 raw parsed rows; 989 malformed rows (parser "
                    "column-list artifacts on multi-statement lines) removed "
                    "in repair; final 3,599,834 = source schema "
                    "AUTO_INCREMENT - 1, contiguous IDs 1..3,599,834."),
    "note": ("Metadata only. The map selects NZ-relevant rows from the "
             "catalog; it does not fetch or serve book content."),
}

# What the matcher sees — reported so consumers know what it would miss.
FILTER_LIMITS = [
    "Coverage is catalog-metadata only (2023-01-13 snapshot; later LibGen "
    "additions are absent).",
    "NZ signal dictionaries are hand-built (publishers, cities, te reo "
    "markers); unlisted NZ publishers/cities only match via title/author.",
    "The map is tiered by evidence: Pass 1 = direct signals (NZ publisher, "
    "'New Zealand' in title, te reo marker, distinctive NZ city); Pass 2 = "
    "exact author match against authors with a repeated NZ publication "
    "footprint (>=2 NZ-published strong rows, person-like names only); "
    "Pass 3 = single-signal rows (one distinctive city or te reo marker). "
    "Filter on Pass for the precision/recall tradeoff you want.",
    "Foreign place names that collide with NZ ones (Nelson, Hamilton, "
    "Canterbury, Thames, Stratford, Eltham...) are weak signals and never "
    "count alone.",
    "Author pass-2 seeds are whole author strings (normalized, exact match "
    "only); one-off NZ authors outside the seed set need a direct signal.",
    "Rows with no metadata signal at all (e.g. NZ author with no NZ marker) "
    "are invisible to the map — the false-negative floor is unknown.",
]

_lock = threading.Lock()
_conn = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        # Tools run in anyio worker threads; all access is serialized
        # behind _lock, so cross-thread use is safe.
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def meter(tool: str, args: dict, n: int, ms: float) -> None:
    try:
        with open(METER_F, "a") as fh:
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": tool, "args": args, "n": n, "ms": round(ms, 1),
            }) + "\n")
    except OSError:
        pass


def _row_out(r, with_signals: bool = True) -> dict:
    d = dict(r)
    if with_signals and "Signals" in d:
        try:
            d["signals"] = json.loads(d.pop("Signals") or "[]")
        except (TypeError, ValueError):
            d["signals"] = []
        d["score"] = d.get("Score")
        d["pass"] = d.get("Pass")
        d.pop("Score", None)
        d.pop("Pass", None)
    d["source"] = SOURCE["name"]
    return d


mcp = MCPServer(
    name="annas-archive-map",
    version="0.1.0",
    instructions=("A map of NZ-relevant books in the LibGen compact catalog "
                  "metadata snapshot (2023-01-13). Every map row carries the "
                  "signals that selected it. `stats()` reports what the map "
                  "holds and what the filter would miss; `search` queries the "
                  "map; `lookup` reads the raw catalog by ID. Metadata only — "
                  "no book content is served."),
)


@mcp.tool()
def stats() -> dict:
    """READ (inventory). What the map holds: catalog row count, mapped row
    count, score histogram, signal-type counts, per-pass counts, and the
    stated limits of the filter (what it would miss). Read this first."""
    t0 = time.time()
    c = db()
    with _lock:
        catalog = c.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        mapped = c.execute("SELECT COUNT(*) FROM nz_map").fetchone()[0]
        by_pass = [dict(r) for r in c.execute(
            "SELECT Pass AS pass, COUNT(*) AS n FROM nz_map GROUP BY Pass")]
        by_score = [dict(r) for r in c.execute(
            "SELECT Score AS score, COUNT(*) AS n FROM nz_map"
            " GROUP BY Score ORDER BY Score DESC")]
        years = c.execute(
            "SELECT MIN(Year), MAX(Year) FROM nz_map"
            " WHERE Year GLOB '[0-9][0-9][0-9][0-9]'").fetchone()
    sig_counts = {}
    for r in c.execute("SELECT Signals FROM nz_map"):
        try:
            for s in json.loads(r[0] or "[]"):
                kind = s.split(":", 1)[0]
                sig_counts[kind] = sig_counts.get(kind, 0) + 1
        except (TypeError, ValueError):
            pass
    meter("stats", {}, mapped, (time.time() - t0) * 1000)
    return {
        "source": SOURCE,
        "catalog_rows": catalog,
        "mapped_rows": mapped,
        "by_pass": by_pass,
        "by_score": by_score,
        "signal_counts": sig_counts,
        "year_range": {"min": years[0], "max": years[1]},
        "filter_limits": FILTER_LIMITS,
        "note": ("Every mapped row carries its `signals`; the map is a "
                 "selection with recorded reasons, not an opinion."),
    }


@mcp.tool()
def search(query: str = "", signal: str = "", min_score: int = 0,
           pass_tier: int = 0, year_from: int = 0, year_to: int = 0,
           cursor: int = 0, limit: int = 50) -> dict:
    """READ (map search). Search the NZ map. `query` matches title/author/
    publisher (substring, case-insensitive); `signal` filters to rows whose
    signals contain a substring (e.g. 'publisher:', 'city:wellington',
    'tereo:'); `min_score` sets the evidence floor; `pass_tier` selects the
    evidence tier (1=direct signals, 2=known NZ author, 3=single signal;
    0=all); `year_from`/`year_to` bound publication year. Results carry
    their signals. `cursor` + `next_cursor` paginate in stable
    score-descending order."""
    t0 = time.time()
    limit = max(1, min(int(limit), 200))
    cursor = max(0, int(cursor))
    where, args = ["1=1"], []
    if query:
        like = "%" + query.replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(Title LIKE ? ESCAPE '\\' OR Author LIKE ? ESCAPE '\\'"
                     " OR Publisher LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    if min_score:
        where.append("Score >= ?")
        args.append(int(min_score))
    if pass_tier:
        where.append("Pass = ?")
        args.append(str(int(pass_tier)))
    if year_from:
        where.append("CAST(Year AS INTEGER) >= ?")
        args.append(int(year_from))
    if year_to:
        where.append("CAST(Year AS INTEGER) <= ?")
        args.append(int(year_to))
    sql = ("SELECT * FROM nz_map WHERE " + " AND ".join(where)
           + " ORDER BY Score DESC, ID ASC LIMIT ? OFFSET ?")
    with _lock:
        rows = [dict(r) for r in db().execute(sql, args + [limit, cursor])]
    out = []
    for r in rows:
        d = _row_out(r)
        if signal and not any(signal in s for s in d.get("signals", [])):
            continue
        out.append(d)
    n = len(out)
    meter("search", {"query": query, "signal": signal}, n,
          (time.time() - t0) * 1000)
    return {"records": out, "cursor": cursor,
            "next_cursor": cursor + n, "limit": limit,
            "note": "Signals on each row record why it is in the map."}


@mcp.tool()
def get(id: int) -> dict:
    """READ (one map row). The full mapped record by catalog ID, with its
    selection signals and source provenance."""
    t0 = time.time()
    with _lock:
        r = db().execute("SELECT * FROM nz_map WHERE ID = ?", (int(id),))
        row = r.fetchone()
    meter("get", {"id": id}, 1 if row else 0, (time.time() - t0) * 1000)
    if not row:
        return {"error": "not in map", "id": id,
                "hint": "Use `lookup` to read the raw catalog row."}
    return {"record": _row_out(dict(row))}


@mcp.tool()
def lookup(id: int) -> dict:
    """READ (raw catalog). The unfiltered catalog row by ID — verification
    path: any row of the 3.6M-row source can be read, mapped or not, with
    no selection applied."""
    t0 = time.time()
    with _lock:
        r = db().execute("SELECT * FROM books WHERE ID = ?", (int(id),))
        row = r.fetchone()
    meter("lookup", {"id": id}, 1 if row else 0, (time.time() - t0) * 1000)
    if not row:
        return {"error": "not in catalog", "id": id}
    return {"record": dict(row), "source": SOURCE["name"],
            "note": "Raw catalog row, unselected."}


@mcp.tool()
def census(field: str = "publisher", limit: int = 50) -> dict:
    """READ (measurement). Value census over the map — `field` one of
    publisher, city, author, year, language, extension. Counts are
    measurements of what the map holds, not statements about the world."""
    t0 = time.time()
    cols = {"publisher": "Publisher", "city": "City", "author": "Author",
            "year": "Year", "language": "Language", "extension": "Extension"}
    col = cols.get(field)
    if not col:
        return {"error": "unknown field", "allowed": sorted(cols)}
    limit = max(1, min(int(limit), 200))
    with _lock:
        rows = [dict(r) for r in db().execute(
            "SELECT COALESCE(NULLIF(TRIM(%s), ''), '(none)') AS value,"
            " COUNT(*) AS n FROM nz_map GROUP BY value"
            " ORDER BY n DESC LIMIT ?" % col, (limit,))]
    meter("census", {"field": field}, len(rows), (time.time() - t0) * 1000)
    return {"field": field, "values": rows,
            "note": "Counts within the map only."}


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    try:
        c = db()
        catalog = c.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        mapped = c.execute("SELECT COUNT(*) FROM nz_map").fetchone()[0]
        return JSONResponse({"ok": True, "catalog_rows": catalog,
                             "mapped_rows": mapped})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8647,
            streamable_http_path="/mcp")
