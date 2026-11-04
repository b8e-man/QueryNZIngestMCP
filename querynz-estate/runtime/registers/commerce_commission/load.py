"""Loading (plan 1b.7): `build(conn, schema, entries)` reads the listed
entries into the reading's tables under `schema`; `publish(conn, staging)`
moves them into `commerce_commission` and makes the views, in one
transaction. sample.py uses the same `build`.

What is read: every entry the newest finished pass of the listing lists, at
the newest hash held for it, and every entry an older finished pass listed
and the newest does not, kept with `taken_down_on`, the date of the first
finished pass that no longer listed it (ruling 142). An entry listed and not yet captured is a ledger line ('not
captured'), never a row. Items in equal cases read plus set aside plus not
captured; the build raises if they do not.

    python -m registers.commerce_commission.load [--schema scratch_…] [--database querynz_v4_sample]
    python -m registers.commerce_commission.load --job

Every line printed is a count.
"""
import argparse
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.commerce_commission import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "commerce_commission"
JOB = "qv4-commerce-commission-load"
STAGING = "staging_commerce_commission_load"
TABLES = ("read_items", "cases", "parties", "read_set_aside")
#: in the private twin (ruling 142): what a suppression the page states covers, kept whole
PRIVATE_TABLES = ("suppressed_names", "suppressed_cases", "contacts")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "read_items": ("list", "slug", "pass_id", "document", "state", "parties", "taken_down_on"),
    "cases": ("key", "slug", "case_number", "title", "title_withheld", "category", "sub_category", "act_section", "acts",
              "sections", "industry", "status", "outcome", "opened_on", "closed_on", "action_on", "url", "taken_down_on") + _CITE,
    "parties": ("key", "case_key", "ordinal", "name", "trading_as", "withheld", "withheld_by", "organisation",
                "company_number", "split_from") + _CITE,
    "read_set_aside": ("document", "place", "stage", "reason"),
    "suppressed_names": ("key", "case_key", "ordinal", "name", "trading_as", "company_number", "suppressed_by") + _CITE,
    "suppressed_cases": ("key", "slug", "title", "url", "suppressed_by") + _CITE,
    "contacts": ("key", "contact") + _CITE,
}
table = capture.table


def ptable(schema: str, t: str) -> str:
    """A private table: in `commerce_commission_private` for the lane's own schema, beside the rest in any other."""
    return f"{SCHEMA}_private.{t}" if schema == SCHEMA else table(schema, t)
_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}(_private)?\.")


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
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}_private")
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t)} CASCADE")
    for t in PRIVATE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {ptable(schema, t)} CASCADE")
    conn.execute(sql("tables.sql", schema))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(row.get(c) for c in cols))
            n += 1
    return n


def build(conn, schema: str, entries: list, read_bytes=read_bytes) -> dict:
    """`entries`: [(list, slug, url, sha256 or None, pass_id[, taken_down_on])], one per entry ever listed: the newest
    pass's, and one taken off the register since (kept, flagged with the date; ruling 142)."""
    t0 = time.monotonic()
    create_tables(conn, schema)
    T = lambda t: table(schema, t)
    ledger, cases, parties, asides, names, kept, contacts = [], [], [], [], [], [], []
    for lst, slug, url, sha, pass_id, *rest in entries:
        down = rest[0] if rest else None
        if sha is None:
            ledger.append({"list": lst, "slug": slug, "pass_id": pass_id, "document": None, "state": "not captured",
                           "parties": 0, "taken_down_on": down})
            continue
        out = read.read_entry(read_bytes(sha), sha, slug, url)
        asides += out["set_aside"]
        if out["case"] is None:
            ledger.append({"list": lst, "slug": slug, "pass_id": pass_id, "document": sha, "state": "set aside",
                           "parties": 0, "taken_down_on": down})
            continue
        cases.append({**out["case"], "taken_down_on": down})
        parties += out["parties"]
        names += out.get("suppressed_names") or []
        kept += [out["suppressed_case"]] if out.get("suppressed_case") else []
        contacts += [out["contact"]] if out.get("contact") else []
        ledger.append({"list": lst, "slug": slug, "pass_id": pass_id, "document": sha, "state": "read",
                       "parties": len(out["parties"]), "taken_down_on": down})
    if len(ledger) != len({(e[0], e[1]) for e in entries}):
        raise AssertionError(f"{SCHEMA}: {len(entries)} entries listed, {len(ledger)} in the ledger")
    return {"cases": _copy(conn, T("cases"), COLUMNS["cases"], cases),
            "parties": _copy(conn, T("parties"), COLUMNS["parties"], parties),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "listed": _copy(conn, T("read_items"), COLUMNS["read_items"], ledger),
            "suppressed_names": _copy(conn, ptable(schema, "suppressed_names"), COLUMNS["suppressed_names"], names),
            "suppressed_cases": _copy(conn, ptable(schema, "suppressed_cases"), COLUMNS["suppressed_cases"], kept),
            "contacts": _copy(conn, ptable(schema, "contacts"), COLUMNS["contacts"], contacts),
            "taken_down": sum(1 for l in ledger if l["taken_down_on"]),
            "not_captured": sum(1 for l in ledger if l["state"] == "not captured"),
            "seconds": round(time.monotonic() - t0, 1)}


def listing(conn, schema: str = SCHEMA) -> list:
    """Every entry the newest finished pass of each listing lists, with the newest hash held for it, then every entry an
    older finished pass listed and the newest does not: taken off the register, kept, with the date of the first
    finished pass after its last listing (ruling 142: a row the publisher takes down stays, flagged)."""
    T = lambda t: table(schema, t)
    out = []
    for lst in capture.LISTS:
        r = conn.execute(f"SELECT max(pass_id) FROM {T('capture_passes')} WHERE list = %s AND finished_at IS NOT NULL",
                         (lst.name,)).fetchone()
        if not r or r[0] is None:
            continue
        latest = (f"(SELECT i.sha256 FROM {T('capture_items')} i WHERE i.list = l.list AND i.slug = l.slug "
                  "ORDER BY i.at DESC LIMIT 1)")
        out += [tuple(x) + (None,) for x in conn.execute(
            f"SELECT l.list, l.slug, l.url, {latest}, l.pass_id FROM {T('capture_listed')} l "
            "WHERE l.pass_id = %s ORDER BY l.ordinal", (r[0],))]
        out += [tuple(x) for x in conn.execute(
            f"WITH fin AS (SELECT pass_id, finished_at FROM {T('capture_passes')} WHERE list = %s AND finished_at IS NOT "
            f"NULL), last AS (SELECT l.slug, max(l.pass_id) AS pass_id FROM {T('capture_listed')} l JOIN fin "
            "USING (pass_id) WHERE l.list = %s GROUP BY l.slug HAVING max(l.pass_id) < %s) "
            f"SELECT l.list, l.slug, l.url, {latest}, l.pass_id, (SELECT min(f.finished_at) FROM fin f WHERE f.pass_id > "
            f"last.pass_id)::date FROM last JOIN {T('capture_listed')} l ON l.pass_id = last.pass_id AND l.slug = last.slug "
            "ORDER BY l.pass_id, l.ordinal", (lst.name, lst.name, r[0]))]
    return out


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging): the newest finished pass of the listing, read under `schema`;
    with no finished pass the tables are made empty. Problems the reading's check finds are logged, as the job logs
    them. Added by the integrator at the merge of regulators-1."""
    from registers.commerce_commission import check
    listed = listing(conn)
    if not listed:
        create_tables(conn, schema)
        log(f"{SCHEMA}: no finished pass of the listing is held; nothing read into {schema}")
        return 0
    counts = build(conn, schema, listed)
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['cases']} cases, {counts['parties']} parties, {counts['set_aside']} set aside, "
        f"{counts['not_captured']} not captured into {schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["cases"] + counts["parties"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        for t in PRIVATE_TABLES:
            conn.execute(f"INSERT INTO {ptable(SCHEMA, t)} SELECT * FROM {ptable(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def unchanged(conn, listed: list) -> bool:
    if conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.read_items",)).fetchone()[0] is None:
        return False
    if conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}_private.suppressed_names",)).fetchone()[0] is None:
        return False
    held = {tuple(r) for r in conn.execute(f"SELECT list, slug, document, taken_down_on FROM {SCHEMA}.read_items")}
    return held == {(e[0], e[1], e[3], e[5] if len(e) > 5 else None) for e in listed}


def job(log=print) -> int:
    """qv4-commerce-commission-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.commerce_commission import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        listed = listing(conn)
        if not listed:
            log(f"{SCHEMA}: no finished pass of the listing is held; nothing loaded")
            jobrun.record(JOB, False, "no finished pass of the listing is held", started, {})
            return 1
        if unchanged(conn, listed):
            log(f"{SCHEMA}: the listing is the one published; nothing loaded")
            jobrun.record(JOB, True, "unchanged: the listing is the one published", started, {})
            return 0
        with conn.transaction():
            counts = build(conn, STAGING, listed)
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['cases']} cases, {counts['parties']} parties, {counts['set_aside']} set aside, "
                  f"{counts['not_captured']} not captured; " + ("; ".join(problems) or "reconciles"))
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
    ap = argparse.ArgumentParser(prog="python -m registers.commerce_commission.load")
    ap.add_argument("--schema", default="scratch_commerce_commission_full")
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
