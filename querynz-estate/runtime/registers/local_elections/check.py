"""The lane's one check against the outside world, and the reading's own.

Outside: the newest listings pass asked every seeded council page (listings.tsv)
and each answered and landed, or its failure is recorded by name; a seeded
page that yielded returns at the last load and none today (a council took its
returns down: the 2019 returns' seven years under s 112F ended on 12 October
2026) is red, so the held copy is known to be the only one.

The reading: no row before 2017 (ruling 71); a row for one candidate names
one; no value on the register shaped like an email, a phone number or a
street address (hard limit 15); no column named for an address.

    python -m registers.local_elections.check [--database D] [--schema S]   exit 1 on any problem
"""
import argparse
import re
import sys

from registers.local_elections import capture, read

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\+?64|0)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)")
STREET = re.compile(r"\b\d{1,5}[A-Za-z]?\s+[A-Z][a-zA-Zāēīōū'-]+(?:\s+[A-Z][a-zA-Zāēīōū'-]+)?\s+"
                    r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Lane|Terrace|Tce|Crescent|Cres|Way|Grove|"
                    r"Close|Highway|Hwy|Parade|Court|Ct)\b")
TEXT_COLUMNS = ("candidate_as_listed", "position", "link_words", "context")


def value_problems(rows) -> list:
    """rows: [(key, column, value)]: any value shaped like an email, a phone number or a street address."""
    out = []
    for key, col, v in rows:
        for name, rx in (("an email", EMAIL), ("a phone number", PHONE), ("a street address", STREET)):
            if v and rx.search(v):
                out.append(f"{col} of {key[:80]} holds {name}")
    return out


def reading(conn, schema: str) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    n = conn.execute(f"SELECT count(*) FROM {T('returns')} WHERE election_year < %s", (read.WINDOW_FROM,)).fetchone()[0]
    if n:
        out.append(f"{n} rows before {read.WINDOW_FROM} (ruling 71)")
    n = conn.execute(f"SELECT count(*) FROM {T('returns')} WHERE covers = 'one candidate' AND candidate_as_listed = ''"
                     ).fetchone()[0]
    if n:
        out.append(f"{n} rows for one candidate name nobody")
    vals = []
    for c in TEXT_COLUMNS:
        vals += [(r[0], c, r[1]) for r in conn.execute(f"SELECT key, {c} FROM {T('returns')}")]
    out += value_problems(vals)[:20]
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name LIKE %s",
        (schema, ("" if schema == capture.SCHEMA else capture.SCHEMA + "_") + "%"))]
    out += [f"a column named {c}" for c in cols if re.search(r"address|phone|email", c)]
    return out


def outside(conn, schema: str = capture.SCHEMA, seed_list=None) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    r = conn.execute(f"SELECT max(pass_id) FROM {T('capture_passes')} WHERE mode = 'listings' AND finished_at IS NOT NULL"
                     ).fetchone()
    if not r or r[0] is None:
        return ["no finished listings pass"]
    got = {u: (s, w) for u, s, w in conn.execute(f"SELECT url, state, why FROM {T('capture_pages')} WHERE pass_id = %s",
                                                 (r[0],))}
    for council, _years, url in (seed_list if seed_list is not None else capture.seeds()):
        if url not in got:
            out.append(f"{council}: {url} not asked in the newest pass")
        elif got[url][0] != "landed":
            out.append(f"{council}: {url} {got[url][0]}: {got[url][1]}")
    if conn.execute("SELECT to_regclass(%s)", (T("returns"),)).fetchone()[0] is not None:
        for url, n in conn.execute(f"SELECT listing_url, count(*) FROM {T('returns')} GROUP BY 1"):
            st = got.get(url)
            if st and st[0] == "not found":
                out.append(f"{url}: {n} returns at the last load; the page is gone (the held copies are the only ones)")
    return out


def main(argv=None) -> int:
    from support import db
    ap = argparse.ArgumentParser(prog="python -m registers.local_elections.check")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=capture.SCHEMA)
    a = ap.parse_args(argv)
    key = db.READ_KEY if a.database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.database) as conn:
        problems = outside(conn, a.schema)
        if conn.execute("SELECT to_regclass(%s)", (capture.table(a.schema, "returns"),)).fetchone()[0] is not None:
            problems += reading(conn, a.schema)
    for p in problems:
        print(f"local_elections: {p}")
    print(f"local_elections: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
