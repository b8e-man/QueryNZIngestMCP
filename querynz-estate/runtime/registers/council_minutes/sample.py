"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
listings sample.list names (`key: listing <sha256>` lines), from the document
store, through this branch's own reading, into `schema` of the sample
database (the lane's tables there carry its name). A listing's address is the
name the landing wrapper kept for it, so no address enters git. A document
not in the store fails the fill, naming its hash. Minutes are never read. No
model is called and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import names_of, path_for  # noqa: E402
from support.fetchgate import host_of  # noqa: E402
from registers.council_minutes import capture, load  # noqa: E402


def listings_of(items: list, conn) -> list:
    """[(host, sha256, None)] for each `key: listing` line."""
    out = []
    for i in items:
        if not i.startswith("key: listing "):
            continue
        sha = i.split()[2]
        hosts = sorted({host_of(n) for n in names_of(sha, conn) if host_of(n) in capture.COUNCIL_OF_HOST})
        if not os.path.exists(path_for(sha)) or not hosts:
            raise LookupError(f"council_minutes/sample.list names {sha}, which is not in the document store with its address")
        out.append((hosts[0], sha, None))
    return out


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, listings_of(items, conn), {})["meetings"]
