"""Loading (plan 1b.7): `build(conn, schema, entries)` reads the pages the
newest finished walk landed into the reading's tables under `schema`;
`publish(conn, staging)` moves them into `iwi_directory` and makes the views,
in one transaction. sample.py uses the same `build`.

An entity met on several pages (a marae shared by hapū of two iwi, an
organisation listed under each iwi it serves) is one row, cited to the first
page in address order, with `pages` counting the pages that list it; its
flags are the union of what each page marks, and an organisation any page
marks as a post-settlement governance entity is one. An organisation's key
is its name folded, macrons off; where its pages print names that differ
(Ngāti Hāua Iwi Trust, Upper Whanganui, and Ngāti Hauā Iwi Trust, Waikato:
one key, two bodies) each name printed is its own body, keyed by the first
page that lists it, and its relations and settlements go with it. Pages in
equal pages read plus not read (site pages) plus set aside; the build raises
if not.

    python -m registers.iwi_directory.load [--schema scratch_…] [--database querynz_v4_sample]
    python -m registers.iwi_directory.load --job

Every line printed is a count.
"""
import argparse
import os
import re
import sys
import time
from collections import Counter

from support import jobrun
from support.docstore.landing import read_bytes
from registers.iwi_directory import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "iwi_directory"
JOB = "qv4-iwi-directory-load"
STAGING = "staging_iwi_directory_load"
TABLES = ("read_pages", "entities", "relations", "settlements", "read_unread_labels", "read_set_aside")
#: what an organisation's entry prints beyond the labels read onto a row (people, phones, emails, addresses), whole:
#: in the private twin only, which qv4_read and qv4_product are never granted (ruling 142, 4 November 2026)
PRIVATE = f"{SCHEMA}_private"
PRIVATE_COLUMNS = ("key", "entity_key", "label", "value", "document", "place")


def private_table(schema: str) -> str:
    return f"{PRIVATE}.entry_fields" if schema == SCHEMA else f"{schema}_private.{SCHEMA}_entry_fields"


def create_private(conn, schema: str) -> None:
    name = private_table(schema)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {name.split('.')[0]}")
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(f"CREATE TABLE {name} (key text PRIMARY KEY, entity_key text NOT NULL, label text NOT NULL, "
                 f"value text NOT NULL, document text NOT NULL, place text NOT NULL)")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "read_pages": ("url", "document", "kind", "state", "entities", "relations", "iwi_links"),
    "entities": ("key", "kind", "name", "iwi_key", "listed_as", "region", "legal_entity", "governance_structure",
                 "hapu_represented", "area_of_interest", "local_authorities", "primary_purpose", "website", "wharenui",
                 "location", "flags", "charity_number", "nzbn", "last_updated", "pages", "url") + _CITE,
    "relations": ("key", "from_key", "relation", "to_key", "to_name", "section", "url") + _CITE,
    "settlements": ("key", "settlement_key", "entity_key", "iwi_key", "name", "act", "act_year", "stage", "signed_on", "as_printed",
                    "url") + _CITE,
    "read_unread_labels": ("label", "pages"),
    "read_set_aside": ("document", "place", "stage", "reason"),
}
table = capture.table
_NAMES = re.compile(rf"(?<![A-Za-z0-9_]){SCHEMA}\.")


def sql(name: str, schema: str = SCHEMA) -> str:
    """tables.sql's reading part, or publish.sql, for `schema` (prefixed names outside the lane's own schema)."""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = capture.READING + text.split(capture.READING, 1)[1]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return _NAMES.sub(f"{schema}.{pre}", text)


def create_tables(conn, schema: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t)} CASCADE")
    conn.execute(sql("tables.sql", schema))
    create_private(conn, schema)


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(row.get(c) for c in cols))
            n += 1
    return n


def merge(entities: list) -> list:
    """One row per key: the first page's, `pages` counted, flags united, an organisation any page marks as a
    governance entity is one, an empty field filled from a later page."""
    out = {}
    for e in entities:
        k = e["key"]
        if k not in out:
            out[k] = dict(e, flags=list(e["flags"]), pages=1)
            continue
        o = out[k]
        o["pages"] += 1
        o["flags"] += [f for f in e["flags"] if f not in o["flags"]]
        if e["kind"] == "governance entity" and o["kind"] == "organisation":
            o["kind"] = "governance entity"
        for c, v in e.items():
            if o.get(c) is None and v is not None:
                o[c] = v
    return list(out.values())


def split_by_printed_name(ents: list, rels: list, sets: list) -> list:
    """An organisation key whose pages print different names (read.printed: macrons kept) names as many bodies:
    each name printed is keyed `<key>/<slug of the first page that prints it>`, and the relations and settlements
    read from its pages follow it. `ents` in page order; rows are re-keyed in place. Returns the keys split."""
    printed = {}
    for e in ents:
        if e["key"].startswith("tkm/org/"):
            printed.setdefault(e["key"], {}).setdefault(read.printed(e["name"]), read.slug_of(e["url"]))
    split = {k: v for k, v in printed.items() if len(v) > 1}
    by_page = {}
    for e in ents:
        if e["key"] in split:
            new = f"{e['key']}/{split[e['key']][read.printed(e['name'])]}"
            by_page[(e["key"], e["document"])] = new
            e["key"] = new
    for r in rels:
        r["from_key"] = by_page.get((r["from_key"], r["document"]), r["from_key"])
    for s in sets:
        if (s["entity_key"], s["document"]) in by_page:
            s["entity_key"] = by_page[(s["entity_key"], s["document"])]
            s["key"] = read.settlement_row_key(s["entity_key"], s["settlement_key"])
    return sorted(split)


def build(conn, schema: str, entries: list, read_bytes=read_bytes) -> dict:
    """`entries`: [(url, sha256)], one per page the walk landed, read in address order."""
    t0 = time.monotonic()
    create_tables(conn, schema)
    T = lambda t: table(schema, t)
    ledger, ents, rels, sets, asides, unread = [], [], [], [], [], Counter()
    for url, sha in sorted(set(entries)):
        try:
            out = read.read_page(read_bytes(sha), sha, url)
        except read.NotTheShape as exc:
            asides.append({"document": sha, "place": url, "stage": "read", "reason": str(exc)})
            ledger.append({"url": url, "document": sha, "kind": "unknown", "state": "set aside", "entities": 0,
                           "relations": 0, "iwi_links": []})
            continue
        ents += out["entities"]
        rels += out["relations"]
        sets += out["settlements"]
        unread.update(out["unread"])
        ledger.append({"url": url, "document": sha, "kind": out["kind"],
                       "state": "not read" if out["kind"] == "site" else "read", "entities": len(out["entities"]),
                       "relations": len(out["relations"]), "iwi_links": out["iwi_links"]})
    if len(ledger) != len({u for u, _ in entries}):
        raise AssertionError(f"{SCHEMA}: {len(set(entries))} pages landed, {len(ledger)} in the ledger")
    split = split_by_printed_name(ents, rels, sets)
    seen, rel_rows = set(), []
    for r in rels:
        k = (r["from_key"], r["relation"], r["to_key"], r["to_name"])
        if k not in seen:
            seen.add(k)
            rel_rows.append(dict(r, key="|".join((r["from_key"], r["relation"], r["to_key"] or r["to_name"] or ""))))
    set_rows = list({s["key"]: s for s in reversed(sets)}.values())
    private = []
    for e in ents:
        for i, (label, value) in enumerate(e.pop("_private", None) or (), 1):
            private.append({"key": f"{e['key']}|{e['document']}|{e['place']}|{i}", "entity_key": e["key"],
                            "label": label, "value": value, "document": e["document"], "place": e["place"]})
    private = list({r["key"]: r for r in private}.values())
    merged = merge(ents)
    return {"entities": _copy(conn, T("entities"), COLUMNS["entities"], merged),
            "relations": _copy(conn, T("relations"), COLUMNS["relations"], rel_rows),
            "settlements": _copy(conn, T("settlements"), COLUMNS["settlements"], set_rows),
            "unread_labels": _copy(conn, T("read_unread_labels"), COLUMNS["read_unread_labels"],
                                   [{"label": k, "pages": v} for k, v in sorted(unread.items())]),
            "set_aside": _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides),
            "pages": _copy(conn, T("read_pages"), COLUMNS["read_pages"], ledger),
            "private_fields": _copy(conn, private_table(schema), PRIVATE_COLUMNS, private),
            "organisation_keys_split": len(split),
            "seconds": round(time.monotonic() - t0, 1)}


def listing(conn, schema: str = SCHEMA) -> list:
    """Every page the newest finished walk landed: [(url, sha256)]."""
    T = lambda t: table(schema, t)
    if conn.execute("SELECT to_regclass(%s)", (T("capture_passes"),)).fetchone()[0] is None:
        return []
    r = conn.execute(f"SELECT max(pass_id) FROM {T('capture_passes')} WHERE finished_at IS NOT NULL").fetchone()
    if not r or r[0] is None:
        return []
    return [tuple(x) for x in conn.execute(
        f"SELECT url, sha256 FROM {T('capture_frontier')} WHERE pass_id = %s AND state = 'landed' ORDER BY url",
        (r[0],))]


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging): the newest finished walk, read under `schema`; with none
    held the tables are made empty. Problems the reading's check finds are logged, as the job logs them."""
    from registers.iwi_directory import check
    listed = listing(conn)
    if not listed:
        create_tables(conn, schema)
        log(f"{SCHEMA}: no finished walk is held; nothing read into {schema}")
        return 0
    counts = build(conn, schema, listed)
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['entities']} entities, {counts['relations']} relations, {counts['settlements']} "
        f"settlements, {counts['set_aside']} set aside into {schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["entities"] + counts["relations"] + counts["settlements"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        conn.execute(f"INSERT INTO {private_table(SCHEMA)} SELECT * FROM {private_table(staging)}")
        conn.execute(sql("publish.sql"))
    log(f"{SCHEMA}: published from {staging}")


def unchanged(conn, listed: list) -> bool:
    if conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.read_pages",)).fetchone()[0] is None:
        return False
    held = {(r[0], r[1]) for r in conn.execute(f"SELECT url, document FROM {SCHEMA}.read_pages")}
    return held == set(listed)


def job(log=print) -> int:
    """qv4-iwi-directory-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.iwi_directory import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        listed = listing(conn)
        if not listed:
            log(f"{SCHEMA}: no finished walk is held; nothing loaded")
            jobrun.record(JOB, False, "no finished walk is held", started, {})
            return 1
        if unchanged(conn, listed):
            log(f"{SCHEMA}: the walk is the one published; nothing loaded")
            jobrun.record(JOB, True, "unchanged: the walk is the one published", started, {})
            return 0
        with conn.transaction():
            counts = build(conn, STAGING, listed)
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['entities']} entities, {counts['relations']} relations, {counts['settlements']} settlements, "
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
    ap = argparse.ArgumentParser(prog="python -m registers.iwi_directory.load")
    ap.add_argument("--schema", default="scratch_iwi_directory_full")
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
