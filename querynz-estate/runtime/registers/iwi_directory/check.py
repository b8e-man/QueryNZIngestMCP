"""The lane's one figure against the outside world (contract: the lane).

The source's own count is the site's: the iwi its 13 region maps and its
local and regional authority lists link (117 distinct iwi on 22 October
2026). Exit 1 on any of:

  1. no finished walk is held, or one is held and nothing of it is published
     (the load refused: its own red line names why)
  2. an iwi the site's own maps and lists link is not read (not landed, set
     aside, or not the iwi page's shape), or an iwi page is read that no map
     or list links
  3. the reading does not reconcile: a page in the ledger as read with no
     rows, a relation or settlement whose entity is not held, a hapū whose
     iwi is not held, a role flag no rule names (`other: …`: the profile must
     learn it before the row is trusted), a settlement row keyed other than
     by its entity and settlement, or named by the flag's own words
  4. a table or view carries a column named for a person's contact or an
     address, or a text value shaped like an email address or a phone number
     (reported by key, never by value: hard limit 15)

Every line printed is a count.

    python -m registers.iwi_directory.check [--database querynz_v4] [--schema iwi_directory]
    python -m registers.iwi_directory.check --database querynz_v4_sample --schema scratch_… --views scratch_….v_ \
        --capture-database querynz_v4      (a session's scratch build of the live walk)
"""
import argparse
import re
import sys

from registers.iwi_directory import capture

SCHEMA = "iwi_directory"
VIEWS = ("iwi_directory_entities", "iwi_directory_relations", "iwi_directory_settlements")
CONTACTISH = ("email", "phone", "mobile", "postal", "physical", "address", "contact", "chair", "ceo", "person")
EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
#: a New Zealand phone number's shape, in Postgres's regular expressions (\m, \M: the start and end of a word)
PHONE = r"(\+64|\m0)\d{1,2}[ -]?\d{3}[ -]?\d{3,4}\M"
TEXT_COLUMNS = ("name", "listed_as", "region", "legal_entity", "governance_structure", "hapu_represented",
                "area_of_interest", "local_authorities", "primary_purpose", "website", "wharenui", "location",
                "last_updated")


def reading(conn, schema: str = SCHEMA) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    n = conn.execute(f"SELECT count(*) FROM {T('read_pages')} WHERE state = 'read' AND kind IN ('iwi', 'omo', "
                     "'nontribal') AND entities = 0").fetchone()[0]
    if n:
        out.append(f"{n} pages read with no entity")
    n = conn.execute(f"SELECT count(*) FROM {T('entities')} e WHERE NOT EXISTS (SELECT 1 FROM {T('read_pages')} p "
                     "WHERE p.document = e.document AND p.state = 'read')").fetchone()[0]
    if n:
        out.append(f"{n} entities with no ledger line")
    n = conn.execute(f"SELECT count(*) FROM {T('relations')} r WHERE r.relation <> 'iwi in region' AND NOT EXISTS "
                     f"(SELECT 1 FROM {T('entities')} e WHERE e.key = r.from_key)").fetchone()[0]
    if n:
        out.append(f"{n} relations from an entity not held")
    n = conn.execute(f"SELECT count(*) FROM {T('relations')} r WHERE r.to_key IS NOT NULL AND NOT EXISTS "
                     f"(SELECT 1 FROM {T('entities')} e WHERE e.key = r.to_key)").fetchone()[0]
    if n:
        out.append(f"{n} relations to an entity not held")
    n = conn.execute(f"SELECT count(*) FROM {T('settlements')} s WHERE NOT EXISTS (SELECT 1 FROM {T('entities')} e "
                     "WHERE e.key = s.entity_key)").fetchone()[0]
    if n:
        out.append(f"{n} settlements whose entity is not held")
    n = conn.execute(f"SELECT count(*) FROM {T('settlements')} WHERE key <> entity_key || '|' || "
                     "coalesce(settlement_key, 'no settlement named')").fetchone()[0]
    if n:
        out.append(f"{n} settlement rows not keyed by their entity and settlement (a key must name one row)")
    n = conn.execute(f"SELECT count(*) FROM {T('settlements')} WHERE name ~* "
                     "'^post[- ](treaty )?settlement governance entity'").fetchone()[0]
    if n:
        out.append(f"{n} settlements named by the post-settlement flag's own words")
    n = conn.execute(f"SELECT count(*) FROM {T('entities')} WHERE kind = 'hapū' AND iwi_key NOT IN "
                     f"(SELECT key FROM {T('entities')} WHERE kind = 'iwi')").fetchone()[0]
    if n:
        out.append(f"{n} hapū whose iwi is not held")
    n = conn.execute(f"SELECT count(*) FROM {T('entities')} WHERE EXISTS (SELECT 1 FROM unnest(flags) f "
                     "WHERE f LIKE 'other: %')").fetchone()[0]
    if n:
        out.append(f"{n} entities carry a role flag no rule names")
    n = conn.execute(f"SELECT count(*) FROM {T('entities')} e WHERE e.kind = 'governance entity' AND NOT EXISTS "
                     f"(SELECT 1 FROM {T('settlements')} s WHERE s.entity_key = e.key)").fetchone()[0]
    if n:
        out.append(f"{n} governance entities name no settlement")
    out += contact_shapes(conn, T("entities"), "entities")
    return out


def contact_shapes(conn, name: str, label: str) -> list:
    out = []
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema || '.' || table_name = %s",
        (name,))]
    bad = [c for c in cols if any(w in c.lower() for w in CONTACTISH)]
    if bad:
        out.append(f"{label} carries {len(bad)} columns named for a contact or an address")
    present = [c for c in TEXT_COLUMNS if c in cols]
    if present:
        cond = " OR ".join(f"{c} ~ %s OR {c} ~ %s" for c in present)
        args = [x for _ in present for x in (EMAIL, PHONE)]
        rows = conn.execute(f"SELECT key FROM {name} WHERE {cond} ORDER BY key LIMIT 20", args).fetchall()
        if rows:
            out.append(f"{label}: {len(rows)} rows with a value shaped like an email or a phone number, e.g. key "
                       f"{rows[0][0]}")
    return out


def views(conn, prefix: str = "pub.") -> list:
    out = []
    for v in VIEWS:
        name = prefix + v
        out += contact_shapes(conn, name, v) if v == "iwi_directory_entities" else []
    return out


def outside(conn, schema: str = SCHEMA, listed=None) -> list:
    """`listed`: the walk's pages, where the walk is held elsewhere than `schema` (a session's scratch build)."""
    T = lambda t: capture.table(schema, t)
    from registers.iwi_directory import load
    if not (load.listing(conn, schema) if listed is None else listed):
        return ["no finished walk of the site is held"]
    if not conn.execute(f"SELECT count(*) FROM {T('read_pages')}").fetchone()[0]:
        return ["a finished walk is held and none of it is published: the load has not run, or refused (its job "
                "record says why)"]
    linked = {r[0] for r in conn.execute(f"SELECT DISTINCT unnest(iwi_links) FROM {T('read_pages')}")}
    read_iwi = {r[0].rsplit("/", 1)[1] for r in conn.execute(f"SELECT key FROM {T('entities')} WHERE kind = 'iwi'")}
    out = []
    if not linked:
        out.append("no region map or authority list read: nothing to count the iwi against")
    missing, extra = sorted(linked - read_iwi), sorted(read_iwi - linked)
    print(f"{SCHEMA}: {len(linked)} iwi linked by the site's own maps and lists; {len(read_iwi)} iwi pages read")
    if missing:
        out.append(f"{len(missing)} iwi the site links are not read, e.g. {missing[0]}")
    if extra:
        out.append(f"{len(extra)} iwi pages read that no map or list links, e.g. {extra[0]}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.iwi_directory.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--views", default="pub.", help="the prefix the views are read under")
    ap.add_argument("--capture-database", help="where the walk is held, for a scratch build (load.py's own option)")
    ap.add_argument("--capture-schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db
    from registers.iwi_directory import load
    key = lambda d: db.READ_KEY if d == "querynz_v4" else db.OWNER_KEY
    listed = None
    if a.capture_database:
        with db.connect(key(a.capture_database), a.capture_database) as src:
            listed = load.listing(src, a.capture_schema)
    with db.connect(key(a.database), a.database) as conn:
        problems = outside(conn, a.schema, listed)
        if not problems or problems[0] != "no finished walk of the site is held":
            problems += reading(conn, a.schema) + views(conn, a.views)
    for p in problems:
        print(f"{SCHEMA}: RED: {p}")
    print(f"{SCHEMA}: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
