"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
entries sample.list names (`key: item <list> <sha256>` lines), from
the document store, through this branch's own reading, into `schema` of the
sample database (the lane's tables there carry its name). The listing page
and the documents about the source are listed for the tests, not read as
entries. A document not in the store fails the fill, naming its hash. No
model is called and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import names_of, path_for  # noqa: E402
from registers.commerce_commission import load  # noqa: E402


def entries_of(items: list, conn) -> list:
    """[(list, slug, url, sha256, None)]: the slug from the page's own address, which the landing wrapper kept as
    a name of the document (support.docstore.landing.names_of), so no slug (some carry a person's name) is written into git."""
    for sha in (i for i in items if not i.startswith("key:")):
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"commerce_commission/sample.list names {sha}, which is not in the document store")
    out = []
    for i in items:
        if i.startswith("key: item "):
            _, _, lst, sha = i.split()
            urls = [n for n in names_of(sha, conn) if n.startswith("https://")]
            if not os.path.exists(path_for(sha)) or not urls:
                raise LookupError(f"commerce_commission/sample.list names {sha}, which is not in the document store with its address")
            url = urls[0]
            out.append((lst, url.rstrip("/").rsplit("/", 1)[1], url, sha, None))
    return out


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, entries_of(items, conn))["cases"]
