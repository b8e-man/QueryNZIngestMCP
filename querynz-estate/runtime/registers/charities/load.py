"""Loading (plan 1b.7): `load(conn, schema)` builds the reading's tables
under `schema` from the pages the capture lists, and `publish(conn, staging)`
moves them into `charities` and `charities_private` and makes the views, in
one transaction. `fill` in sample.py uses the same `build`.

Idempotent per listing: the reading's tables are dropped and made again and
every row is read again from the same pages inside one transaction, so a
second load of the same listing gives the same rows under the same keys (only
`loaded_at` moves). The capture's own tables are never touched. Items in
equal items out plus items set aside, page by page, in the `read_pages`
ledger; check.py holds the lane to it.

A charity's address for service goes to `charities_private.addresses`, never
to a table in `charities`; publish.sql shows it only where the charity is a
body corporate (queue: whether a charity's address for service is shown when
it may be a trustee's home; the default, until Arthur rules).

    python -m registers.charities.load [--schema scratch_charities_full] [--database querynz_v4_sample]
    python -m registers.charities.load --job      # qv4-charities-load: build in staging, check, publish

A session loads only a scratch or staging schema: it reads the listing and
the pages from querynz_v4 with the read-only login and writes into `schema`
of `database` with the owner's. `--job` builds into `STAGING` of querynz_v4,
publishes only when the reading reconciles and agrees with the register's own
view, and records the run. Every line printed is a count.
"""
import argparse
import collections
import decimal
import json
import os
import re
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.charities import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "charities"
PRIVATE = "charities_private"
JOB = "qv4-charities-load"
SCRATCH = "scratch_charities_full"
STAGING = "staging_charities_load"
TABLES = ("read_pages", "codes", "groups", "charities", "officers", "returns", "read_set_aside", "read_notes")
PRIVATE_TABLES = ("addresses", "address_parts", "officer_name_fields")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "read_pages": ("document", "entity_set", "rows", "typed", "set_aside", "skipped"),
    "codes": ("code_list", "entity", "code", "name", "document"),
    "groups": ("key", "number", "group_id", "name", "status", "registered_on", "deregistered_on",
               "source_modified_at", "absent_since") + _CITE,
    "charities": ("key", "number", "organisation_id", "name", "other_names", "status", "registered_on",
                  "deregistered_on", "deregistration_reason", "legal_structure", "legal_structure_other",
                  "charitable_purpose", "main_sector_id", "main_sector", "main_activity_id", "main_activity",
                  "main_beneficiary_id", "main_beneficiary", "group_key", "group_number",
                  "group_name", "group_type", "nzbn", "incorporation_number", "year_end_month", "year_end_day",
                  "annual_return_due_on", "source_modified_at", "absent_since") + _CITE,
    "officers": ("key", "officer_id", "charity_key", "organisation_id", "kind", "full_name", "first_name",
                 "middle_name", "last_name", "name_note", "suppressed", "role", "started_on", "ended_on", "ended_on_stated", "status",
                 "disqualified", "declared_not_disqualified", "source_modified_at", "absent_since") + _CITE,
    "returns": ("key", "return_id", "charity_key", "group_key", "organisation_id", "group_id", "period_end",
                "months_covered", "began_on", "tier_id", "tier", "currency", "audited", "modified_opinion", "opinion",
                "status_code") + tuple(read.HEADLINE) + ("figures", "material_expenses", "source_modified_at",
                                                         "absent_since") + _CITE,
    "read_set_aside": ("entity_set", "document", "place", "stage", "reason"),
    "read_notes": ("note", "count"),
    "addresses": ("key", "address_for_service", "document", "page", "place"),
    "address_parts": ("key", "field", "value", "why", "document", "page", "place"),
    "officer_name_fields": ("key", "field", "value", "why", "document", "page", "place"),
}
JSON_COLUMNS = ("figures", "material_expenses")


def private_of(schema: str) -> str:
    return PRIVATE if schema == SCHEMA else f"{schema}_private"


def table(schema: str, t: str, shared: bool = False) -> str:
    """`schema.t` (a private table: in the schema's private twin); in a
    schema every module shares (the sample's), the lane's tables carry its
    name: `schema.charities_t`."""
    where = private_of(schema) if t in PRIVATE_TABLES else schema
    return f"{where}.{SCHEMA}_{t}" if shared else f"{where}.{t}"


_NAMES = re.compile(r"(?<![A-Za-z0-9_])charities(_private)?\.")


def sql(name: str, schema: str = SCHEMA, shared: bool = False) -> str:
    """A file of this lane's SQL under `schema` (its private twin for
    `charities_private.`), rewritten in one pass; for tables.sql, the
    reading's part only (the capture makes its own)."""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    if name == "tables.sql":
        text = capture.READING + text.split(capture.READING, 1)[1]
    pre = f"{SCHEMA}_" if shared else ""
    return _NAMES.sub(lambda m: f"{private_of(schema) if m.group(1) else schema}.{pre}", text)


def create_tables(conn, schema: str, shared: bool = False) -> None:
    """The reading's tables, empty, under `schema` and its private twin. The
    capture's tables in the same schema are never dropped."""
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {private_of(schema)}")
    for t in TABLES + PRIVATE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table(schema, t, shared)} CASCADE")
    conn.execute(sql("tables.sql", schema, shared))


def _json(v):
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False, sort_keys=True,
                      default=lambda d: float(d) if isinstance(d, decimal.Decimal) else str(d))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(chr(34) + c + chr(34) for c in cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(_json(row.get(c)) if c in JSON_COLUMNS else row.get(c) for c in cols))
            n += 1
    return n


class Ledger:
    """Rows in, typed and set aside, page by page."""

    def __init__(self):
        self.pages = {}

    def open(self, entity_set: str):
        def on_page(sha, n):
            self.pages[sha] = {"document": sha, "entity_set": entity_set, "rows": n, "typed": 0, "set_aside": 0,
                               "skipped": 0}
        return on_page

    def typed(self, sha):
        self.pages[sha]["typed"] += 1

    def aside(self, sha):
        self.pages[sha]["set_aside"] += 1

    def close(self):
        for p in self.pages.values():
            p["skipped"] = p["rows"] - p["typed"] - p["set_aside"]
        return list(self.pages.values())


def build(conn, schema: str, pages: dict, read_bytes=read_bytes, only: dict = None, shared: bool = False,
          absent: dict = None) -> dict:
    """Read every listed page into the tables under `schema`. `pages`: feed
    set → [sha256], oldest first. `only`: feed set → the ids to read (the
    sample's); None for all. `absent`: sha256 → the day the newest full copy
    finished, for pages landed before it (read.absent_since): a row read from
    one carries that day as `absent_since`. Returns the counts."""
    absent = absent or {}
    t0 = time.monotonic()
    create_tables(conn, schema, shared)
    T = lambda t: table(schema, t, shared)
    ledger, notes, asides, counts = Ledger(), collections.Counter(), [], collections.Counter()
    pick = lambda s: None if only is None or s not in only else set(only[s])   # a set with no key line: whole

    codes = read.Codes()
    for lst in read.CODE_LISTS:
        for sha in pages.get(lst, ()):
            _, rows = read.parse_page(read_bytes(sha))
            n = codes.add_page(lst, rows, sha)
            ledger.pages[sha] = {"document": sha, "entity_set": lst, "rows": len(rows), "typed": n,
                                 "set_aside": len(rows) - n, "skipped": 0}
            for r in rows:
                if read.text(r.get("Name")) is None:
                    asides.append(read.aside(lst, sha, r.get(read._CODE_ID.get(lst, "Id")), "read", "a code with no name"))
    missing = codes.missing()
    if missing:
        raise LookupError(f"charities: no page of the code list(s) {', '.join(missing)} is listed; nothing is read")
    counts["codes"] = _copy(conn, T("codes"), COLUMNS["codes"],
                            (dict(zip(COLUMNS["codes"], e)) for e in codes.entries))

    def take(entity_set, reader, sink, on_aside=None):
        """Every row of a set's pages to `sink` (typed) or the catch log."""
        for sha, row, line in read.newest_first(pages.get(entity_set, []), entity_set, read_bytes,
                                                pick(entity_set), ledger.open(entity_set)):
            if line is not None:
                asides.append(line)
                ledger.aside(sha)
                continue
            out, why = reader(row, sha)
            if out is None:
                asides.append(read.aside(entity_set, sha, row[read.SETS[entity_set]], read.stage_of(why), why))
                ledger.aside(sha)
                if on_aside:
                    on_aside(row, why)
                continue
            out["absent_since"] = absent.get(sha)
            if out["absent_since"]:
                counts[f"{entity_set} absent from the newest full copy"] += 1
            sink(out)
            ledger.typed(sha)

    groups = []
    take("Groups", read.read_group, groups.append)
    by_gid = {g["group_id"]: g for g in groups}
    orgs, charities = [], {}
    take("Organisations", lambda r, sha: read.read_organisation(r, sha, codes, by_gid, notes), orgs.append,
         lambda r, why: charities.__setitem__(r["OrganisationId"], (None, why)))
    held = collections.Counter(o["number"] for o in orgs)
    kept = []
    for o in orgs:
        if held[o["number"]] > 1:
            why = f"the register's number is held by {held[o['number']]} organisations"
            asides.append(read.aside("Organisations", o["document"], o["organisation_id"], "key", why))
            ledger.pages[o["document"]]["typed"] -= 1
            ledger.aside(o["document"])
            charities[o["organisation_id"]] = (None, why)
        else:
            kept.append(o)
            charities[o["organisation_id"]] = (o["key"], None)
    counts["groups"] = _copy(conn, T("groups"), COLUMNS["groups"], groups)
    counts["charities"] = _copy(conn, T("charities"), COLUMNS["charities"], kept)
    counts["addresses"] = _copy(conn, T("addresses"), COLUMNS["addresses"],
                                (o for o in kept if o["address_for_service"] is not None))
    counts["address_parts"] = _copy(conn, T("address_parts"), COLUMNS["address_parts"],
                                    ({**p, "key": o["key"], "document": o["document"], "page": o["page"],
                                      "place": o["place"]} for o in kept for p in o["address_parts"]))
    name_fields = []
    del orgs, kept

    for entity_set, t, reader in (
            ("Officers", "officers", lambda r, sha: read.read_officer(r, sha, codes, charities, notes)),
            ("AnnualReturn", "returns", lambda r, sha: read.read_return(r, sha, codes, charities, by_gid, notes))):
        batch = []

        def sink(out, t=t, batch=batch):
            name_fields.extend({**p, "document": out["document"], "page": out["page"], "place": out["place"]}
                               for p in out.get("private_name_fields") or ())
            batch.append(out)
            if len(batch) >= 5000:
                counts[t] += _copy(conn, T(t), COLUMNS[t], batch)
                batch.clear()

        take(entity_set, reader, sink)
        counts[t] += _copy(conn, T(t), COLUMNS[t], batch)

    counts["officer_name_fields"] = _copy(conn, T("officer_name_fields"), COLUMNS["officer_name_fields"], name_fields)
    ledger_rows = ledger.close()
    if only is None:
        bad = [p for p in ledger_rows if p["skipped"]]
        if bad:
            raise AssertionError(f"charities: {len(bad)} page(s) do not reconcile (rows in ≠ typed + set aside)")
    _copy(conn, T("read_pages"), COLUMNS["read_pages"], ledger_rows)
    counts["set_aside"] = _copy(conn, T("read_set_aside"), COLUMNS["read_set_aside"], asides)
    _copy(conn, T("read_notes"), COLUMNS["read_notes"], ({"note": k, "count": v} for k, v in sorted(notes.items())))
    counts["pages"] = len(ledger_rows)
    counts["rows_in"] = sum(p["rows"] - p["skipped"] for p in ledger_rows)
    counts["seconds"] = round(time.monotonic() - t0, 1)
    for a in asides:
        counts[f"aside: {a['entity_set']}: {a['reason'] if a['stage'] != 'supersede' else 'read again on a later page'}"] += 1
    return dict(counts)


def listings(conn) -> dict:
    """Feed set → [sha256] oldest first, for every set this reading reads."""
    return {s: [sha for sha, _ in read.pages(conn, s)] for s in tuple(read.SETS) + read.CODE_LISTS}


def absences(conn) -> dict:
    """sha256 → the day the set's newest full copy finished, for every page landed before it (read.absent_since)."""
    out = {}
    for s in read.SETS:
        out.update(read.absent_since(conn, s))
    return out


def load(conn, schema: str, log=print) -> int:
    """Every listed page, read, under `schema` of the connection's database
    (the merge gate's staging step). Returns the rows typed."""
    started = jobrun.now()
    counts = build(conn, schema, listings(conn), absent=absences(conn))
    rows = counts["charities"] + counts["officers"] + counts["returns"] + counts["groups"]
    detail = ", ".join(f"{k} {v}" for k, v in counts.items() if not k.startswith("aside")) + f", into {schema}"
    log("charities: " + detail)
    jobrun.record(JOB, True, detail, started, {k: v for k, v in counts.items() if not k.startswith("aside")})
    return rows


def publish(conn, staging: str, log=print) -> None:
    """The reading's tables from `staging` (and its private twin) into
    `charities` and `charities_private`, and the views of publish.sql, in
    one transaction (contract: the lane). The capture's tables stay."""
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES + PRIVATE_TABLES:
            conn.execute(f"INSERT INTO {table(SCHEMA, t)} SELECT * FROM {table(staging, t)}")
        conn.execute(sql("publish.sql"))
    log(f"charities: published from {staging}")


def unchanged(conn, listed: dict) -> bool:
    """True when the published reading read exactly the pages listed now
    (register rule 10: rebuild only what changed)."""
    if conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.read_pages",)).fetchone()[0] is None:
        return False
    held = {r[0] for r in conn.execute(f"SELECT document FROM {SCHEMA}.read_pages")}
    return held == {sha for shas in listed.values() for sha in shas}


def job(log=print) -> int:
    """qv4-charities-load: build in STAGING of querynz_v4, hold it to the
    reading's own checks (every row reconciled, the register's view agreed),
    and publish only then. A reading that fails its own check publishes
    nothing."""
    from support import db
    from registers.charities import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        listed = listings(conn)
        if unchanged(conn, listed):
            log("charities: the listing is the one published; nothing loaded")
            jobrun.record(JOB, True, "unchanged: the listing is the one published", started, {})
            return 0
        with conn.transaction():
            counts = build(conn, STAGING, listed, absent=absences(conn))
        f = check.reading(conn, STAGING, conn, read_bytes)
        detail = (f"{counts['charities']} charities, {counts['officers']} officers, {counts['returns']} returns, "
                  f"{counts['set_aside']} set aside; " + ("; ".join(f["problems"]) or "reconciles, the view agrees"))
        if not f["ok"]:
            log("charities: RED, nothing published: " + detail)
            jobrun.record(JOB, False, "nothing published: " + detail, started, {})
            return 1
        publish(conn, STAGING, log)
    log("charities: published: " + detail)
    jobrun.record(JOB, True, "published: " + detail, started,
                  {k: v for k, v in counts.items() if not k.startswith("aside")})
    return 0


def main(argv=None) -> int:
    from support import db
    ap = argparse.ArgumentParser(prog="python -m registers.charities.load")
    ap.add_argument("--schema", default=SCRATCH)
    ap.add_argument("--database", default="querynz_v4_sample")
    ap.add_argument("--job", action="store_true", help="qv4-charities-load: build, check and publish into querynz_v4")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    if not a.schema.startswith(("scratch_", "staging_")):
        print("charities: a session loads only a scratch or staging schema")
        return 2
    started = jobrun.now()
    with db.connect(db.READ_KEY, "querynz_v4") as src:
        src.execute("SET statement_timeout = '60s'")
        pages = listings(src)
        absent = absences(src)
    with db.connect(db.OWNER_KEY, a.database) as conn:
        with conn.transaction():
            counts = build(conn, a.schema, pages, absent=absent)
    for k, v in counts.items():
        print(f"charities: {k}: {v}")
    jobrun.record(JOB, True, f"{counts['charities']} charities, {counts['officers']} officers, {counts['returns']} "
                  f"returns into {a.database}.{a.schema}", started,
                  {k: v for k, v in counts.items() if not k.startswith("aside")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
