"""The sample filler (plan 1b.6): `fill(conn, schema, items)` loads the
returns named in sample.list into `schema` of the sample database through
this branch's own code, with the Commission's listing and spreadsheets
beside them (landed by hash; they are small). Each return is found in the
old folder by the old folder's manifests and its hash checked on landing;
one the manifests misname is found by hashing every in-window file; one
found nowhere fails naming the hash, so the session can ask for a capture.
No model is called; stored page readings are replayed, except for a return
the list names on a `key: empty-store <sha256>` line, which is read as if
the store held nothing for it: a case that must stay set aside for a
re-read cannot be moved by a job that later reads it.

Every module fills one shared scratch schema, so this lane's tables there
carry its name (`candidate_returns_files`, …; `load.table`).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support import reader as rd  # noqa: E402
from support.docstore import sha256_file  # noqa: E402
from support.docstore.landing import copy_from_old, read_bytes  # noqa: E402
from registers.candidate_returns import capture, load  # noqa: E402


def _land(paths: list, sha: str, conn) -> list:
    """The paths whose bytes, landed, are `sha`."""
    out = []
    for p in paths:
        ref, _ = copy_from_old(p, capture.SOURCE, conn)
        if ref.sha256 == sha:
            out.append(p)
    return out


def fill(conn, schema: str, items: list) -> int:
    load.create_tables(conn, schema, shared=True)
    load.wipe(conn, schema, shared=True)
    shas = [i.split()[0] for i in items if i.strip() and not i.startswith("key:")]
    hidden = {i.split()[2] for i in items if i.startswith("key:") and i.split()[1:2] == ["empty-store"]}
    manifest, everything = capture.manifest_index(), None
    landed = {}
    for sha in shas:
        paths = _land(manifest.get(sha, []), sha, conn)
        if not paths:                                 # the manifest misnames it: hash every in-window file, once
            everything = everything if everything is not None else _hash_all()
            paths = _land(everything.get(sha, []), sha, conn)
        if not paths:
            raise LookupError(f"candidate_returns/sample.list names {sha}, which is not among the old folder's "
                              f"in-window returns: ask for a capture")
        landed[sha] = paths
    store = rd.Store()
    store.hidden = hidden
    b = load.build(landed, load.statements(conn), store, read_bytes)
    load.insert(conn, schema, b, shared=True)
    c = load.counts(b)
    if not c["reconciles"]:
        raise RuntimeError(f"candidate_returns: the sample's catch log does not reconcile: {c}")
    return c["rows"]


def _hash_all() -> dict:
    out = {}
    for p in capture.return_files():
        out.setdefault(sha256_file(p), []).append(p)
    return out
