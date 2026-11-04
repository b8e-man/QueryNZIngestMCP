"""The lane's one figure against the outside world (contract: the lane).

The source's own count is the Commission's: the case register listing's
`:total`, landed with the first page of every pass (1,727 on 21 October
2026; the old estate held 112). Exit 1 on any of:

  1. no finished pass of the listing is held
  2. the newest finished pass's distinct entries differ from the total its
     first page stated by more than `SLACK` (the Commission can add an entry
     while a pass of eighteen pages runs)
  3. an entry it listed is not read: not captured yet, or set aside
  4. the reading does not reconcile (a listed entry with no ledger line, a
     case row with no ledger line, a party with no case), or a view shows a
     withheld name, carries an address column, or a text value shaped like a
     street address (reported by key, never by value)

Every line printed is a count.

    python -m registers.commerce_commission.check [--database querynz_v4]
"""
import argparse
import json
import re
import sys

from registers.commerce_commission import capture

SCHEMA = "commerce_commission"
SLACK = 2
ADDRESSISH = ("address", "street", "postal", "residential", "home", "email", "phone", "suburb", "postcode")
VIEWS = ("commerce_commission_cases", "commerce_commission_parties")
_NUM = r"\d{1,4}[A-Za-z]?(?:\s*[-/]\s*\d{1,4}[A-Za-z]?)?"
_STREET = (r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Crescent|Cres|Terrace|Tce|Lane|Way|Parade|Highway|Hwy|"
           r"Grove|Close|Court|Ct|Rise|Quay|Square|Boulevard|Esplanade|Mews|Heights|Glade|Row|Promenade|Strand|Mall)")
_NOT_A_HOUSE = "".join(f"(?<!{re.escape(w)} )" for w in ("Highway", "Hwy", "SH", "No", "No.", "Act", "Regulations",
                                                         "Section", "Schedule", "Part", "Clause", "s", "ss"))
STREET = re.compile(rf"(?<![\w/.-]){_NOT_A_HOUSE}{_NUM},?\s+(?:[A-Z][\w'’.-]*\s+){{1,4}}{_STREET}\b"
                    rf"(?!\s+(?:Limited|Ltd|Incorporated|Inc)\b)")


def reading(conn, schema: str = SCHEMA) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    n = conn.execute(f"SELECT count(*) FROM {T('cases')} c WHERE NOT EXISTS (SELECT 1 FROM {T('read_items')} r "
                     "WHERE r.document = c.document AND r.state = 'read')").fetchone()[0]
    if n:
        out.append(f"{n} case rows with no ledger line")
    read_n = conn.execute(f"SELECT count(*) FROM {T('read_items')} WHERE state = 'read'").fetchone()[0]
    cases = conn.execute(f"SELECT count(*) FROM {T('cases')}").fetchone()[0]
    if read_n != cases:
        out.append(f"{cases} case rows against {read_n} entries read in the ledger")
    said = conn.execute(f"SELECT coalesce(sum(parties), 0) FROM {T('read_items')}").fetchone()[0]
    parties = conn.execute(f"SELECT count(*) FROM {T('parties')}").fetchone()[0]
    if said != parties:
        out.append(f"{parties} party rows against {said} in the ledger")
    orphans = conn.execute(f"SELECT count(*) FROM {T('parties')} p WHERE NOT EXISTS (SELECT 1 FROM {T('cases')} c "
                           "WHERE c.key = p.case_key)").fetchone()[0]
    if orphans:
        out.append(f"{orphans} parties with no case")
    leaked = conn.execute(f"SELECT count(*) FROM {T('parties')} WHERE withheld AND (name IS NOT NULL OR trading_as IS NOT NULL)"
                          ).fetchone()[0]
    if leaked:
        out.append(f"{leaked} withheld parties keep a name in the table")
    # ruling 142: a name a suppression the page states covers is kept whole in the private twin, keyed by the row
    P = (lambda t: f"{SCHEMA}_private.{t}") if schema == SCHEMA else T
    see = schema != SCHEMA or conn.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s AND "
                                           "has_schema_privilege(current_user, oid, 'USAGE'))",
                                           (f"{SCHEMA}_private",)).fetchone()[0]
    lost = see and conn.execute(f"SELECT count(*) FROM {T('parties')} p WHERE p.withheld_by = 'the page states a "
                                f"suppression' AND NOT EXISTS (SELECT 1 FROM {P('suppressed_names')} s WHERE s.key = "
                                "p.key)").fetchone()[0]
    if lost:
        out.append(f"{lost} suppressed parties with no name kept in the private twin")
    return out


def views(conn, prefix: str = "pub.") -> list:
    out = []
    n = conn.execute(f"SELECT count(*) FROM {prefix}commerce_commission_parties WHERE withheld AND "
                     "(name <> 'name withheld' OR trading_as IS NOT NULL)").fetchone()[0]
    if n:
        out.append(f"{n} withheld parties show a name on the view")
    n = conn.execute(f"SELECT count(*) FROM {prefix}commerce_commission_cases c WHERE (c.title_withheld AND "
                     "c.title <> 'name withheld by the Commission') OR EXISTS (SELECT 1 FROM "
                     f"{prefix}commerce_commission_parties p WHERE p.case_key = c.key AND p.withheld_by = "
                     "'the page states a suppression' AND (c.url IS NOT NULL OR NOT c.title_withheld))").fetchone()[0]
    if n:
        out.append(f"{n} cases show a withheld heading or the page address of a suppressed name")
    schema, _, stem = prefix.rstrip(".").partition(".")
    schema = schema or "pub"
    for v in VIEWS:
        name = (stem + v) if stem else v
        cols = [r for r in conn.execute("SELECT column_name, data_type FROM information_schema.columns "
                                        "WHERE table_schema = %s AND table_name = %s", (schema, name))]
        extra = [c for c, _ in cols if any(w in c for w in ADDRESSISH)]
        if extra:
            out.append(f"{v} carries {', '.join(extra)}")
        for c, typ in cols:
            if typ not in ("text", "ARRAY") or c in ("key", "case_key", "document", "reader", "profile", "place", "url"):
                continue
            expr = f"array_to_string({c}, ' ; ')" if typ == "ARRAY" else c
            keys = [r[0] for r in conn.execute(f"SELECT key, {expr} FROM {schema}.{name}") if r[1] and STREET.search(r[1])]
            if keys:
                out.append(f"{v}.{c}: {len(keys)} values shaped like a street address (first key {keys[0]})")
    return out


def outside(conn, schema: str = SCHEMA) -> dict:
    T = lambda t: capture.table(schema, t)
    r = conn.execute(f"SELECT pass_id, stated, pages, items FROM {T('capture_passes')} WHERE finished_at IS NOT NULL "
                     "ORDER BY finished_at DESC LIMIT 1").fetchone()
    if r is None:
        return {"ok": False, "detail": "no finished pass of the listing is held"}
    pass_id, stated, pages, items = r
    states = dict(conn.execute(f"SELECT state, count(*) FROM {T('read_items')} WHERE pass_id = %s GROUP BY state",
                               (pass_id,)).fetchall())
    listed = sum(states.values())
    ok = stated is not None and abs(items - stated) <= SLACK and states.get("read", 0) == items
    return {"ok": ok, "pass_id": pass_id, "stated": stated, "pages": pages, "listed": items, "read": states.get("read", 0),
            "set_aside": states.get("set aside", 0), "not_captured": states.get("not captured", 0),
            "ledger": listed, "difference": None if stated is None else items - stated, "old_estate": 112}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.commerce_commission.check")
    ap.add_argument("--database", default="querynz_v4")
    a = ap.parse_args(argv)
    from support import db
    with db.connect(db.READ_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        if conn.execute("SELECT to_regclass('commerce_commission.read_items')").fetchone()[0] is None:
            print(f"{SCHEMA}: check: nothing published yet (no load has run)")
            return 1
        out = outside(conn)
        out["problems"] = reading(conn) + views(conn)
    print(f"{SCHEMA}: check: " + json.dumps(out, default=str))
    return 0 if out["ok"] and not out["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
