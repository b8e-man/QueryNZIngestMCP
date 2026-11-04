"""A council's minutes PDF with no text layer (profile `council-minutes-scanned` v1): recognised by its shape
(minutes.scan_shape: a PDF, no usable text layer, at least half its pages a page-wide image; never a phrase, since a
scan has no text for one to match), every page read by the page reader, and its text then read exactly as a text
layer is (load.read_minutes and model_read: the same two skips first, then the standard template's reading or the
text reader).

The page reader runs only in its night window (ruling 129: between 22:00 and 05:45 NZDT, when page pieces are queued
and no text-reader piece is running, the card manager stops the standing server and loads `page-reader`); this lane
only queues pieces, `qv4-council-minutes-pages`, one document a piece. Every page of a scan is read, its text layer
or none (a scan's few characters are the scanner's, not the minutes'), at a pinned DPI so the key the piece stores
and the key the load asks for are the same whatever the worker's environment says. Stored by hash and page under
this profile (ruling 50); the load and the text reader replay them and never call the page reader.

    texts(sha256, data, store)        ({page: text tidied by minutes.from_pages}, unread pages): every page or none
    python -m registers.council_minutes.scans --pieces        every landed scan with a page unread, one sha256 a line
    python -m registers.council_minutes.scans --piece SHA256  one piece of qv4-council-minutes-pages (counts only)
"""
import os
import re
import sys

from support import profiles
from support import reader as rd
from support.docread import pages, pagereader
from registers.council_minutes import minutes as M

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profiles-proposed.jsonl")
PROFILE = M.SCANNED
#: pinned: the page reader's key carries the DPI, so the piece and the load must agree on it
DPI = 200
SOURCE = f"page reader {pagereader.MODEL} at {DPI} dpi, profile {PROFILE}"


def profile_version() -> int:
    held = [p for p in (profiles.profile(PROFILE), profiles.profile(PROFILE, path=PROPOSED) if os.path.exists(PROPOSED)
                        else None) if p]
    if not held:
        raise LookupError(f"no document profile {PROFILE}")
    return max(int(p["version"]) for p in held)


def page_key(sha256: str, page: int, version: int) -> str:
    """The key read_document stores a page-reader page under (support.docread.read: model, then dpi and prompt)."""
    return rd.reading_key(sha256, page, pagereader.MODEL, {"dpi": DPI, "prompt": pagereader.PROMPT}, PROFILE, version)


def recognise(data: bytes, layer: dict) -> tuple:
    """(SCANNED, '') or ('', why), from the document's shape alone (`layer`: its text-layer pages, measured)."""
    how = pages.read_from(data, layer)
    if how != "pixels":
        return "", f"it has a text layer ({how})"
    return M.scan_shape(data, how, len(layer), M.picture_pages(data))


def texts(sha256: str, data: bytes, store: rd.Store = None, version: int = None, layer: dict = None) -> tuple:
    """({page: page-reader text, tidied}, []) when every page is stored; (None, [unread pages]) otherwise. The text is
    the page reader's alone: a scan is never read half from its layer."""
    store = store or rd.Store()
    version = version or profile_version()
    layer = layer if layer is not None else pages.text_pages(data)
    got, unread = {}, []
    for p in sorted(layer):
        key = page_key(sha256, p, version)
        if store.has(key):
            got[p] = M.from_pages(store.get(key).text)
        else:
            unread.append(p)
    if unread or not got:
        return None, unread or sorted(layer)
    return got, []


def read_pages(sha256: str, *, url: str = None, model: str = None, store: rd.Store = None, post=None,
               data: bytes = None) -> dict:
    """One piece of `qv4-council-minutes-pages`: every page of one scan through the page reader on the card the worker
    holds, each stored once; a stored page is replayed. Counts only; no page text is printed."""
    from support.docread.read import read_document
    if data is None:
        from support.docstore.landing import read_bytes
        data = read_bytes(sha256)
    store = store or rd.Store()
    layer = pages.text_pages(data)
    prof, why = recognise(data, layer)
    if prof != PROFILE:
        return {"document": sha256, "state": why, "pages": len(layer), "read_now": 0, "replayed": 0, "unread": []}
    # every page counted thin, so every page goes to the page reader (a scan's few layer characters are the scanner's)
    got = read_document(data, sha256, profile=PROFILE, profile_version=profile_version(), store=store, page_reader=True,
                        dpi=DPI, texts={p: "" for p in layer}, url=url, model=model, post=post)
    return {"document": sha256, "state": "read" if not got.unread else "pages unread", "pages": len(layer),
            "read_now": len(got.readings) - got.replayed, "replayed": got.replayed, "unread": list(got.unread)}


def waiting(conn, store: rd.Store = None, read_bytes=None) -> list:
    """The landed minutes PDFs that are scans with a page not yet read, fewest pages first (sha256)."""
    if read_bytes is None:
        from support.docstore.landing import read_bytes
    store = store or rd.Store()
    version = profile_version()
    out = []
    for (sha,) in conn.execute("SELECT DISTINCT sha256 FROM council_minutes.capture_documents WHERE state = 'landed' "
                               "AND sha256 IS NOT NULL ORDER BY sha256").fetchall():
        data = read_bytes(sha)
        if not data[:5].startswith(b"%PDF"):
            continue
        layer = pages.text_pages(data)
        if pages.read_from(data, layer) != "pixels" or recognise(data, layer)[0] != PROFILE:
            continue
        if any(not store.has(page_key(sha, p, version)) for p in layer):
            out.append((len(layer), sha))
    return [sha for _n, sha in sorted(out)]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    database = argv[argv.index("--database") + 1] if "--database" in argv else "querynz_v4"
    if "--pieces" in argv:
        from support import db
        with db.connect(db.READ_KEY, database) as conn:
            conn.execute("SET statement_timeout = '60s'")
            for sha in waiting(conn):
                print(sha)
        return 0
    if "--piece" in argv:
        sha = argv[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            print("--piece takes the document's sha256 as the last argument", file=sys.stderr)
            return 2
        line = read_pages(sha, url=os.environ.get("QV4_MODEL_URL"), model=os.environ.get("QV4_MODEL"))
        print(f"council minutes pages: {sha[:12]} {PROFILE}@{profile_version()}: {line['state']}, {line['pages']} page(s), "
              f"read now {line['read_now']}, replayed {line['replayed']}, unread {line['unread']}")
        return 1 if line["unread"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
