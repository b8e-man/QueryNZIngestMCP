"""The sample filler (plan 1b.6): the lane reads no council list, so `fill`
only proves each `key:` document of sample.list is in the store and
recognised as its key says (`key: bars <url> <sha256>`). No model is called
and nothing is fetched."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import path_for, read_bytes  # noqa: E402
from registers.council_procurement import read  # noqa: E402


def fill(conn, schema: str, items: list) -> int:
    n = 0
    for i in items:
        sha = i.split()[-1]
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"council_procurement/sample.list names {sha}, which is not in the document store")
        if i.startswith("key: "):
            _, want, url, _ = i.split()
            got = read.recognise(url, read_bytes(sha))
            if got != want:
                raise AssertionError(f"{sha[:12]}… is listed as {want} and recognised as {got}")
            n += 1
    return n
