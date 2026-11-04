"""Loading (plan 1b.7). The merge gate's staging step calls `load` to build
this lane's tables under a staging schema of the real database, and
`publish` to move the rows into the lane's own tables in one transaction
and refresh the published views. `fill` in sample.py uses the same pieces.

Capture, read every listing, join the scans, insert. Items in equal items
out plus items set aside: every table row on a listing is a declaration or
a catch-log line, and every file taken from the old folder is landed or a
catch-log line. A linked scan whose printed total could not be read is a
catch-log line of its own (stage `form`, its hash and pages): its row is
still a declaration, so it is counted apart.

    python -m registers.disclosures.load [--schema scratch_…] [--database querynz_v4_sample]
    python -m registers.disclosures.load --job    # qv4-disclosures-load: capture, build in staging, check, publish

The Commission's two listings are re-fetched by the old job every night, and
their bytes change most nights; pub.disclosures cites them by hash, and the
day's build keeps only rows whose document the frozen release listed. So
the lane is loaded every night, after that release, by `--job`: it copies
the old folder's current listings and scans, builds into `STAGING` of
querynz_v4, holds the result to check.py's verdict against the frozen
site, and publishes only when no difference lacks a card. A session loads
only a scratch or staging schema of the sample database.
"""
import argparse
import os
import sys

from support import jobrun
from support.docstore.landing import read_bytes
from registers.disclosures import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "disclosures"
JOB = "qv4-disclosures-load"
STAGING = "staging_disclosures_load"
PRIVATE = "disclosures_private"
TABLES = ("declarations", "items", "files", "set_aside")
COLUMNS = ("key", "document", "page", "place", "regime", "threshold", "section", "party", "party_label", "party_basis",
           "donor_name", "amount", "amount_original", "received_on", "given_on", "commission_note", "amendment",
           "amended_on", "withdrawn_on", "returned_on", "amount_note", "items_sum", "items_check",
           "at_or_under_threshold", "href", "declaration_document", "form_total", "form_check", "form_reading",
           "read_from", "reader", "profile",
           "profile_version", "loaded_at", "issue")
ITEM_COLUMNS = ("key", "declaration", "ordinal", "amount", "first_date", "contributor", "text")


def private_of(schema: str) -> str:
    return PRIVATE if schema == SCHEMA else f"{schema}_private"


def table(schema: str, t: str, shared: bool = False) -> str:
    """`schema.t`; in a schema every module shares (the sample's), the
    lane's tables carry its name: `schema.disclosures_t`."""
    return f"{schema}.{SCHEMA}_{t}" if shared else f"{schema}.{t}"


def sql(name: str, schema: str = SCHEMA, shared: bool = False) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    pre = f"{SCHEMA}_" if shared else ""
    return text.replace(f"{PRIVATE}.", f"{private_of(schema)}.{pre}").replace(f"{SCHEMA}.", f"{schema}.{pre}")


def create_tables(conn, schema: str, shared: bool = False) -> None:
    """The lane's tables as tables.sql has them now: made again on every
    build, since every row is rebuilt from documents (a register can be
    regenerated). The published views go with them; publish makes them
    again in the same transaction."""
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {private_of(schema)}")
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t, shared)} CASCADE")
    conn.execute(f"DROP TABLE IF EXISTS {table(private_of(schema), 'donor_addresses', shared)} CASCADE")
    conn.execute(sql("tables.sql", schema, shared))


def wipe(conn, schema: str, shared: bool = False) -> None:
    for t in TABLES:
        conn.execute(f"DELETE FROM {table(schema, t, shared)}")
    conn.execute(f"DELETE FROM {table(private_of(schema), 'donor_addresses', shared)}")


def insert(conn, schema: str, result: read.Result, linked: dict, forms: dict, shared: bool = False) -> int:
    for item, stage, reason in result.set_aside:
        conn.execute(f"INSERT INTO {table(schema, 'set_aside', shared)} (item, stage, reason) VALUES (%s, %s, %s)",
                     (item, stage, reason))
    for row in result.rows:
        doc = linked.get(row["key"])
        r = {**row, **row["filed"], "declaration_document": doc,
             **read.form_check(row["filed"]["amount"], doc, forms)}
        conn.execute(f"INSERT INTO {table(schema, 'declarations', shared)} ({', '.join(COLUMNS)}) "
                     f"VALUES ({', '.join(['%s'] * len(COLUMNS))})", tuple(r[c] for c in COLUMNS))
    for it in result.items:
        conn.execute(f"INSERT INTO {table(schema, 'items', shared)} ({', '.join(ITEM_COLUMNS)}) "
                     f"VALUES ({', '.join(['%s'] * len(ITEM_COLUMNS))})", tuple(it[c] for c in ITEM_COLUMNS))
    for key, address in result.addresses:
        conn.execute(f"INSERT INTO {table(private_of(schema), 'donor_addresses', shared)} (key, address) VALUES (%s, %s)",
                     (key, address))
    return len(result.rows)


def build(conn, schema: str, listings: list, declarations: list, aside: list, shared: bool = False) -> dict:
    """listings: [(sha256, Commission name)]; declarations: [(sha256,
    Commission name)]; aside: [(item, why)] from capture. Wipes and fills
    `schema`; returns the counts."""
    create_tables(conn, schema, shared)
    wipe(conn, schema, shared)
    for item, why in aside:
        conn.execute(f"INSERT INTO {table(schema, 'set_aside', shared)} (item, stage, reason) VALUES (%s, 'capture', %s)",
                     (item, why))
    results = [read.read_listing(read_bytes(sha), sha) for sha, _ in listings]
    rows = [r for res in results for r in res.rows]
    linked, files = read.join(rows, declarations)
    forms = {sha: read.form_reading(sha) for sha in set(linked.values())}
    # ruling 62: a scan whose total could not be read is set aside with its hash and pages, never queued from here;
    # its row stays (the table is the source for the amount), so these lines are not in the reconciliation
    needs = read.needs_reading(forms, linked)
    for item, stage, reason in needs:
        conn.execute(f"INSERT INTO {table(schema, 'set_aside', shared)} (item, stage, reason) VALUES (%s, %s, %s)",
                     (item, stage, reason))
    n = seen = aside_n = 0
    for res in results:
        n += insert(conn, schema, res, linked, forms, shared)
        seen += res.seen
        aside_n += len(res.set_aside)
    files_t = table(schema, "files", shared)
    for sha, name in listings:
        conn.execute(f"INSERT INTO {files_t} VALUES (%s, %s, 'listing', NULL, 'read') ON CONFLICT DO NOTHING", (sha, name))
    for sha, name, by, status in files:
        conn.execute(f"INSERT INTO {files_t} VALUES (%s, %s, 'declaration', %s, %s) ON CONFLICT DO NOTHING",
                     (sha, name, by, status))
    if seen != n + aside_n:
        raise AssertionError(f"the catch log does not reconcile: {seen} table rows, {n} read, {aside_n} set aside")
    return {"listings": len(listings), "table_rows": seen, "rows": n, "set_aside": aside_n,
            "declarations_held": len({s for s, _ in declarations}), "linked": len(linked),
            "files_not_linked": sum(1 for f in files if f[3] == "not linked by the table"),
            "collisions": sum(1 for f in files if f[3] == "collision"), "not_documents": len(aside),
            "need_a_reading": len(needs)}


def documents(landed: list, aside: list) -> tuple:
    """capture.copy_all's output as build's three arguments."""
    listings = [(ref.sha256, capture.commission_name(p)) for kind, ref, p, _ in landed if kind == "listing"]
    declarations = [(ref.sha256, capture.commission_name(p)) for kind, ref, p, _ in landed if kind == "declaration"]
    return listings, declarations, [(os.path.basename(p), why) for p, why in aside]


def load(conn, schema: str, log=print) -> int:
    """Every candidate file of the old folder landed by hash, every listing
    read, the scans joined, under `schema`. Returns the row count."""
    started = jobrun.now()
    landed, aside = capture.copy_all(conn)
    counts = build(conn, schema, *documents(landed, aside))
    detail = ", ".join(f"{k} {v}" for k, v in counts.items()) + f", into {schema}"
    log("disclosures: " + detail)
    jobrun.record(JOB, True, detail, started, counts)
    return counts["rows"]


def stage(conn, schema: str, shared: bool = False) -> tuple:
    """Capture, build `schema`, and hold it to the lane's check: (green,
    counts, the check's lines). Green is rows read and no difference from
    the frozen site, nor any form, that a card does not name."""
    from registers.disclosures import check
    landed, aside = capture.copy_all(conn)
    with conn.transaction():
        counts = build(conn, schema, *documents(landed, aside), shared=shared)
    uncarded, lines = check.verdict(check.held(conn, table(schema, "declarations", shared)),
                                    *check.frozen(), check.carded())
    counts["uncarded"] = uncarded
    if not counts["rows"]:
        lines.append("no declaration read: nothing to publish")
    return bool(counts["rows"]) and not uncarded, counts, lines


def frozen_release() -> str:
    """The frozen release the check compares with, by its version folder."""
    from registers.disclosures import check
    return os.path.basename(os.path.realpath(os.path.dirname(os.path.dirname(check.HOME_JSON))))


def job(log=print) -> int:
    """qv4-disclosures-load: stage, check and publish into querynz_v4. A
    load that fails its check publishes nothing and the last published
    rows stay; the staged ones are kept for a look."""
    from support import db
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, db.LIVE) as conn:
        conn.execute("SET statement_timeout = '600s'")
        green, counts, lines = stage(conn, STAGING)
        detail = (f"{counts['rows']} declarations from {counts['listings']} listings, {counts['set_aside']} set aside, "
                  f"{counts['linked']} scans linked; against frozen release {frozen_release()}: {lines[0]}; "
                  f"{counts['uncarded']} differences with no card")
        if not green:
            for line in lines:
                log("disclosures: " + line)
            log("disclosures: RED, nothing published: " + detail)
            jobrun.record(JOB, False, "nothing published: " + detail, started, counts)
            return 1
        publish(conn, STAGING)
    log("disclosures: published: " + detail)
    jobrun.record(JOB, True, "published: " + detail, started, counts)
    return 0


def publish(conn, staging: str) -> None:
    """The lane's own tables wiped and refilled from the staged ones, and
    the views refreshed, in one transaction (contract: the lane)."""
    with conn.transaction():
        create_tables(conn, SCHEMA)
        wipe(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {SCHEMA}.{t} SELECT * FROM {staging}.{t}")
        conn.execute(f"INSERT INTO {PRIVATE}.donor_addresses SELECT * FROM {private_of(staging)}.donor_addresses")
        conn.execute(sql("publish.sql"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m registers.disclosures.load")
    ap.add_argument("--schema")
    ap.add_argument("--database", default="querynz_v4_sample")
    ap.add_argument("--job", action="store_true", help=f"{JOB}: capture, build, check and publish into querynz_v4")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    from support import db
    if not a.schema or not a.schema.startswith(("scratch_", "staging_")) or a.database == db.LIVE:
        print("disclosures: a session loads only a scratch or staging schema of the sample database")
        return 2
    with db.connect(db.OWNER_KEY, a.database) as conn:
        green, counts, lines = stage(conn, a.schema, shared=a.schema.startswith("scratch_"))
    for line in lines:
        print("disclosures: " + line)
    print("disclosures: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f", into {a.database}.{a.schema}: "
          + ("green" if green else "RED"))
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
