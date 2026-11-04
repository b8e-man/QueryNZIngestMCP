"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
listing pages sample.list names (`key: page <sha256>` lines), from the
document store, through this branch's own reading, into `schema` of the
sample database (the lane's tables there carry its name). The page's
address comes from the names the landing wrapper kept and its council from
`listings.tsv`, so no address enters git. A document not in the store fails
the fill, naming its hash. No model is called, nothing is fetched, and no
return is opened."""
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import names_of, path_for  # noqa: E402
from registers.local_elections import capture, load  # noqa: E402


def council_of(url: str, seed_list=None) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    for council, _years, seed in (seed_list if seed_list is not None else capture.seeds()):
        if (urllib.parse.urlsplit(seed).hostname or "") == host:
            return council
    raise LookupError(f"local_elections: no seeded council for {host}")


def pages_of(items: list, conn) -> list:
    out = []
    for i in items:
        if not i.startswith("key: page "):
            continue
        sha = i.split()[2]
        urls = [n for n in names_of(sha, conn) if n.startswith("http")]
        if not os.path.exists(path_for(sha)) or not urls:
            raise LookupError(f"local_elections/sample.list names {sha}, which is not in the document store with its address")
        url = sorted(urls)[0]
        out.append({"council": council_of(url), "url": url, "sha256": sha, "seed_year": None})
    return out


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, pages_of(items, conn), {})["returns"]
