"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
pages sample.list names (`key: page <sha256>` lines), from the document
store, through this branch's own reading, into `schema` of the sample
database (the lane's tables there carry its name). The page's address is the
name the landing wrapper kept for it, so no address enters git. A document
not in the store fails the fill, naming its hash. No model is called and
nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import names_of, path_for  # noqa: E402
from registers.iwi_directory import load  # noqa: E402


def entries_of(items: list, conn) -> list:
    """[(url, sha256)] for each `key: page` line."""
    out = []
    for i in items:
        if not i.startswith("key: page "):
            continue
        sha = i.split()[2]
        urls = [n for n in names_of(sha, conn) if n.startswith("https://www.tkm.govt.nz/")]
        if not os.path.exists(path_for(sha)) or not urls:
            raise LookupError(f"iwi_directory/sample.list names {sha}, which is not in the document store with its address")
        out.append((sorted(urls)[0], sha))
    return out


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, entries_of(items, conn))["entities"]
