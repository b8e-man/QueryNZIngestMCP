"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
documents sample.list names, from the document store, through this branch's
own reading, into `schema` of the sample database (the lane's tables there
carry its name). A hash whose shape a profile recognises is read: the
national file only at the records the `key: dia N` lines name, a record of
grants whole, a society's file (a PDF) whole or as one catch-log line. Any
other hash is a document the capture holds and the reading does not (a page
about the source, a page the walk passed through, a challenge page). A
document not in the store fails the fill, naming its hash. No model is
called and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import path_for, read_bytes  # noqa: E402
from registers.grants import load, read  # noqa: E402

LIST_OF = {read.DIA_CSV: "dia-file", read.LOTTERY_PAGE: "lottery-page"}


def docs_of(items: list) -> tuple:
    """([(list, url, sha256)] for every recognised document, {sha256 of the national file: record numbers})."""
    records = {int(i.split()[2]) for i in items if i.startswith("key: dia ")}
    docs, only = [], {}
    for sha in dict.fromkeys(i for i in items if not i.startswith("key:")):
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"grants/sample.list names {sha}, which is not in the document store")
        data = read_bytes(sha)
        slug = read.recognise(data)
        if slug in LIST_OF:
            docs.append((LIST_OF[slug], None, sha))
            if slug == read.DIA_CSV:
                only[sha] = records
        elif data.startswith(b"%PDF"):                  # a society's file: read, or a catch-log line
            docs.append(("society-file", None, sha))
    return docs, only


def fill(conn, schema: str, items: list) -> int:
    docs, only = docs_of(items)
    return load.build(conn, schema, docs, only=only)["grants"]
