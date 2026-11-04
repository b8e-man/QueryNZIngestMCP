"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
decisions-list pages sample.list names (`key: page <sha256> <n>` lines give
their order in the pass) and the register's pages (`key: reglist`, `key:
regdetail`), from the document store, through this branch's own
reading, into `schema` of the sample database (the lane's tables there carry
its name). The documents about the source are listed but not read as pages.
A document not in the store fails the fill, naming its hash. No model is
called and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import path_for  # noqa: E402
from registers.building_practitioners import load  # noqa: E402


def pages_of(items: list) -> list:
    order = {}
    for i in items:
        if i.startswith("key: page "):
            _, _, sha, n = i.split()
            order[sha] = int(n)
    for sha in (i for i in items if not i.startswith("key:")):
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"building_practitioners/sample.list names {sha}, which is not in the document store")
    return [(sha, 1) for sha, _ in sorted(order.items(), key=lambda kv: kv[1])]


def register_of(items: list) -> dict:
    """`key: reglist <sha256>` (a search page of the register) and `key: regdetail <sha256>` (a practitioner's page)."""
    lists = [i.split()[2] for i in items if i.startswith("key: reglist ")]
    details = [i.split()[2] for i in items if i.startswith("key: regdetail ")]
    return {"pass_id": 0 if lists else None, "lists": lists, "details": details}


def fill(conn, schema: str, items: list) -> int:
    return load.build(conn, schema, pages_of(items), shared=True, reg=register_of(items))["decisions"]
