"""The lane's one figure against the outside world (contract: the lane).

The source's own count is the Board's: the decisions list's heading,
"Displaying 20 of N results", landed with the first page of every pass. Exit
1 on any of:

  1. no finished pass of the decisions list is held
  2. the newest finished pass's distinct decisions (typed, plus set aside)
     differ from the N its first page stated by more than `SLACK` (the Board
     can add a decision while a pass of about eighty pages is running)
  3. the reading does not reconcile (items in ≠ typed + superseded + set
     aside on a page), or a view shows a suppressed practitioner's name,
     number or decision address, or carries an address column
  4. the register of practitioners has rows while the position records no
     `authorised: register` line
  5. the register (ruling 132): no finished pass of its 26 searches; a
     practitioner's page neither a row nor set aside; more than
     `AWAITING_MAX` of the practitioners the newest pass lists without their
     page read (the copy is not yet whole); a town whose shape names an
     address without its flag

Every line printed is a count.

    python -m registers.building_practitioners.check
"""
import argparse
import json
import sys

from registers.building_practitioners import capture

SCHEMA = "building_practitioners"
SLACK = 2
AWAITING_MAX = 0.02
ADDRESSISH = ("address", "street", "postal", "residential", "home", "email", "phone", "suburb", "postcode")
#: boolean flags that say a text names an address by its shape (ruling 102): a yes or no, never the address
FLAGS = ("area_names_address",)


def reading(conn, schema: str = SCHEMA, shared: bool = False) -> list:
    from registers.building_practitioners import load
    T = lambda t: load.table(schema, t, shared)
    out = []
    bad = conn.execute(f"SELECT count(*) FROM {T('read_pages')} WHERE stated IS NOT NULL AND "
                       "items <> typed + superseded + set_aside").fetchone()[0]
    if bad:
        out.append(f"{bad} pages do not reconcile")
    typed = conn.execute(f"SELECT count(*) FROM {T('decisions')}").fetchone()[0]
    said = conn.execute(f"SELECT coalesce(sum(typed), 0) FROM {T('read_pages')}").fetchone()[0]
    if typed != said:
        out.append(f"{typed} decision rows against {said} in the ledger")
    held = conn.execute(f"SELECT count(*) FROM {T('practitioners')}").fetchone()[0]
    if held and not capture.authorisation("register"):
        out.append(f"{held} practitioner rows while the position records no authorisation")
    if conn.execute("SELECT to_regclass(%s)", (T("read_register"),)).fetchone()[0] is None:
        out.append("no register ledger: the load predates the register's reading")
        return out
    led = conn.execute(f"SELECT pages, typed, set_aside, listed, awaiting FROM {T('read_register')}").fetchone()
    if led is not None:
        pages, typed, aside, listed, awaiting = led
        if pages != typed + aside:
            out.append(f"{pages} practitioner pages against {typed} rows and {aside} set aside")
        if typed != held:
            out.append(f"{held} practitioner rows against {typed} in the register's ledger")
    from registers.building_practitioners import register
    unflagged = [a for a, f in conn.execute(f"SELECT area, area_names_address FROM {T('practitioners')} "
                                            "WHERE area IS NOT NULL") if register.names_address(a) and not f]
    if unflagged:
        out.append(f"{len(unflagged)} towns shaped as an address without their flag")
    return out


def register_outside(conn, schema: str = SCHEMA, shared: bool = False) -> dict:
    """The register's own count: the practitioners its newest finished pass of searches lists, against those read."""
    from registers.building_practitioners import load
    if not capture.authorisation("register"):
        return {"ok": True, "detail": "not authorised: nothing asked"}
    led = conn.execute(f"SELECT pass_id, searches, listed, pages, typed, set_aside, awaiting "
                       f"FROM {load.table(schema, 'read_register', shared)}").fetchone()
    if led is None or led[0] is None:
        return {"ok": False, "detail": "no finished pass of the register's searches is read"}
    pass_id, searches, listed, pages, typed, aside, awaiting = led
    from registers.building_practitioners.register import QUERIES
    ok = searches == len(QUERIES) and listed > 0 and awaiting <= AWAITING_MAX * listed
    return {"ok": ok, "pass_id": pass_id, "searches": searches, "listed": listed, "pages": pages, "typed": typed,
            "set_aside": aside, "awaiting": awaiting}


def views(conn, prefix: str = "pub.") -> list:
    out = []
    n = conn.execute(f"SELECT count(*) FROM {prefix}building_practitioner_decisions WHERE suppressed AND "
                     "(name <> 'name withheld by the Board' OR lbp_number IS NOT NULL OR decision_url IS NOT NULL "
                     "OR pdf_url IS NOT NULL)").fetchone()[0]
    if n:
        out.append(f"{n} suppressed decisions show a name, number or address on the view")
    schema, _, stem = prefix.rstrip(".").partition(".")
    for v in ("building_practitioner_decisions", "building_practitioners"):
        cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                                           "AND table_name = %s", (schema or "pub", (stem + v) if stem else v))]
        extra = [c for c in cols if any(w in c for w in ADDRESSISH) and c not in FLAGS]
        if extra:
            out.append(f"{v} carries {', '.join(extra)}")
    return out


def outside(conn, schema: str = SCHEMA) -> dict:
    r = conn.execute(f"SELECT pass_id, stated, pages, items FROM {schema}.capture_passes WHERE finished_at IS NOT NULL "
                     "ORDER BY finished_at DESC LIMIT 1").fetchone()
    if r is None:
        return {"ok": False, "detail": "no finished pass of the decisions list is held"}
    pass_id, stated, pages, items = r
    shas = [x[0] for x in conn.execute(f"SELECT sha256 FROM {schema}.capture_pages WHERE pass_id = %s", (pass_id,))]
    from support.docstore.landing import read_bytes
    from registers.building_practitioners import read
    keys, asides = set(), 0
    for sha in shas:
        out = read.read_page(read_bytes(sha), sha, 1)
        keys |= {x["key"] for x in out["rows"]}
        asides += sum(1 for a in out["set_aside"] if a["place"].startswith("item["))
    held = len(keys) + asides
    return {"ok": stated is not None and abs(held - stated) <= SLACK, "pass_id": pass_id, "stated": stated,
            "pages": pages, "items_listed": items, "distinct_decisions": len(keys), "set_aside": asides,
            "difference": None if stated is None else held - stated}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.building_practitioners.check")
    ap.add_argument("--database", default="querynz_v4")
    a = ap.parse_args(argv)
    from support import db
    with db.connect(db.READ_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        if conn.execute("SELECT to_regclass('building_practitioners.read_pages')").fetchone()[0] is None:
            print(f"{SCHEMA}: check: nothing published yet (no load has run)")
            return 1
        out = outside(conn)
        out["register"] = register_outside(conn)
        out["problems"] = reading(conn) + views(conn)
    print(f"{SCHEMA}: check: " + json.dumps(out, default=str))
    return 0 if out["ok"] and out["register"]["ok"] and not out["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
