"""Held-document lookup for the fetch gate — global dedupe (2026-11-10).

The gate consults this before the network: a URL the store already holds as
an immutable document (pdf / image / spreadsheet) is served from the store's
captured bytes and never asked for twice. Web pages, csvs and `other` (JSON
listing/API pages) are never served from here — their re-read is how a change
is noticed (unchanged bytes land as `new=False`, changed bytes as a new
document).

Set QV4_RECAPTURE=1 to bypass and ask the network anyway (a person's
deliberate recapture, e.g. the courts 107 repair).
"""
import os
import sqlite3
import threading

DBDIR = os.environ.get("QV4_DB") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db")
DB = os.path.join(DBDIR, "docs.sqlite")
IMMUTABLE = ("pdf", "image", "spreadsheet")

_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
    return _conn


def held_document(name: str):
    """(sha256, path, kind) for a URL held as an immutable document, else None."""
    marks = ",".join("?" * len(IMMUTABLE))
    with _lock:
        row = _db().execute(
            f"SELECT d.sha256, d.path, d.kind FROM names n "
            f"JOIN documents d ON d.sha256 = n.sha256 "
            f"WHERE n.name = ? AND n.kind = 'url' AND d.kind IN ({marks}) "
            f"ORDER BY n.seen_at LIMIT 1", (name, *IMMUTABLE)).fetchone()
    return row or None


def held_bytes(name: str):
    """(sha256, bytes) of a held immutable document, else None."""
    r = held_document(name)
    if r is None:
        return None
    sha, path, _ = r
    try:
        with open(path, "rb") as f:
            return sha, f.read()
    except OSError:
        return None
