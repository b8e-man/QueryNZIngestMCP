"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the pages
sample.list names, from the document store, through this branch's own
reading, into `schema` of the sample database. `key: <feed set> <id>` lines
name the rows read from a set's pages; a set with no key line is read whole.
Each page says which set it is from (its rows' own metadata), so no listing
is needed; a listed document that is not a feed page (the feed's metadata,
the open-data page: the capture's cases) is not read. A document not in the
store fails the fill, naming its hash. No model is called and nothing is
fetched.

Every module fills one shared scratch schema, so the lane's tables there
carry its name (`charities_charities`, …; load.table), the address in the
schema's private twin.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import path_for, read_bytes  # noqa: E402
from registers.charities import load as L  # noqa: E402
from registers.charities import read  # noqa: E402


def keys_of(items: list) -> dict:
    """feed set → the ids its key lines name."""
    out = collections.defaultdict(set)
    for i in items:
        if i.startswith("key:"):
            _, s, rid = i.split()
            out[s].add(int(rid))
    return dict(out)


def pages_of(items: list) -> dict:
    """feed set → [sha256], in the order of their first key (one pass's order)."""
    out = collections.defaultdict(list)
    for sha in dict.fromkeys(i for i in items if not i.startswith("key:")):
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"charities/sample.list names {sha}, which is not in the document store")
        try:
            _, rows = read.parse_page(read_bytes(sha))
        except ValueError:          # not JSON: a document about the feed, not a page of it
            continue
        if not rows:
            raise ValueError(f"charities/sample.list names {sha}, a page with no rows: it names no set")
        s = read.set_of(rows[0])
        first = rows[0].get(read.SETS.get(s, "")) or 0
        out[s].append((first, sha))
    return {s: [sha for _, sha in sorted(v)] for s, v in out.items()}


def fill(conn, schema: str, items: list) -> int:
    counts = L.build(conn, schema, pages_of(items), only=keys_of(items), shared=True)
    return counts["charities"] + counts["officers"] + counts["returns"] + counts["groups"]
