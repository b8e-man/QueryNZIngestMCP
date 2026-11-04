"""The lane's one figure against the outside world (contract: the lane).

The source's own count is each listing's grid: the rows the council's own
page shows, counted at capture apart from the reader. Exit 1 on any of:

  1. no listing is held, or fewer instances answer than `FLOOR_INSTANCES`
     (21 of 24 on 22 October 2026: Kāpiti and Hawke's Bay answered 404,
     Christchurch's page tripped the gate's challenge check)
  2. the reading does not reconcile: a listing read whose meetings differ
     from its grid's rows, a meeting cited to a listing not in the ledger, a
     document whose meeting is not held, minutes marked landed with no hash
  3. a column named for a venue or an address, or a body name shaped like a
     street address (reported by key, never by value: hard limit 15)

Reported, not red: instances held (and why, by count), minutes not yet
captured, held by the old estate, failed.

    python -m registers.council_minutes.check [--database querynz_v4] [--schema council_minutes]
"""
import argparse
import sys

from registers.council_minutes import capture

SCHEMA = "council_minutes"
FLOOR_INSTANCES = 21
ADDRESSISH = ("venue", "address", "street", "location", "postal", "physical")
#: a street address's shape, in Postgres's regular expressions
STREET = (r"\m\d{1,4}[A-Za-z]?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s+(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|"
          r"Terrace|Tce|Crescent|Cres|Lane|Way|Highway|Hwy|Parade|Quay)\M")


def reading(conn, schema: str = SCHEMA) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    for sql, what in (
        # the rows held, counted, against the grid's own count: a host's newest listing wins every row it shows
        (f"SELECT count(*) FROM (SELECT DISTINCT ON (host) document, grid_rows FROM {T('read_listings')} "
         "WHERE state = 'read' ORDER BY host, asked_at DESC NULLS LAST) l "
         f"WHERE (SELECT count(*) FROM {T('meetings')} m WHERE m.document = l.document) + "
         f"(SELECT count(*) FROM {T('read_set_aside')} s WHERE s.document = l.document AND s.place IS NOT NULL) "
         "<> l.grid_rows", "listings whose rows held differ from the grid's own count"),
        (f"SELECT count(*) FROM {T('meetings')} m WHERE NOT EXISTS (SELECT 1 FROM {T('read_listings')} l "
         "WHERE l.document = m.document AND l.state = 'read')", "meetings with no ledger line"),
        (f"SELECT count(*) FROM {T('documents')} d WHERE NOT EXISTS (SELECT 1 FROM {T('meetings')} m "
         "WHERE m.key = d.meeting_key)", "documents whose meeting is not held"),
        (f"SELECT count(*) FROM {T('meetings')} WHERE minutes_held = 'landed' AND minutes_sha256 IS NULL",
         "minutes marked landed with no hash"),
        (f"SELECT count(*) FROM {T('meetings')} WHERE body ~ %s", "body names shaped like a street address"),
        # the minutes' reading (2 November 2026): every landed minutes PDF has a ledger line; no row cites a PDF the
        # ledger does not mark read; no attendee or declaring member is shaped like an address or a contact; no
        # resolution has no text
        (f"SELECT count(*) FROM {T('meetings')} m WHERE m.minutes_held = 'landed' AND m.minutes_sha256 IS NOT NULL "
         f"AND NOT EXISTS (SELECT 1 FROM {T('minutes_read')} r "
         "WHERE r.document = m.minutes_sha256)", "landed minutes with no line in the minutes ledger"),
        (f"SELECT (SELECT count(*) FROM {T('attendance')} a WHERE NOT EXISTS (SELECT 1 FROM {T('minutes_read')} r "
         f"WHERE r.document = a.document AND r.state = 'read')) + (SELECT count(*) FROM {T('resolutions')} x WHERE NOT "
         f"EXISTS (SELECT 1 FROM {T('minutes_read')} r WHERE r.document = x.document AND r.state = 'read')) + "
         f"(SELECT count(*) FROM {T('declarations')} d WHERE NOT EXISTS (SELECT 1 FROM {T('minutes_read')} r "
         "WHERE r.document = d.document AND r.state = 'read'))", "minutes rows citing a PDF the ledger does not mark read"),
        (f"SELECT (SELECT count(*) FROM {T('attendance')} WHERE name ~ %s OR name ~ '@|\\mPO Box\\M') + "
         f"(SELECT count(*) FROM {T('declarations')} WHERE member ~ %s OR member ~ '@')",
         "attendees or declaring members shaped like an address or a contact"),
        (f"SELECT count(*) FROM {T('resolutions')} WHERE coalesce(btrim(text), '') = ''", "resolutions with no text"),
    ):
        n = conn.execute(sql, (STREET,) * sql.count("%s") or None).fetchone()[0]
        if n:
            out.append(f"{n} {what}")
    tables = [capture.table(schema, t).split(".", 1)[1] for t in ("meetings", "documents")]
    cols = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s "
                        "AND table_name = ANY(%s)", (schema, tables)).fetchall()
    bad = [f"{t}.{c}" for t, c in cols if any(w in c.lower() for w in ADDRESSISH)]
    if bad:
        out.append(f"columns named for a venue or an address: {', '.join(sorted(bad))}")
    return out


def outside(conn, schema: str = SCHEMA) -> tuple:
    """(problems, counts) of the capture's record and the published reading."""
    T = lambda t: capture.table(schema, t)
    problems, counts = [], {}
    if conn.execute("SELECT to_regclass(%s)", (T("capture_listings"),)).fetchone()[0] is None:
        return ["no capture record: the capture has never run"], counts
    answered = conn.execute(f"SELECT count(DISTINCT host) FROM {T('capture_listings')} WHERE sha256 IS NOT NULL").fetchone()[0]
    counts["instances answering"] = answered
    if answered == 0:
        problems.append("no listing is held")
    elif answered < FLOOR_INSTANCES:
        problems.append(f"{answered} instances answer, under the floor of {FLOOR_INSTANCES}")
    for why, n in conn.execute(f"SELECT split_part(why, ':', 1), count(*) FROM {T('capture_held_hosts')} GROUP BY 1"):
        counts[f"instances held ({why})"] = n
    for state, n in conn.execute(f"SELECT state, count(*) FROM {T('capture_documents')} GROUP BY 1 ORDER BY 1"):
        counts[f"minutes {state}"] = n
    if conn.execute("SELECT to_regclass(%s)", (T("meetings"),)).fetchone()[0] is not None:
        for held, n in conn.execute(f"SELECT minutes_held, count(*) FROM {T('meetings')} GROUP BY 1 ORDER BY 1"):
            counts[f"meetings: {held}"] = n
        problems += reading(conn, schema)
    return problems, counts


def main(argv=None) -> int:
    from support import db
    ap = argparse.ArgumentParser(prog="python -m registers.council_minutes.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    key = db.READ_KEY if a.database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        problems, counts = outside(conn, a.schema)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    for p in problems:
        print(f"{SCHEMA}: RED: {p}")
    print(f"{SCHEMA}: " + ("red" if problems else "green"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
