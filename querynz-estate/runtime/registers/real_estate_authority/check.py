"""The lane's one check against the outside world (contract: the lane): for
each year the database lists, its own "Search Results (N)" against the
cases this lane holds for that year (abstract and every linked PDF landed).

The source's count is the newest listing read of the year (`listings`,
page 1); `--live` asks again through the fetch gate, off-peak only. A year
where held exceeds the source is `withdrawn` (the database dropped a
decision we hold), not a fault; a year short is a fault until the capture
reaches it.

    compare(source, held)      {"equal": [...], "short": [...], "withdrawn": [...]}
    python -m registers.real_estate_authority.check [--schema real_estate_authority] [--live]

Read-only on the database. Exit 1 when any year is short.
"""
import datetime as dt
import sys


def compare(source: dict, held: dict) -> dict:
    out = {"equal": [], "short": [], "withdrawn": []}
    for y in sorted(set(source) | set(held)):
        s, h = int(source.get(y, 0)), int(held.get(y, 0))
        out["equal" if s == h else "short" if h < s else "withdrawn"].append({"year": y, "source": s, "held": h})
    return out


def source_counts(conn, schema: str) -> dict:
    cur = conn.execute(f"SELECT DISTINCT ON (year) year, num_found FROM {schema}.listings ORDER BY year, read_at DESC")
    return {r[0]: r[1] for r in cur}


def held_counts(conn, schema: str) -> dict:
    cur = conn.execute(f"SELECT year, count(*) FROM {schema}.cases WHERE captured_at IS NOT NULL GROUP BY year")
    return {r[0]: r[1] for r in cur}


#: the share of held abstracts the reading may set aside before it is red
SET_ASIDE_SHARE = 0.01


def reading(conn, schema: str, held_schema: str = "real_estate_authority") -> list:
    """The reading's own checks, under `schema`: every landed abstract read or set aside, at most SET_ASIDE_SHARE set
    aside, no name or licence number on a suppressed decision's parties, no penalty text on a suppressed decision held
    for a product to blank by mistake, and every party's decision present. Returns the problems (empty when green)."""
    one = lambda q, *a: conn.execute(q, a).fetchone()[0]
    out = []
    held = one(f"SELECT count(*) FROM {held_schema}.cases WHERE abstract IS NOT NULL")
    read_n, aside = one(f"SELECT count(*) FROM {schema}.decisions"), one(f"SELECT count(*) FROM {schema}.read_set_aside")
    if read_n + aside != held:
        out.append(f"{held} abstracts held, {read_n} read and {aside} set aside")
    if held and aside > SET_ASIDE_SHARE * held:
        out.append(f"{aside} of {held} abstracts set aside, over {SET_ASIDE_SHARE:.0%}")
    leaked = one(f"SELECT count(*) FROM {schema}.parties WHERE suppressed AND (name IS NOT NULL OR licence_number IS NOT NULL)")
    if leaked:
        out.append(f"{leaked} parties of suppressed decisions carry a name or a number")
    pen = one(f"SELECT count(*) FROM {schema}.decisions WHERE suppressed AND penalty IS NOT NULL")
    if pen:
        out.append(f"{pen} suppressed decisions carry penalty text")
    # ruling 142: a suppressed decision's names are kept whole in the private twin, keyed by the party
    see = one("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s AND has_schema_privilege(current_user, oid, "
              "'USAGE'))", f"{schema}_private")
    lost = see and one(f"SELECT count(*) FROM {schema}.parties p WHERE p.suppressed AND NOT EXISTS (SELECT 1 FROM "
                       f"{schema}_private.suppressed_parties s WHERE s.key = p.key)")
    if lost:
        out.append(f"{lost} parties of suppressed decisions with no name kept in the private twin")
    orphans = one(f"SELECT count(*) FROM {schema}.parties p WHERE NOT EXISTS "
                  f"(SELECT 1 FROM {schema}.decisions d WHERE d.key = p.decision_key)")
    if orphans:
        out.append(f"{orphans} parties with no decision")
    return out


def live_counts(years) -> dict:
    from registers.real_estate_authority import capture as C
    import support.fetchgate as fg
    out = {}
    for y in years:
        f = fg.open_url(C.listing_url(y), timeout=60)
        if f.blocked or f.status != 200:
            raise RuntimeError(f"{y}: {f.blocked or f.status}")
        out[y] = C.parse_listing(f.body)[0]
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    schema = argv[argv.index("--schema") + 1] if "--schema" in argv else "real_estate_authority"
    from support import db
    with db.connect(db.READ_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '60s'")
        source, held = source_counts(conn, schema), held_counts(conn, schema)
    if "--live" in argv:
        from registers.real_estate_authority import capture as C
        if not C.off_peak(dt.datetime.now().astimezone()):
            print("--live asks the source again and runs off-peak only")
            return 2
        source = live_counts(sorted(source))
    out = compare(source, held)
    for k in ("equal", "short", "withdrawn"):
        print(f"{k}: {len(out[k])} years, source {sum(r['source'] for r in out[k])}, held {sum(r['held'] for r in out[k])}")
    for r in out["short"]:
        print(f"  short {r['year']}: source {r['source']}, held {r['held']}")
    return 1 if out["short"] else 0


if __name__ == "__main__":
    sys.exit(main())
