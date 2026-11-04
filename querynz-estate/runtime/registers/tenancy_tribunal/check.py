"""The lane's one check against the outside world (contract: the lane): for
each published month, the source's own count of orders against the number
of orders this lane holds.

The source's count is `numFound` for the month as the listing service gave
it (`listings`, the newest read of each month; `--live` asks again, through
the fetch gate, off-peak only). Held is the number of listing rows (`case_id`)
of that month whose order is landed. Orders leave the source at the end of
their three years, so an old month's source count falls while what is held
does not: a month where held exceeds the source is `past_window`, not a fault.

    compare(source, held)      {"equal": [...], "short": [...], "past_window": [...]}
    python -m registers.tenancy_tribunal.check [--schema tenancy_tribunal] [--live]

Read-only on the database. Exit 1 when any month is short.
"""
import datetime as dt
import sys


def compare(source: dict, held: dict) -> dict:
    """source, held: month → count."""
    out = {"equal": [], "short": [], "past_window": []}
    for m in sorted(set(source) | set(held)):
        s, h = int(source.get(m, 0)), int(held.get(m, 0))
        row = {"month": m, "source": s, "held": h}
        out["equal" if s == h else "short" if h < s else "past_window"].append(row)
    return out


def source_counts(conn, schema: str) -> dict:
    cur = conn.execute(f"SELECT DISTINCT ON (month) month, num_found FROM {schema}.listings ORDER BY month, read_at DESC")
    return {r[0]: r[1] for r in cur}


def held_counts(conn, schema: str) -> dict:
    cur = conn.execute(f"SELECT date_trunc('month', published_date)::date, count(DISTINCT case_id) FROM {schema}.orders "
                       "WHERE document IS NOT NULL GROUP BY 1")
    return {r[0]: r[1] for r in cur}


def live_counts(months) -> dict:
    from registers.tenancy_tribunal import capture as C
    import support.fetchgate as fg
    out = {}
    for m in months:
        f = fg.open_url(C.count_url(m), timeout=60)
        if f.blocked or f.status != 200:
            raise RuntimeError(f"{m:%Y-%m}: {f.blocked or f.status}")
        out[m] = C.parse_listing(f.body)[0]
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    schema = argv[argv.index("--schema") + 1] if "--schema" in argv else "tenancy_tribunal"
    from support import db
    with db.connect(db.READ_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '60s'")
        source, held = source_counts(conn, schema), held_counts(conn, schema)
    if "--live" in argv:
        from registers.tenancy_tribunal import capture as C
        if not C.off_peak(dt.datetime.now().astimezone()):
            print("--live asks the source again and runs off-peak only")
            return 2
        source = live_counts(sorted(source))
    out = compare(source, held)
    for k in ("equal", "short", "past_window"):
        print(f"{k}: {len(out[k])} months, source {sum(r['source'] for r in out[k])}, held {sum(r['held'] for r in out[k])}")
    for r in out["short"]:
        print(f"  short {r['month']:%Y-%m}: source {r['source']}, held {r['held']}")
    return 1 if out["short"] else 0


if __name__ == "__main__":
    sys.exit(main())
