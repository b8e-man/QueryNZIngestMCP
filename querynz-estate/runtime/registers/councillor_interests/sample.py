"""The sample filler (plan 1b.6): `fill(conn, schema, items)` builds the
lane's reading from the pages sample.list names (`key: page <sha256>
<council>` lines), from the document store, through this branch's own
reading, into `schema` of the sample database. A page's address is the name
the landing wrapper kept for it. A document not in the store fails the fill.
No model is called and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import names_of, path_for  # noqa: E402
from registers.councillor_interests import capture, load  # noqa: E402


def items_of(items: list, conn) -> list:
    """The capture-record items the sample's pages stand for."""
    out = []
    for i in items:
        if not i.startswith("key: page "):
            continue
        _, _, sha, council = i.split(" ", 3)
        host = capture.REGISTERS[council][0]
        urls = [n for n in names_of(sha, conn) if capture.on_site(n, host)]
        if not os.path.exists(path_for(sha)) or not urls:
            raise LookupError(f"councillor_interests/sample.list names {sha}, which is not in the document store with its address")
        out.append({"council": council, "url": sorted(urls)[0], "kind": "page", "found_on": None, "asked_at": None,
                    "sha256": sha, "why": None})
    return out


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, items_of(items, conn), {})["interests"]
