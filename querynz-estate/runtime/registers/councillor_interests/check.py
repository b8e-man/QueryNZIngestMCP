"""The lane's one figure against the outside world (contract: the lane).

The source's own count is the Department of Internal Affairs' list of
councils: 78 (data.govt.nz `council-contact-details`, `b6a3c710…`). Exit 1
on any of:

  1. the registers table does not hold every one of the 78 councils
  2. a council whose register is a structured page has no member read, or
     a page read gives a member with no category
  3. a published entry shaped like a street address, a road, an email or a
     phone number (it belongs in councillor_interests_private.entries); a
     row whose heading names real property, a home, an address or a contact,
     or a spouse or partner, without its flag; a column named for an address
     or a contact; or the session or product login able to see the private
     twin (reported by count, never by value: hard limit 11)

Reported, not red: councils by form (html register, pdf register,
per-member files, not reached and why, not found).

    python -m registers.councillor_interests.check [--database querynz_v4] [--schema councillor_interests]
"""
import argparse
import sys

from registers.councillor_interests import capture

SCHEMA = "councillor_interests"
COUNCILS = 78
CONTACTISH = ("address", "phone", "email", "mobile", "postal", "residen", "home", "contact")
#: Postgres regular expressions mirroring read.py's
STREET = (r"\m\d{1,4}[A-Za-z]?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s+(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|"
          r"Terrace|Tce|Crescent|Cres|Lane|Way|Highway|Hwy|Parade|Quay)\M|\m(PO Box|RD ?\d)\M")
EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE = r"(\+64|\m0)\d{1,2}[ -]?\d{3}[ -]?\d{3,4}\M"
#: model_read.ROAD in Postgres's words: a road or highway named, numbered or not; a rural delivery; a lot or a deposited plan
ROAD = (r"\m(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Terrace|Tce|Crescent|Cres|Lane|Highway|Hwy|Parade|Quay|"
        r"Boulevard|Grove|Close|Rise|Esplanade)\M\.?(,|\s*$)|\mState\s+Highway\M|\mRD\s?\d|\mLot\s+\d|\m(DP|SO)\s?\d{3,}")
#: read.REAL_PROPERTY and read.PRIVATE_PERSON in Postgres's words: a heading that must carry its flag
REAL_PROPERTY = r"real\s+property|\mland\M|\mproperty\M|\mhomes?\M|address|residen|contact|phone|e-?mail"
PARTNER = r"\mspouse\M|\mpartner\M|\mwife\M|\mhusband\M|\mfamily members?\M"


def reading(conn, schema: str = SCHEMA) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    n = conn.execute(f"SELECT count(*) FROM {T('registers')}").fetchone()[0]
    if n != COUNCILS:
        out.append(f"{n} councils in the registers table, not {COUNCILS}")
    for sql, what, args in (
        (f"SELECT count(*) FROM {T('registers')} WHERE form = 'html register' AND members_read = 0",
         "structured registers with no member read", None),
        (f"SELECT count(*) FROM {T('interests')} WHERE category ~* %s AND NOT real_property",
         "rows whose heading names real property, a home, an address or a contact, not flagged", (REAL_PROPERTY,)),
        (f"SELECT count(*) FROM {T('interests')} WHERE kind = 'real property' AND NOT real_property",
         "rows the text reader typed real property, not flagged", None),
        (f"SELECT count(*) FROM {T('interests')} WHERE category ~* %s AND NOT of_partner",
         "rows whose heading names a spouse, partner or family member, not flagged", (PARTNER,)),
        (f"SELECT count(*) FROM {T('interests')} i, unnest(i.entries) e WHERE e ~ %s OR e ~ %s OR e ~ %s",
         "entries shaped like an address, an email or a phone number", (STREET, EMAIL, PHONE)),
        (f"SELECT count(*) FROM {T('interests')} i, unnest(i.entries) e WHERE e ~* %s",
         "entries naming a road, a highway, a rural delivery or a title", (ROAD,)),
    ):
        k = conn.execute(sql, args).fetchone()[0]
        if k:
            out.append(f"{k} {what}")
    tables = [capture.table(schema, t).split(".", 1)[1] for t in ("interests", "registers", "documents")]
    cols = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s "
                        "AND table_name = ANY(%s)", (schema, tables)).fetchall()
    bad = [f"{t}.{c}" for t, c in cols if any(w in c.lower() for w in CONTACTISH)]
    if bad:
        out.append(f"columns named for an address or a contact: {', '.join(sorted(bad))}")
    for role in ("qv4_read", "qv4_product"):
        if conn.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AND EXISTS (SELECT 1 FROM pg_namespace "
                        "WHERE nspname = %s AND has_schema_privilege(%s, oid, 'USAGE'))",
                        (role, f"{SCHEMA}_private", role)).fetchone()[0]:
            out.append(f"{role} can see {SCHEMA}_private")
    return out


def main(argv=None) -> int:
    from support import db
    ap = argparse.ArgumentParser(prog="python -m registers.councillor_interests.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    key = db.READ_KEY if a.database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        T = lambda t: capture.table(a.schema, t)
        if conn.execute("SELECT to_regclass(%s)", (T("registers"),)).fetchone()[0] is None:
            print(f"{SCHEMA}: RED: nothing loaded")
            return 1
        for form, n in conn.execute(f"SELECT form, count(*) FROM {T('registers')} GROUP BY 1 ORDER BY 1"):
            print(f"{SCHEMA}: councils, {form}: {n}")
        problems = reading(conn, a.schema)
    for p in problems:
        print(f"{SCHEMA}: RED: {p}")
    print(f"{SCHEMA}: " + ("red" if problems else "green"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
