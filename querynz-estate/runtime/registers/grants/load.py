"""Loading (plan 1b.7): `build(conn, schema, docs)` reads the listed documents
into the reading's tables under `schema`; `publish(conn, staging)` moves them
into `grants` and makes the views, in one transaction. sample.py uses the
same `build`.

What is read (`listing`): the newest national file of class 4 grants landed
(the Department replaces it whole once a year, so an older file is never read
beside it), every Community Matters page the walk landed whose shape is a
record of grants, at the newest hash held for its address, and every file a
society walk landed (`society-file`), at the newest hash for its address: a
file no profile recognises is a catch-log line, and the check tells a list in
an unknown layout from a scan and from a file that is no list. A page whose
address says it is a record of grants and whose shape no profile recognises
is listed too, so it becomes a catch-log line and the check sees it. Items in
equal grants plus set aside, document by document; the build raises if not.

    python -m registers.grants.load [--schema scratch_…] [--database querynz_v4_sample]
    python -m registers.grants.load --job

Every line printed is a count.
"""
import argparse
import json
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.grants import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "grants"
JOB = "qv4-grants-load"
STAGING = "staging_grants_load"
TABLES = ("grants", "recipients", "publishers", "read_documents", "read_set_aside", "read_notes")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "grants": ("key", "publisher_key", "grantor_key", "grantor_as_published", "committee", "recipient_key",
               "recipient_as_published", "recipient_final_as_published", "recipient_kind", "nzbn_as_published", "nzbn",
               "charity_number_as_published", "charity_number", "status", "amount_requested_as_published",
               "amount_granted_as_published", "amount_nzd", "multi_year", "purpose_as_published", "category_1",
               "category_2", "decided_on", "decided_on_as_published", "period", "round", "is_refund", "refunded_on",
               "refunded_on_as_published", "amount_refunded_as_published", "benefits", "territorial_authority",
               "other_territorial_authority", "region", "application_as_published", "reason_as_published",
               "interest_as_published") + _CITE,
    "recipients": ("key", "grantor_key", "publisher_key", "name_as_published", "kind", "nzbn", "charity_number",
                   "grants", "accepted", "declined", "amount_nzd", "first_period", "last_period") + _CITE,
    "publishers": ("key", "name", "kind", "website", "on_departments_list", "licence", "attribution", "role", "grants"),
    "read_documents": ("document", "list", "url", "profile", "records", "grants", "set_aside", "stated"),
    "read_set_aside": ("document", "place", "stage", "reason"),
    "read_notes": ("document", "note", "count"),
}
table = capture.table
_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}(_private)?\.")
#: an address that says it is a record of grants, recognised or not
RECORD_ADDRESS = re.compile(r"(?i)record-of-grants|grants-made|record-of-grant")


def sql(name: str, schema: str = SCHEMA) -> str:
    """tables.sql's reading part, or publish.sql, for `schema` (prefixed names outside the lane's own schema)."""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = capture.READING + text.split(capture.READING, 1)[1]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(lambda m: f"{schema}{'_private' if m.group(1) and schema == SCHEMA else ''}.{pre}", text)


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


def repeat(out, applications: dict) -> None:
    """A society's application printed again in another of its files (Pelorus served its approved list of 28 April
    2026 under the declined list's name too, as other bytes) is read once: the repeat becomes a catch-log line."""
    keep = []
    for g in out.grants:
        k = (g["grantor_key"], g.get("application_as_published"))
        if k[1] and k in applications:
            out.set_aside.append({"document": g["document"], "place": g["place"], "stage": "repeat",
                                  "reason": f"application {k[1]} is read from {applications[k][:12]}…"})
            continue
        if k[1]:
            applications[k] = g["document"]
        keep.append(g)
    out.grants = keep


def build(conn, schema: str, docs: list, read_bytes=read_bytes, only=None) -> dict:
    """`docs`: [(list, url, sha256)], one per document to read; `only`: {sha256: record numbers} (the sample)."""
    t0 = time.monotonic()
    create_tables(conn, schema)
    T = lambda t: table(schema, t)
    grants, ledger, asides, notes = [], [], [], []
    applications = {}
    for lst, url, sha in docs:
        out = read.read_document(read_bytes(sha), sha, (only or {}).get(sha))
        repeat(out, applications)
        grants += out.grants
        asides += out.set_aside
        notes += [{"document": sha, "note": k, "count": v} for k, v in sorted(out.notes.items())]
        ledger.append({"document": sha, "list": lst, "url": url, "profile": out.slug, "records": out.records,
                       "grants": len(out.grants), "set_aside": len(out.set_aside),
                       "stated": json.dumps(out.stated, ensure_ascii=False)})
    keys = [g["key"] for g in grants]
    if len(keys) != len(set(keys)):
        raise AssertionError(f"{SCHEMA}: {len(keys) - len(set(keys))} grant keys repeat")
    recips, link = read.recipients(grants)
    for g in grants:
        g["recipient_key"] = link[g["key"]]
    counted = {}
    for g in grants:
        counted[g["grantor_key"]] = counted.get(g["grantor_key"], 0) + 1
        counted[g["publisher_key"]] = counted.get(g["publisher_key"], 0) + (g["publisher_key"] != g["grantor_key"])
    pubs = [{**p, "grants": counted.get(p["key"], 0)} for p in read.publishers()]
    known = {p["key"] for p in pubs}
    stray = {g["grantor_key"] for g in grants} - known
    if stray:
        raise AssertionError(f"{SCHEMA}: grantors with no publisher row: {sorted(stray)}")
    return {"grants": _copy(conn, T("grants"), COLUMNS["grants"], grants),
            "recipients": _copy(conn, T("recipients"), COLUMNS["recipients"], recips),
            "publishers": _copy(conn, T("publishers"), COLUMNS["publishers"], pubs),
            "documents": _copy(conn, T("read_documents"), COLUMNS["read_documents"], ledger),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "notes": _copy(conn, T("read_notes"), COLUMNS["read_notes"], notes),
            "seconds": round(time.monotonic() - t0, 1)}


def listing(conn, schema: str = SCHEMA) -> list:
    """[(list, url, sha256)]: the newest national file, and every record-of-grants page at its newest hash."""
    T = lambda t: table(schema, t)
    out = []
    r = conn.execute(f"SELECT url, sha256 FROM {T('capture_docs')} WHERE list = 'dia-file' "
                     "ORDER BY at DESC LIMIT 1").fetchone()
    if r:
        out.append(("dia-file", r[0], r[1]))
    rows = conn.execute(
        f"SELECT DISTINCT ON (url) url, sha256, recognised FROM {T('capture_docs')} WHERE list = 'lottery-page' "
        "ORDER BY url, at DESC").fetchall()
    out += [("lottery-page", u, s) for u, s, slug in rows if slug == read.LOTTERY_PAGE or RECORD_ADDRESS.search(u)]
    rows = conn.execute(
        f"SELECT DISTINCT ON (url) url, sha256 FROM {T('capture_docs')} WHERE list = 'society-file' "
        "ORDER BY url, at DESC").fetchall()
    out += [("society-file", u, s) for u, s in rows]
    return out


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging): the newest national file and every record-of-grants page
    held, read under `schema`; with nothing captured the tables are made empty. Problems the reading's check finds
    are logged, as the job logs them. Added by the integrator at the merge of grants-1."""
    from registers.grants import check
    if conn.execute("SELECT to_regclass('grants.capture_docs')").fetchone()[0] is None:
        create_tables(conn, schema)
        log(f"{SCHEMA}: the capture has not run on this database (no grants.capture_docs); nothing read into {schema}")
        return 0
    listed = listing(conn)
    if not listed:
        create_tables(conn, schema)
        log(f"{SCHEMA}: nothing captured yet; nothing read into {schema}")
        return 0
    counts = build(conn, schema, listed)
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['grants']} grants, {counts['recipients']} recipients, {counts['documents']} documents, "
        f"{counts['set_aside']} set aside into {schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["grants"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            cols = ", ".join(COLUMNS[t])
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} ({cols}) SELECT {cols} FROM {table(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def unchanged(conn, listed: list) -> bool:
    if conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.read_documents",)).fetchone()[0] is None:
        return False
    held = {(r[0], r[1]) for r in conn.execute(f"SELECT list, document FROM {SCHEMA}.read_documents")}
    return held == {(e[0], e[2]) for e in listed}


def job(log=print) -> int:
    """qv4-grants-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.grants import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        listed = listing(conn)
        if not listed:
            log(f"{SCHEMA}: nothing captured yet; nothing loaded")
            jobrun.record(JOB, False, "nothing captured yet", started, {})
            return 1
        if unchanged(conn, listed):
            log(f"{SCHEMA}: the listing is the one published; nothing loaded")
            jobrun.record(JOB, True, "unchanged: the listing is the one published", started, {})
            return 0
        with conn.transaction():
            counts = build(conn, STAGING, listed)
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['grants']} grants, {counts['recipients']} recipients, {counts['documents']} documents, "
                  f"{counts['set_aside']} set aside; " + ("; ".join(problems) or "reconciles"))
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
    ap = argparse.ArgumentParser(prog="python -m registers.grants.load")
    ap.add_argument("--schema", default="scratch_grants_full")
    ap.add_argument("--database", default="querynz_v4_sample")
    ap.add_argument("--capture-database", default="querynz_v4")
    ap.add_argument("--capture-schema", default=SCHEMA)
    ap.add_argument("--job", action="store_true")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    if not a.schema.startswith(("scratch_", "staging_")):
        print(f"{SCHEMA}: a session loads only a scratch or staging schema")
        return 2
    key = db.READ_KEY if a.capture_database == "querynz_v4" else db.OWNER_KEY
    with db.connect(key, a.capture_database) as src:
        listed = listing(src, a.capture_schema)
    with db.connect(db.OWNER_KEY, a.database) as conn:
        with conn.transaction():
            counts = build(conn, a.schema, listed)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
