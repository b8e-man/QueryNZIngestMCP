"""The sample filler (plan 1b.6): `fill(conn, schema, items)` reads the
corpus records named in sample.list (their hashes, as support/mcpsource
landed them) and the files they point at from the document store into
`schema` of the sample database through this branch's own code. A record
not in the store fails naming it; a file not in the store is a catch-log
line, as it is live. No model is called (the text reader's readings are
replayed from the reader store where they exist); nothing is fetched.

Every module fills one shared scratch schema, so this lane's tables there
carry its name (`courts_documents`, …; load.table). The ledger of orders
there is the sample's own.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from support.docstore.landing import path_for  # noqa: E402
from registers.courts import capture  # noqa: E402
from registers.courts import load as L  # noqa: E402


def entries_of(shas: list) -> list:
    """The lane's entries for record documents held in the store, in the
    list's order; the file's state is `landed` when the store holds it and
    `caught` when it does not (the sample's stand-in for the pull's row)."""
    out = []
    for n, sha in enumerate(shas, 1):
        if not os.path.exists(path_for(sha)):
            raise LookupError(f"courts/sample.list names record {sha}, which is not in the document store: run the pull "
                              "(python -m support.mcpsource --corpus courts)")
        rec = capture.record_of(sha)
        cap = (rec.get("capture") or {}).get("sha256")
        state = "landed" if cap and os.path.exists(path_for(cap)) else "caught"
        out.append(capture.entry(rec.get("id") or rec.get("url"), n, sha, rec.get("url"), rec.get("content_type"), cap, state,
                                 (rec.get("capture") or {}).get("bytes"), rec=rec))
    return out


def fill(conn, schema: str, items: list) -> int:
    hashes = [i.split()[0] for i in items if not i.startswith("key:")]
    if not hashes or hashes[0] != capture.LISTING_SHA:
        raise LookupError("courts/sample.list must name the old listing first (the gap report reads it)")
    entries = entries_of(hashes[1:])
    conn.execute(L.capture_tables_sql(schema, shared=True))
    # the gap report (the old listing's judgments the corpus lacks) is the live check's: against twenty records it says nothing
    counts = L.build(conn, schema, entries, [], L.orders(conn, schema, shared=True), shared=True, old_listing=[])
    return counts["records"]
