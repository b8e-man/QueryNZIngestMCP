"""The sample filler (plan 1b.6): `fill(conn, schema, items)` loads the
documents named in sample.list into `schema` of the sample database
through this branch's own code. A document not yet in the store is copied
by hash from the old folder; one found in neither fails naming the hash, so
the session can ask for a capture. No model is called.

Every module fills one shared scratch schema, so this lane's tables there
carry its name (`disclosures_declarations`, …; load.table).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore import sha256_file  # noqa: E402
from support.docstore.landing import copy_from_old, land, names_of, path_for, read_bytes  # noqa: E402
from registers.disclosures import capture  # noqa: E402
from registers.disclosures import load as L  # noqa: E402


def old_index() -> dict:
    """sha256 → [(kind, old path)] for every candidate file of the old folder:
    one document may be held under several names."""
    out = {}
    for kind, p in capture.candidate_files():
        out.setdefault(sha256_file(p), []).append((kind, p))
    return out


def kind_of(data: bytes) -> str:
    return "listing" if data.lstrip()[:1] == b"<" else "declaration"


def fill(conn, schema: str, items: list) -> int:
    index = None
    listings, declarations = [], []
    for item in items:
        if item.startswith("key:"):
            continue
        sha = item.split()[0]
        if os.path.exists(path_for(sha)):
            data = read_bytes(sha)
            # every name the store and the old folder know: the table may link any one of them
            index = index if index is not None else old_index()
            names = {os.path.basename(n) for n in names_of(sha, conn)} | {os.path.basename(p) for _, p in index.get(sha, [])}
            names = sorted(names) or [sha]
            for name in names:
                land(data, name=name, source=capture.SOURCE, conn=conn)
        else:
            index = index if index is not None else old_index()
            if sha not in index:
                raise LookupError(f"disclosures/sample.list names {sha}, which is neither in the document store "
                                  f"nor in the old folder: ask for a capture")
            for _, p in index[sha]:
                ref, _ = copy_from_old(p, capture.SOURCE, conn)
            data, names = read_bytes(sha), [os.path.basename(p) for _, p in index[sha]]
        group = listings if kind_of(data) == "listing" else declarations
        group += [(sha, capture.commission_name(n)) for n in sorted(set(names))]
    return L.build(conn, schema, listings, declarations, [], shared=True)["rows"]
