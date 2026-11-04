"""Loading (plan 1b.7): `build(conn, schema, pages)` reads the listed
decisions-list pages into the reading's tables under `schema`;
`publish(conn, staging)` moves them into `building_practitioners` and makes
the views, in one transaction. sample.py uses the same `build`.

Idempotent per listing: the reading's tables are dropped and made again and
every page read again. Pages are read newest landed first, so a decision
read again on an older page (a pass's pages shift when the Board adds a
decision mid-pass, and every weekly pass reads them all again) is counted as
superseded, not read twice. Items in equal decisions typed plus superseded
plus set aside, page by page; the build raises if a page does not reconcile.

    python -m registers.building_practitioners.load [--schema scratch_…] [--database querynz_v4_sample]
        [--register-database querynz_v4_sample --register-schema scratch_…]   # a session's register capture
    python -m registers.building_practitioners.load --job

Every line printed is a count.
"""
import argparse
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.building_practitioners import capture, read, register

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "building_practitioners"
PRIVATE = "building_practitioners_private"
JOB = "qv4-building-practitioners-load"
STAGING = "staging_building_practitioners_load"
TABLES = ("read_pages", "decisions", "practitioners", "read_register", "read_set_aside")
#: in the private twin (ruling 142): what the lane's own tables leave out, kept whole
PRIVATE_TABLES = ("suppressed", "summaries", "contacts")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "read_pages": ("document", "pass_id", "stated", "items", "typed", "superseded", "set_aside"),
    "decisions": ("key", "complaint_number", "citation", "decision_kind", "name", "lbp_number", "suppressed", "region",
                  "licence_classes", "decided_on", "penalties", "grounds", "upheld", "decision_url", "pdf_url",
                  "taken_down_on") + _CITE,
    "suppressed": ("key", "name", "lbp_number", "region", "decision_url", "pdf_url", "document", "place"),
    "summaries": ("key", "summary", "document", "place"),
    "contacts": ("key", "field", "value", "document"),
    "read_set_aside": ("document", "place", "stage", "reason"),
    "practitioners": ("key", "licence_number", "name", "first_name", "middle_names", "last_name", "suppressed",
                      "licence_classes", "status", "area", "area_names_address", "region", "first_granted_on",
                      "register_url", "register_id") + _CITE,
    "read_register": ("pass_id", "searches", "listed", "pages", "typed", "set_aside", "awaiting"),
}


def private_of(schema: str) -> str:
    return PRIVATE if schema == SCHEMA else f"{schema}_private"


def table(schema: str, t: str, shared: bool = False) -> str:
    where = private_of(schema) if t in PRIVATE_TABLES else schema
    return f"{where}.{SCHEMA}_{t}" if shared else f"{where}.{t}"


_NAMES = re.compile(r"(?<![A-Za-z0-9_])building_practitioners(_private)?\.")


def sql(name: str, schema: str = SCHEMA, shared: bool = False) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = capture.READING + text.split(capture.READING, 1)[1]
    pre = f"{SCHEMA}_" if shared else ""
    return _NAMES.sub(lambda m: f"{private_of(schema) if m.group(1) else schema}.{pre}", text)


def create_tables(conn, schema: str, shared: bool = False) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {private_of(schema)}")
    for t in TABLES + PRIVATE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t, shared)} CASCADE")
    conn.execute(sql("tables.sql", schema, shared))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(row.get(c) for c in cols))
            n += 1
    return n


def read_register(reg: dict, read_bytes=read_bytes, versions: dict = None) -> dict:
    """The register's rows from `reg` ({'pass_id', 'lists': [sha256], 'details': [sha256]}): the pass's searches
    give each listed practitioner's classes and areas; each practitioner's page (the newest held) gives a row.
    Every page is a row, a duplicate number or a catch-log line; every listed practitioner is read or awaiting."""
    versions = versions or register.versions()
    listed, asides = {}, []
    for sha in reg.get("lists", []):
        out, why = register.read_list(read_bytes(sha))
        if out is None:
            asides.append({"document": sha, "place": "search", "stage": "recognise", "reason": why})
        else:
            listed[out["query"]] = out["rows"]
    classes = register.classes_of(listed)
    rows, numbers, read_ids = [], set(), set()
    for sha in reg.get("details", []):
        d, why = register.read_detail(read_bytes(sha))
        if d is None:
            asides.append({"document": sha, "place": "practitioner", "stage": "read", "reason": why})
            continue
        read_ids.add(d["guid"])
        if d["number"] in numbers:
            asides.append({"document": sha, "place": f"practitioner={d['number']}", "stage": "read",
                           "reason": "a practitioner number already read from another page"})
            continue
        numbers.add(d["number"])
        rows.append(register.row(d, sha, classes.get(d["guid"], []), d["guid"] in classes, versions))
    ledger = {"pass_id": reg.get("pass_id"), "searches": len(listed), "listed": len(classes),
              "pages": len(reg.get("details", [])), "typed": len(rows),
              "set_aside": sum(1 for a in asides if a["place"].startswith("practitioner")),
              "awaiting": len(set(classes) - read_ids)}
    return {"rows": rows, "set_aside": asides, "ledger": ledger}


def build(conn, schema: str, pages: list, read_bytes=read_bytes, shared: bool = False, version: int = None,
          reg: dict = None, finished: list = None) -> dict:
    """`pages`: [(sha256, pass_id)] oldest landed first; read newest first. `reg`: the register's pages
    (`register_listing`), or None to read none. `finished`: [(pass_id, the day it finished)] of the decisions list's
    finished passes: a decision no page of the newest finished pass lists is kept, flagged `taken_down_on` the day
    the first finished pass after its last listing finished (ruling 142)."""
    t0 = time.monotonic()
    version = version or read.profile_version()
    create_tables(conn, schema, shared)
    T = lambda t: table(schema, t, shared)
    seen, rows, asides, ledger = set(), [], [], []
    last = {}                                   # decision key → the newest pass that listed it
    for sha, pass_id in reversed(list(dict.fromkeys(pages))):
        out = read.read_page(read_bytes(sha), sha, version)
        typed = superseded = 0
        for r in out["rows"]:
            last[r["key"]] = max(last.get(r["key"], pass_id or 0), pass_id or 0)
            if r["key"] in seen:
                superseded += 1
                continue
            seen.add(r["key"])
            rows.append(r)
            typed += 1
        asides += out["set_aside"]
        item_asides = sum(1 for a in out["set_aside"] if a["place"].startswith("item["))
        if out["stated"] is not None and out["items"] != typed + superseded + item_asides:
            raise AssertionError(f"{SCHEMA}: page {sha[:12]} does not reconcile")
        ledger.append({"document": sha, "pass_id": pass_id, "stated": out["stated"][1] if out["stated"] else None,
                       "items": out["items"], "typed": typed, "superseded": superseded, "set_aside": item_asides})
    newest = max((p for p, _ in finished or []), default=None)
    for r in rows:
        later = [d for p, d in finished or [] if p > last.get(r["key"], 0)]
        r["taken_down_on"] = min(later) if newest is not None and last.get(r["key"], 0) < newest and later else None
    private = {"suppressed": [{"key": r["key"], **{k: r["private"][k] for k in ("name", "lbp_number", "region",
                                                                                 "decision_url", "pdf_url")},
                               "document": r["document"], "place": r["place"]} for r in rows if r["suppressed"]],
               "summaries": [{"key": r["key"], "summary": r["private"]["summary"], "document": r["document"],
                              "place": r["place"]} for r in rows if r["private"]["summary"]],
               "contacts": []}
    practitioners = 0
    if reg is not None:
        from psycopg.types.json import Jsonb
        r = read_register(reg, read_bytes)
        asides += r["set_aside"]
        practitioners = _copy(conn, T("practitioners"), COLUMNS["practitioners"],
                              ({**x, "licence_classes": Jsonb(x["licence_classes"])} for x in r["rows"]))
        private["contacts"] = [{"key": x["key"], "field": f, "value": v, "document": x["document"]}
                               for x in r["rows"] for f, v in x.get("contacts") or []]
        _copy(conn, T("read_register"), COLUMNS["read_register"], [r["ledger"]])
    return {"decisions": _copy(conn, T("decisions"), COLUMNS["decisions"], rows),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "pages": _copy(conn, T("read_pages"), COLUMNS["read_pages"], ledger),
            **{t: _copy(conn, T(t), COLUMNS[t], v) for t, v in private.items()},
            "taken_down": sum(1 for r in rows if r["taken_down_on"]),
            "superseded": sum(l["superseded"] for l in ledger), "practitioners": practitioners,
            "seconds": round(time.monotonic() - t0, 1)}


def listing(conn, schema: str = SCHEMA) -> list:
    """The pages of every pass, oldest landed first: a decision the Board's list no longer shows is read from the
    newest page that listed it and kept (ruling 142: a row the publisher takes down stays, flagged)."""
    return [tuple(x) for x in conn.execute(
        f"SELECT sha256, pass_id FROM {schema}.capture_pages ORDER BY pass_id, page_no")]


def finished_passes(conn, schema: str = SCHEMA) -> list:
    """[(pass_id, the New Zealand day it finished)] of the decisions list's finished passes."""
    return [tuple(x) for x in conn.execute(
        f"SELECT pass_id, (finished_at AT TIME ZONE 'Pacific/Auckland')::date FROM {schema}.capture_passes "
        "WHERE finished_at IS NOT NULL ORDER BY pass_id")]


def register_listing(conn, schema: str = SCHEMA) -> dict:
    """The newest finished pass of the register's searches, and the newest page held of every practitioner."""
    if conn.execute("SELECT to_regclass(%s)", (f"{schema}.capture_register_passes",)).fetchone()[0] is None:
        return {"pass_id": None, "lists": [], "details": []}
    r = conn.execute(f"SELECT max(pass_id) FROM {schema}.capture_register_passes WHERE finished_at IS NOT NULL").fetchone()
    pass_id = r[0] if r else None
    lists = [x[0] for x in conn.execute(f"SELECT sha256 FROM {schema}.capture_register_lists WHERE pass_id = %s "
                                        "ORDER BY query_no", (pass_id,))] if pass_id is not None else []
    details = [x[0] for x in conn.execute(f"SELECT DISTINCT ON (guid) sha256 FROM {schema}.capture_register_details "
                                          "ORDER BY guid, fetched_at DESC, sha256")]
    return {"pass_id": pass_id, "lists": lists, "details": details}


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging): the newest pass's pages, read under `schema`.
    Problems the reading's check finds are logged, as the job logs them. Added by the integrator at the merge of sanctions-1."""
    from registers.building_practitioners import check
    listed = listing(conn)
    counts = build(conn, schema, listed, reg=register_listing(conn), finished=finished_passes(conn))
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['decisions']} decisions, {counts['practitioners']} practitioners, {counts['set_aside']} set aside "
        f"into {schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["decisions"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES + PRIVATE_TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def unchanged(conn, listed: list, reg: dict) -> bool:
    for t in ("read_pages", "read_register", "summaries"):
        if conn.execute("SELECT to_regclass(%s)", (table(SCHEMA, t),)).fetchone()[0] is None:
            return False
    if {r[0] for r in conn.execute(f"SELECT document FROM {SCHEMA}.read_pages")} != {s for s, _ in listed}:
        return False
    held = {r[0] for r in conn.execute(f"SELECT document FROM {SCHEMA}.practitioners")}
    gone = {r[0] for r in conn.execute(f"SELECT document FROM {SCHEMA}.read_set_aside WHERE stage = 'read' "
                                       "AND place LIKE 'practitioner%%'")}
    led = conn.execute(f"SELECT pass_id FROM {SCHEMA}.read_register").fetchone()
    return held | gone == set(reg["details"]) and (led[0] if led else None) == reg["pass_id"]


def job(log=print) -> int:
    """qv4-building-practitioners-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.building_practitioners import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        listed = listing(conn)
        reg = register_listing(conn)
        if unchanged(conn, listed, reg):
            log(f"{SCHEMA}: the listing is the one published; nothing loaded")
            jobrun.record(JOB, True, "unchanged: the listing is the one published", started, {})
            return 0
        with conn.transaction():
            counts = build(conn, STAGING, listed, reg=reg, finished=finished_passes(conn))
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['decisions']} decisions, {counts['practitioners']} practitioners, {counts['set_aside']} set aside; "
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
    ap = argparse.ArgumentParser(prog="python -m registers.building_practitioners.load")
    ap.add_argument("--schema", default="scratch_building_practitioners_full")
    ap.add_argument("--database", default="querynz_v4_sample")
    ap.add_argument("--capture-database", default="querynz_v4")
    ap.add_argument("--capture-schema", default=SCHEMA)
    ap.add_argument("--register-database", default=None, help="where the register's capture record is (default: --capture-database)")
    ap.add_argument("--register-schema", default=None, help="its schema there (default: --capture-schema)")
    ap.add_argument("--job", action="store_true")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    if not a.schema.startswith(("scratch_", "staging_")):
        print(f"{SCHEMA}: a session loads only a scratch or staging schema")
        return 2
    key = lambda d: db.READ_KEY if d == "querynz_v4" else db.OWNER_KEY
    with db.connect(key(a.capture_database), a.capture_database) as src:
        listed = listing(src, a.capture_schema)
        finished = finished_passes(src, a.capture_schema)
    rdb = a.register_database or a.capture_database
    with db.connect(key(rdb), rdb) as src:
        reg = register_listing(src, a.register_schema or a.capture_schema)
    with db.connect(db.OWNER_KEY, a.database) as conn:
        with conn.transaction():
            counts = build(conn, a.schema, listed, reg=reg, finished=finished)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
