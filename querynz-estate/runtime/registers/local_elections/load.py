"""Loading (plan 1b.7): `build(conn, schema, pages, files)` reads the listing
pages the capture holds into the register under `schema`; `load(conn,
schema)` is the merge gate's staging step and `publish(conn, staging)` moves
the tables into `local_elections` and makes the views, in one transaction.
sample.py uses the same `build`.

A listing page is read as `read.read_listing` reads it and given a profile by
its shape (`shape_of`). A return linked from two pages is one row, cited to
the first page in address order. A row outside the window (ruling 71) is
counted on its page and not a row. Pages in equal pages read, followed only,
holding no returns, or set aside; the build raises if not. The returns
themselves are held by hash and not read (ruling 79): the row says whether
its file is held, and by which hash.

    python -m registers.local_elections.load [--schema scratch_local_elections_full] [--capture-schema scratch_local_elections_capture]
    python -m registers.local_elections.load --job

Every line printed is a count.
"""
import argparse
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.local_elections import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "local_elections"
JOB = "qv4-local-elections-load"
STAGING = "staging_local_elections_load"
READER = "registers/local_elections/read.py read_listing"
TABLES = ("read_pages", "returns", "read_set_aside")
#: profile slug → version (profiles-proposed.jsonl)
PROFILES = {"council-returns-listing": 1, "council-returns-results-table": 1, "council-returns-hub": 1,
            "local-candidate-return-file": 1}
COLUMNS = {
    "read_pages": ("council", "url", "document", "profile", "state", "rows_read", "not_returns", "out_of_window"),
    "returns": ("key", "council", "election_year", "by_election", "covers", "candidate_as_listed", "position",
                "return_kind", "link_words", "file_url", "file_document", "file_state", "listing_url", "context",
                "document", "place", "reader", "profile", "profile_version"),
    "read_set_aside": ("document", "place", "stage", "reason"),
}
table = capture.table
_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}\.")


def sql(name: str, schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = "-- ── the reading" + text.split("-- ── the reading", 1)[1]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(f"{schema}.{pre}", text)


def create_tables(conn, schema: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t)} CASCADE")
    conn.execute(sql("tables.sql", schema))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(row.get(c) for c in cols))
            n += 1
    return n


def shape_of(out: dict) -> str:
    """The page's profile, by shape: rows whose link words name nobody (a results table's 'View return') are the
    results-table shape; other rows, a listing; none, a hub (sub-listings or nothing)."""
    rows = out["rows"]
    if not rows:
        return "council-returns-hub"
    generic = sum(1 for r in rows if read.GENERIC_WORDS.fullmatch((r["link_words"] or "").strip()))
    return "council-returns-results-table" if generic * 2 > len(rows) else "council-returns-listing"


def build(conn, schema: str, pages: list, files: dict, read_bytes=read_bytes) -> dict:
    """`pages`: [{council, url, sha256, seed_year}], the newest landed copy of each listing page; `files`:
    {file url: (state, sha256)} from the capture."""
    t0 = time.monotonic()
    create_tables(conn, schema)
    T = lambda t: table(schema, t)
    ledger, rows, asides, seen = [], [], [], set()
    for p in sorted(pages, key=lambda p: p["url"]):
        try:
            data = read_bytes(p["sha256"])
            out = read.read_listing(data, p["url"], p["council"], p.get("seed_year"),
                                    capture.council_words(p["council"], p["url"]))
        except (OSError, read.NotTheShape) as exc:
            asides.append({"document": p["sha256"], "place": p["url"], "stage": "read", "reason": str(exc)[:300]})
            ledger.append({"council": p["council"], "url": p["url"], "document": p["sha256"], "profile": "",
                           "state": "set aside", "rows_read": 0, "not_returns": 0, "out_of_window": 0})
            continue
        profile = shape_of(out)
        n_in, n_out = 0, 0
        for r in out["rows"]:
            if r["election_year"] is not None and r["election_year"] < read.WINDOW_FROM:
                n_out += 1
                continue
            key = f"{p['council']}|{r['file_url']}"
            if key in seen:
                continue
            seen.add(key)
            state, sha = files.get(r["file_url"], ("not asked", None))
            rows.append(dict(r, key=key, file_document=sha, file_state=state, document=p["sha256"], place=p["url"],
                             reader=READER, profile=profile, profile_version=PROFILES[profile]))
            n_in += 1
        state = "read" if out["rows"] else ("followed only" if out["follow"] else "no returns")
        ledger.append({"council": p["council"], "url": p["url"], "document": p["sha256"], "profile": profile,
                       "state": state, "rows_read": n_in, "not_returns": sum(out["not_returns"].values()),
                       "out_of_window": n_out})
    if len(ledger) != len({p["url"] for p in pages}):
        raise AssertionError(f"{SCHEMA}: {len(pages)} pages held, {len(ledger)} in the ledger")
    return {"returns": _copy(conn, T("returns"), COLUMNS["returns"], rows),
            "pages": _copy(conn, T("read_pages"), COLUMNS["read_pages"], ledger),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "seconds": round(time.monotonic() - t0, 1)}


def held(conn, schema: str = SCHEMA):
    """(pages, files) the capture holds under `schema`: the newest landed copy of each listing page."""
    T = lambda t: table(schema, t)
    if conn.execute("SELECT to_regclass(%s)", (T("capture_pages"),)).fetchone()[0] is None:
        return [], {}
    pages = [{"council": r[0], "url": r[1], "seed_year": r[2], "sha256": r[3]} for r in conn.execute(
        f"SELECT DISTINCT ON (url) council, url, seed_year, sha256 FROM {T('capture_pages')} "
        f"WHERE state = 'landed' ORDER BY url, pass_id DESC")]
    files = {r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT url, state, sha256 FROM {T('capture_files')}")}
    return pages, files


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging): what the capture holds, read under `schema`; with nothing
    held the tables are made empty."""
    from registers.local_elections import check
    pages, files = held(conn)
    if not pages:
        create_tables(conn, schema)
        log(f"{SCHEMA}: no listing page is held; nothing read into {schema}")
        return 0
    counts = build(conn, schema, pages, files)
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['returns']} returns from {counts['pages']} pages, {counts['set_aside']} set aside into "
        f"{schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["returns"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def job(log=print) -> int:
    """qv4-local-elections-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.local_elections import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        pages, files = held(conn)
        if not pages:
            log(f"{SCHEMA}: no listing page is held; nothing loaded")
            jobrun.record(JOB, False, "no listing page is held", started, {})
            return 1
        with conn.transaction():
            counts = build(conn, STAGING, pages, files)
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['returns']} returns from {counts['pages']} pages, {counts['set_aside']} set aside; "
                  + ("; ".join(problems) or "reconciles"))
        if problems:
            log(f"{SCHEMA}: RED, nothing published: " + detail)
            jobrun.record(JOB, False, "nothing published: " + detail, started, {})
            return 1
        publish(conn, STAGING, log)
    jobrun.record(JOB, True, "published: " + detail, started, counts)
    log(f"{SCHEMA}: published: " + detail)
    return 0


def main(argv=None) -> int:
    from support import db
    ap = argparse.ArgumentParser(prog="python -m registers.local_elections.load")
    ap.add_argument("--schema", default="scratch_local_elections_full")
    ap.add_argument("--database", default="querynz_v4_sample")
    ap.add_argument("--capture-database", default="querynz_v4_sample")
    ap.add_argument("--capture-schema", default="scratch_local_elections_capture")
    ap.add_argument("--publish", action="store_true", help="also make the views (in the sample database only)")
    ap.add_argument("--job", action="store_true")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    if not a.schema.startswith(("scratch_", "staging_")):
        print(f"{SCHEMA}: a session loads only a scratch or staging schema")
        return 2
    key = db.READ_KEY if a.capture_database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.capture_database) as src:
        pages, files = held(src, a.capture_schema)
    with db.connect(db.OWNER_KEY, a.database) as conn:
        with conn.transaction():
            counts = build(conn, a.schema, pages, files)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
