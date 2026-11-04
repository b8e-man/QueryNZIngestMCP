"""Loading (plan 1b.7): `build(conn, schema, items, held)` reads the
capture's record into the reading's tables under `schema`; `publish(conn,
staging)` moves them into `councillor_interests` and makes the views, in one
transaction. sample.py uses the same `build`.

Per council (all 78 of `capture.REGISTERS`): how it publishes its register
and what the estate holds of it (`registers`); every register document held
(`documents`: held, never read); and, from each page of the structured shape
(read.py), one row per member and category (`interests`), the newest
capture of each page only. Every category is kept with its flags
(`real_property`, `of_partner`, `private_entries`), counted by heading in
`read_flagged`; an address-shaped entry goes to the private twin
`councillor_interests_private.entries` (ruling 142).

    python -m registers.councillor_interests.load [--schema scratch_…] [--database querynz_v4_sample]
    python -m registers.councillor_interests.load --job
"""
import argparse
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.councillor_interests import capture, model_read, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "councillor_interests"
JOB = "qv4-councillor-interests-load"
STAGING = "staging_councillor_interests_load"
TABLES = ("registers", "documents", "interests", "read_flagged", "read_set_aside")
PRIVATE_TABLES = ("entries",)
COLUMNS = {
    "registers": ("council", "host", "form", "landing_url", "landing_sha256", "documents_held", "members_read", "why"),
    "documents": ("sha256", "council", "url", "found_on", "asked_at", "reading", "members", "unread_pages"),
    "interests": ("key", "council", "member", "role", "category", "entries", "real_property", "of_partner",
                  "private_entries", "kind", "as_at", "document", "page", "place", "url", "read_from", "reader", "model",
                  "profile", "profile_version"),
    "read_flagged": ("council", "category", "why", "members"),
    "entries": ("key", "ordinal", "entry"),
    "read_set_aside": ("document", "place", "stage", "reason"),
}
PER_MEMBER_FILES = 4          # a council with more register documents than this publishes one file per member
table = capture.table
_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}\.")
_PRIVATE = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}_private\.")


def private_of(schema: str) -> str:
    """The private twin of `schema`: `councillor_interests_private`, or `<staging>_private`."""
    return f"{SCHEMA}_private" if schema == SCHEMA else f"{schema[:55]}_private"


def private_table(schema: str, t: str) -> str:
    return f"{SCHEMA}_private.{t}" if schema == SCHEMA else f"{private_of(schema)}.{SCHEMA}_{t}"


def sql(name: str, schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = capture.READING + text.split(capture.READING, 1)[1]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    text = _PRIVATE.sub(f"{private_of(schema)}.{pre}", text)
    return _NAMES.sub(f"{schema}.{pre}", text)


def create_tables(conn, schema: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {private_of(schema)}")
    for t in TABLES + ("read_withheld",):
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t)} CASCADE")
    for t in PRIVATE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {private_table(schema, t)} CASCADE")
    conn.execute(sql("tables.sql", schema))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(row.get(c) for c in cols))
            n += 1
    return n


def build(conn, schema: str, items: list, held: dict, registers: dict = None, read_bytes=read_bytes, store=None,
          version: int = None) -> dict:
    """`items`: the capture's asks, oldest first, as dicts (council, url, kind, found_on, asked_at, sha256, why);
    `held`: host → why for every held host. A register PDF's stored text-reader reading is replayed (model_read.replay,
    never a call); one not yet read waits and is counted."""
    t0 = time.monotonic()
    registers = registers if registers is not None else capture.REGISTERS
    create_tables(conn, schema)
    T = lambda t: table(schema, t)
    newest = {}
    for it in items:
        if it.get("sha256"):
            newest[it["url"]] = it
    docs = {}
    for it in newest.values():
        if it["kind"] == "document" and it["sha256"] not in docs:
            docs[it["sha256"]] = dict(it, reading=None, members=0, unread_pages=[])
    rows, flagged, asides, members_of = {}, {}, [], {}
    model_pages = {}                    # a page that prints a register in another shape: the text reader's (2 November 2026)
    for it in sorted(newest.values(), key=lambda x: x["url"]):
        if it["kind"] != "page":
            continue
        body = read_bytes(it["sha256"])
        if read.recognise(body) != "register":
            if model_read.page_wanted(it["council"], {d["council"] for d in docs.values()}) \
                    and not model_read.recognise_page(body, it["url"], registers.get(it["council"], ("",))[0])[0] \
                    and it["sha256"] not in model_pages:
                model_pages[it["sha256"]] = dict(it)
            continue
        try:
            out = read.read_register(body, it["sha256"], it["url"])
        except read.NotTheShape as exc:
            asides.append({"document": it["sha256"], "place": None, "stage": "read", "reason": str(exc)})
            continue
        members_of[it["council"]] = members_of.get(it["council"], 0) + len(out["members"])
        for i, r in enumerate(out["rows"], 1):
            key = f"{it['council']}/{r['member']}/{r['place']}"
            rows[key] = dict(r, key=key, council=it["council"], as_at=out["as_at"], read_from="text",
                             reader=read.READER, profile=read.PROFILE, profile_version=read.PROFILE_VERSION)
        for (cat, why), n in out["flagged"].items():
            k = (it["council"], cat, why)
            flagged[k] = flagged.get(k, 0) + n
    html_councils = set(members_of) | {it["council"] for it in model_pages.values()}
    states = {}
    todo = sorted(docs.items(), key=lambda kv: (kv[1]["council"], kv[0])) + sorted(
        model_pages.items(), key=lambda kv: (kv[1]["council"], kv[0]))
    for sha, it in todo:
        got = model_read.replay(sha, read_bytes(sha), version=version, store=store)
        it["reading"], it["unread_pages"] = got["state"], got["unread"]
        head = ("page: " if sha in model_pages else "") + (
            got["state"] if got["state"].startswith("waiting") else got["state"].split(":")[0])
        states[head] = states.get(head, 0) + 1
        if got["state"] != "read":
            if got["state"].startswith(("not a register", "set aside")):
                asides.append({"document": sha, "place": None, "stage": "read", "reason": got["state"]})
            continue
        it["members"] = len({r["member_no"] for r in got["rows"]})
        members_of[it["council"]] = members_of.get(it["council"], 0) + it["members"]
        for r in got["rows"]:
            key = f"{it['council']}/{r['member']}/{sha[:12]} member {r['member_no']} category {r['category_no']}"
            rows[key] = {"key": key, "council": it["council"], "member": r["member"], "role": r["role"],
                         "category": r["category"], "entries": r["entries"], "real_property": r["real_property"],
                         "of_partner": r["of_partner"], "private_entries": r["private_entries"],
                         "private": r["private"], "kind": r["kind"], "as_at": got["as_at"],
                         "document": sha, "page": int(r["pages"].split("-")[0]),
                         "place": f"pages {r['pages']}, text reader piece {r['piece']}, member {r['member_no']}, "
                                  f"category {r['category_no']}",
                         "url": it["url"], "read_from": "text", "reader": model_read.READER, "model": r["model"],
                         "profile": got["profile"], "profile_version": got["version"]}
        for (cat, why), n in got["flagged"].items():
            k = (it["council"], cat, why)
            flagged[k] = flagged.get(k, 0) + n
    reg_rows = []
    for council, (host, page, pdf) in registers.items():
        why_failed = None
        nd = sum(1 for d in docs.values() if d["council"] == council)
        landing = newest.get(page) if page else None
        hosts = {capture.site_of(h) for h in held}
        if council in capture.TERMS_BAR:
            form = "held: its terms bar automated access"
        elif council in html_councils:
            form = "html register" if members_of.get(council) else "html register, waiting: text reader"
        elif nd > PER_MEMBER_FILES:
            form = "per-member files"
        elif nd:
            form = "pdf register"
        elif capture.site_of(host) in hosts:
            form = "not reached"
        elif page or pdf:
            failed = [it for it in items if it["url"] in (page, pdf) and it.get("why") and not it.get("sha256")]
            if landing:
                form = "linked, not found"
            elif failed:
                form, why_failed = "address failed", failed[-1]["why"]
            else:
                form = "not yet captured"
        else:
            form = "not found"
        why = capture.TERMS_BAR.get(council) or (why_failed if form == "address failed" else None) or next(
            (w for h, w in held.items() if capture.site_of(h) == capture.site_of(host)), None)
        reg_rows.append({"council": council, "host": host, "form": form, "landing_url": page,
                         "landing_sha256": landing["sha256"] if landing else None, "documents_held": nd,
                         "members_read": members_of.get(council, 0), "why": why})
    private = [{"key": k, "ordinal": i, "entry": e} for k, r in rows.items() for i, e in r.get("private") or []]
    return {"registers": _copy(conn, T("registers"), COLUMNS["registers"], reg_rows),
            "documents": _copy(conn, T("documents"), COLUMNS["documents"], docs.values()),
            "interests": _copy(conn, T("interests"), COLUMNS["interests"], rows.values()),
            "flagged": _copy(conn, T("read_flagged"), COLUMNS["read_flagged"],
                             [{"council": c, "category": cat, "why": w, "members": n}
                              for (c, cat, w), n in sorted(flagged.items())]),
            "private_entries": _copy(conn, private_table(schema, "entries"), COLUMNS["entries"], private),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "documents_by_reading": states,
            "seconds": round(time.monotonic() - t0, 1)}


def held_record(conn, schema: str = SCHEMA) -> tuple:
    T = lambda t: table(schema, t)
    if conn.execute("SELECT to_regclass(%s)", (T("capture_items"),)).fetchone()[0] is None:
        return [], {}
    cur = conn.execute(f"SELECT council, url, kind, found_on, asked_at, sha256, why FROM {T('capture_items')} "
                       "ORDER BY asked_at, item_id")
    cols = [d.name for d in cur.description]
    items = [dict(zip(cols, r)) for r in cur.fetchall()]
    held = dict(conn.execute(f"SELECT host, why FROM {T('capture_held_hosts')}").fetchall())
    return items, held


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step: the capture's record read under `schema`; with none, empty tables."""
    from registers.councillor_interests import check
    items, held = held_record(conn)
    counts = build(conn, schema, items, held)
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['registers']} councils, {counts['documents']} documents held "
        f"({counts['documents_by_reading']}), {counts['interests']} interests read, {counts['flagged']} category flags, {counts['private_entries']} private entries into {schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["registers"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        for t in PRIVATE_TABLES:
            conn.execute(f"INSERT INTO {private_table(SCHEMA, t)} SELECT * FROM {private_table(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def job(log=print) -> int:
    from support import db
    from registers.councillor_interests import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        items, held = held_record(conn)
        with conn.transaction():
            counts = build(conn, STAGING, items, held)
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['registers']} councils, {counts['documents']} documents held ("
                  + ", ".join(f"{k} {v}" for k, v in sorted(counts["documents_by_reading"].items())) + f"), "
                  f"{counts['interests']} interests read, {counts['flagged']} category flags, "
                  f"{counts['private_entries']} private entries; "
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
    ap = argparse.ArgumentParser(prog="python -m registers.councillor_interests.load")
    ap.add_argument("--schema", default="scratch_councillor_interests_full")
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
        items, held = held_record(src, a.capture_schema)
    with db.connect(db.OWNER_KEY, a.database) as conn:
        with conn.transaction():
            counts = build(conn, a.schema, items, held)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
