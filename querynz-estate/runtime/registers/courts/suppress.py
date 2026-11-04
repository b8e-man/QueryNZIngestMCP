"""The suppression lever: one command that withholds a judgment's names
across this lane's tables and records why. Taken as an idea from the old
estate's `courts_register/suppress.py` (dry-run by default, a reason
required, no command that lifts an order) and pointed at this estate's
tables, not the old graph.

    python -m registers.courts.suppress "[2025] NZCA 15" --reason "s 200 CPA order, minute of 28 January 2026"
    python -m registers.courts.suppress <document sha256> --reason "…" --execute

Dry run (the default): prints what the order would reach, as counts only
(the judgments of the citation or the document, the names it would
withhold, the names already withheld); never a name.

`--execute`: records the order in `courts.suppression_orders` (a ledger:
nothing deletes from it), then, in one transaction, flags every name the
order reaches: a caption's party names, every name the text reader
produced on every document of the citation (`courts.people`: judges,
counsel, a public agency and the Crown apart), and the case page's case
name. Nothing is lost (ruling 142, 4 November 2026): the name, its
capacity and the party a counsel acts for are kept whole in
`courts_private.withheld_names`, keyed by the row, flagged suppressed with
the order's reason as the source's words (the session login reads the
schema `courts`, so the name leaves that row); the row keeps its role, its
position and its citation, and the judgment row is marked `suppression`
with the order's reason. The Crown's name and an initial the court printed stay. Every later build reads the ledger
(load.py), so the order outlives the rebuild; `publish` applies it again
after the swap, so an order made during a merge binds too. The published
views read only these tables, so every product that reads them is bound.

The identifying details a document prints (`courts_private.identifiers`)
are gathered under a suppression as without one and are never published,
so the lever has nothing to withhold there and does not touch them.

There is no unsuppress command. A court lifting an order is a person's
decision with a paper trail: the ledger row is withdrawn by hand, with a
note, and the lane re-read.
"""
import argparse
import getpass
import re
import sys

from registers.courts import model_read
from registers.courts import load as L

_SHA = re.compile(r"^[0-9a-f]{64}$")
_CITATION = re.compile(r"^\[\d{4}\] NZ[A-Za-z]{2,6} \d{1,5}$")


def target(ref: str) -> dict:
    ref = (ref or "").strip()
    if _SHA.match(ref):
        return {"citation": None, "document": ref}
    if _CITATION.match(ref):
        return {"citation": ref, "document": None}
    raise SystemExit(f"{ref!r} is neither a neutral citation ([2025] NZCA 15) nor a document's sha256")


def _where(t: dict) -> tuple:
    if t["document"]:
        return "j.document = %s", (t["document"],)
    return "j.citation = %s", (t["citation"],)


def _reach_sql(schema: str, t: dict, shared: bool):
    """The documents the order reaches: the named document, or every
    document of the citation (judgments, releases, transcripts, case pages
    with it in their title), and every document of their case pages' slugs."""
    D = L.table(schema, "documents", shared)
    if t["document"]:
        return (f"SELECT document FROM {D} WHERE document = %s", (t["document"],))
    return (f"WITH c AS (SELECT document, case_slug FROM {D} WHERE citation = %s AND document IS NOT NULL) "
            f"SELECT document FROM c UNION SELECT d.document FROM {D} d JOIN c ON c.case_slug = d.case_slug "
            f"WHERE c.case_slug IS NOT NULL AND d.document IS NOT NULL", (t["citation"],))


def reach(conn, schema: str, t: dict, shared: bool = False) -> dict:
    """What the order reaches, as counts."""
    J, P, N = L.table(schema, "judgments", shared), L.table(schema, "judgment_parties", shared), L.table(schema, "people", shared)
    w, args = _where(t)
    judgments = conn.execute(f"SELECT count(*) FROM {J} j WHERE {w}", args).fetchone()[0]
    to_withhold, already = conn.execute(
        f"SELECT count(*) FILTER (WHERE NOT p.withheld AND NOT p.crown AND NOT p.anonymised AND p.name IS NOT NULL), "
        f"count(*) FILTER (WHERE p.withheld) FROM {P} p JOIN {J} j ON j.key = p.judgment WHERE {w}", args).fetchone()
    rsql, rargs = _reach_sql(schema, t, shared)
    docs = conn.execute(f"SELECT count(*) FROM ({rsql}) r", rargs).fetchone()[0]
    kept = model_read.kept_sql()
    names = conn.execute(f"SELECT count(*) FILTER (WHERE NOT withheld AND name IS NOT NULL AND NOT {kept}), "
                         f"count(*) FILTER (WHERE withheld) FROM {N} WHERE document IN ({rsql})", rargs).fetchone()
    return {"judgments": judgments, "names to withhold": to_withhold, "already withheld": already,
            "documents reached": docs, "model-read names to withhold": names[0], "model-read names already withheld": names[1]}


def withhold(conn, schema: str, t: dict, reason: str, shared: bool = False) -> int:
    """Withhold the names the order reaches; returns how many. Call inside a transaction."""
    J, P, N, C = (L.table(schema, "judgments", shared), L.table(schema, "judgment_parties", shared),
                  L.table(schema, "people", shared), L.table(schema, "cases", shared))
    W = L.table(L.private_of(schema), "withheld_names", shared)
    w, args = _where(t)
    reached = f"SELECT p.key FROM {P} p JOIN {J} j ON j.key = p.judgment WHERE {w} " \
              "AND NOT p.withheld AND NOT p.crown AND NOT p.anonymised AND p.name IS NOT NULL"
    words = f"suppression order: {reason}"
    conn.execute(f"INSERT INTO {W} (key, name, capacity, held_in, document, citation, suppressed, suppression_words) "
                 f"SELECT key, name, capacity, 'judgment_parties', document, citation, true, %s FROM {P} WHERE key IN ({reached}) "
                 "ON CONFLICT (key) DO NOTHING", (words,) + args)
    n = conn.execute(f"UPDATE {P} SET name = NULL, capacity = NULL, withheld = true WHERE key IN ({reached})", args).rowcount
    conn.execute(f"UPDATE {J} j SET suppression = true, withheld = %s, "
                 "suppression_kinds = CASE WHEN 'ledger' = ANY(suppression_kinds) THEN suppression_kinds "
                 f"ELSE suppression_kinds || ARRAY['ledger'] END WHERE {w}", (f"suppression order: {reason}",) + args)
    # the text reader's names on every document the order reaches, the court's officers and the Crown apart
    rsql, rargs = _reach_sql(schema, t, shared)
    kept = model_read.kept_sql()                   # the load's own keep rule (hard limit 16), one rule for both
    named = f"SELECT key FROM {N} WHERE document IN ({rsql}) AND NOT withheld AND name IS NOT NULL AND NOT {kept}"
    nargs = rargs
    conn.execute(f"INSERT INTO {W} (key, name, capacity, held_in, document, citation, for_party, suppressed, suppression_words) "
                 f"SELECT key, name, NULL, 'people', document, citation, for_party, true, %s FROM {N} WHERE key IN ({named}) "
                 "ON CONFLICT (key) DO NOTHING", (words,) + nargs)
    # the party acted for stays in the row: the pub view shows it only where the name is not suppressed
    n += conn.execute(f"UPDATE {N} SET name = NULL, withheld = true WHERE key IN ({named})", nargs).rowcount
    cases = f"SELECT key FROM {C} WHERE document IN ({rsql}) AND case_name IS NOT NULL"
    conn.execute(f"INSERT INTO {W} (key, name, capacity, held_in, document, citation, suppressed, suppression_words) "
                 f"SELECT key, case_name, NULL, 'cases', document, citation, true, %s FROM {C} WHERE key IN ({cases}) "
                 "ON CONFLICT (key) DO NOTHING", (words,) + rargs)
    n += conn.execute(f"UPDATE {C} SET case_name = NULL, suppression = true, withheld = %s WHERE key IN ({cases})",
                      (f"suppression order: {reason}",) + rargs).rowcount
    return n


def apply_all(conn, schema: str = L.SCHEMA, shared: bool = False) -> int:
    """Every order in the ledger applied to the current tables (idempotent)."""
    return sum(withhold(conn, schema, {"citation": o["citation"], "document": o["document"]}, o["reason"], shared)
               for o in L.orders(conn, schema, shared))


def run(conn, ref: str, reason: str, execute: bool = False, schema: str = L.SCHEMA, shared: bool = False,
        by_whom: str = None) -> dict:
    if not (reason or "").strip():
        raise SystemExit("--reason is required: the order and where it is recorded")
    t = target(ref)
    out = {"ref": ref, "executed": execute, **reach(conn, schema, t, shared)}
    if out["judgments"] == 0:
        out["note"] = "no judgment held under this reference: the order is still recorded on --execute and binds when one is read"
    if execute:
        with conn.transaction():
            conn.execute(f"INSERT INTO {L.table(schema, 'suppression_orders', shared)} (citation, document, reason, by_whom) "
                         "VALUES (%s, %s, %s, %s)", (t["citation"], t["document"], reason.strip(), by_whom or getpass.getuser()))
            out["withheld now"] = withhold(conn, schema, t, reason.strip(), shared)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.courts.suppress",
                                 description="Withhold a judgment's names across the courts lane. Dry run unless --execute.")
    ap.add_argument("ref", help="a neutral citation, [2025] NZCA 15, or a document's sha256")
    ap.add_argument("--reason", required=True, help="the order and where it is recorded; never a name")
    ap.add_argument("--execute", action="store_true", help="record the order and withhold (default: dry run)")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=L.SCHEMA)
    a = ap.parse_args(argv)
    from support import db
    with db.connect(db.OWNER_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        conn.execute(L.capture_tables_sql(a.schema))
        out = run(conn, a.ref, a.reason, a.execute, a.schema)
        conn.commit()
    print(("EXECUTED: " if a.execute else "DRY RUN (pass --execute): ") +
          ", ".join(f"{k} {v}" for k, v in out.items() if k not in ("executed",)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
