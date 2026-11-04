"""Loading (step 5.3): `build(conn, schema, cases)` reads every held abstract into the reading's tables under `schema`;
`publish(conn, staging)` moves them into `real_estate_authority` and makes the views, in one transaction.

Rebuilt whole every load (regenerable). Items in equal decisions read plus set aside; the build raises if not.

    python -m registers.real_estate_authority.load [--schema staging_…|scratch_…] [--database querynz_v4]
    python -m registers.real_estate_authority.load --job

Every line printed is a count.
"""
import argparse
import json
import os
import sys
import time

from support import jobrun
from support.docstore.landing import read_bytes
from registers.real_estate_authority import capture, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "real_estate_authority"
JOB = "qv4-real-estate-authority-load"
STAGING = "staging_real_estate_authority_load"
TABLES = ("decisions", "parties", "read_set_aside")
_CITE = ("document", "page", "place", "read_from", "reader", "profile", "profile_version")
COLUMNS = {
    "decisions": ("key", "case_id", "complaint_number", "listed_body", "decided_by", "appeal", "citation", "decided_on",
                  "year", "decision", "decision_note", "penalty", "penalty_kinds", "penalty_names_address",
                  "complaint_type", "transaction_type", "chairperson", "charge", "act_sections", "code_sections",
                  "history", "parties_named", "suppressed", "abstract_url") + _CITE,
    "parties": ("key", "decision_key", "case_id", "seq", "name", "licence_number", "kind", "role", "suppressed",
                "decided_on", "decision") + _CITE,
    "read_set_aside": ("document", "place", "stage", "reason"),
    "suppressed_parties": ("key", "decision_key", "name", "licence_number", "document", "place"),
    "abstract_fields": ("key", "label", "text", "document"),
}
#: in the schema's private twin (`<schema>_private`; ruling 142): what the lane's own tables leave out, kept whole
PRIVATE_TABLES = ("suppressed_parties", "abstract_fields")


def profile_version() -> int:
    from support import profiles
    try:
        return int(profiles.current()[read.PROFILE]["version"])
    except KeyError:
        with open(os.path.join(HERE, "profile-proposed.jsonl"), encoding="utf-8") as f:
            return max(json.loads(l)["version"] for l in f if l.strip() and json.loads(l)["slug"] == read.PROFILE)


def create_tables(conn, schema: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}_private")
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {schema}.{t} CASCADE")
    for t in PRIVATE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {schema}_private.{t} CASCADE")
    conn.execute(capture.reading_sql(schema))


def _copy(conn, name: str, cols: tuple, rows) -> int:
    n = 0
    with conn.cursor().copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(tuple(json.dumps(row[c]) if c == "history" else row.get(c) for c in cols))
            n += 1
    return n


def listing(conn, schema: str = SCHEMA) -> list:
    """Every case whose abstract is landed: [{case_id, year, decision_date, body, abstract}] by case."""
    cur = conn.execute(f"SELECT case_id, year, decision_date, body, abstract FROM {schema}.cases "
                       f"WHERE abstract IS NOT NULL ORDER BY case_id")
    return [dict(zip(("case_id", "year", "decision_date", "body", "abstract"), r)) for r in cur]


def build(conn, schema: str, cases: list, read_bytes=read_bytes, version: int = None) -> dict:
    t0 = time.monotonic()
    version = version or profile_version()
    create_tables(conn, schema)
    decisions, parties, asides = [], [], []
    private = {t: [] for t in PRIVATE_TABLES}
    for c in cases:
        out = read.read_abstract(read_bytes(c["abstract"]), c["abstract"], version, c)
        if out["decision"]:
            decisions.append(out["decision"])
        parties += out["parties"]
        asides += out["set_aside"]
        for t in PRIVATE_TABLES:
            private[t] += out.get(t) or []
    if len(cases) != len(decisions) + len(asides):
        raise AssertionError(f"{SCHEMA}: {len(cases)} abstracts in, {len(decisions)} read + {len(asides)} set aside")
    return {"abstracts": len(cases),
            "decisions": _copy(conn, f"{schema}.decisions", COLUMNS["decisions"], decisions),
            "parties": _copy(conn, f"{schema}.parties", COLUMNS["parties"], parties),
            "set_aside": _copy(conn, f"{schema}.read_set_aside", COLUMNS["read_set_aside"], asides),
            **{t: _copy(conn, f"{schema}_private.{t}", COLUMNS[t], rows) for t, rows in private.items()},
            "suppressed": sum(d["suppressed"] for d in decisions),
            "seconds": round(time.monotonic() - t0, 1)}


def load(conn, schema: str, log=print) -> int:
    """The merge gate's staging step (support/staging)."""
    from registers.real_estate_authority import check
    counts = build(conn, schema, listing(conn))
    problems = check.reading(conn, schema)
    log(f"{SCHEMA}: {counts['decisions']} decisions, {counts['parties']} parties, {counts['set_aside']} set aside into "
        f"{schema}; " + ("; ".join(problems) or "reconciles"))
    return counts["decisions"]


def publish(conn, staging: str, log=print) -> None:
    with conn.transaction():
        create_tables(conn, SCHEMA)
        for t in TABLES:
            conn.execute(f"INSERT INTO {SCHEMA}.{t} SELECT * FROM {staging}.{t}")
        for t in PRIVATE_TABLES:
            conn.execute(f"INSERT INTO {SCHEMA}_private.{t} SELECT * FROM {staging}_private.{t}")
        with open(os.path.join(HERE, "publish.sql"), encoding="utf-8") as f:
            conn.execute(f.read())
    log(f"{SCHEMA}: published from {staging}")


def job(log=print) -> int:
    """qv4-real-estate-authority-load: build in staging, hold it to the reading's checks, publish only then."""
    from support import db
    from registers.real_estate_authority import check
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, "querynz_v4") as conn:
        conn.execute("SET statement_timeout = '600s'")
        with conn.transaction():
            counts = build(conn, STAGING, listing(conn))
        problems = check.reading(conn, STAGING)
        detail = (f"{counts['decisions']} decisions, {counts['parties']} parties, {counts['suppressed']} suppressed, "
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
    ap = argparse.ArgumentParser(prog="python -m registers.real_estate_authority.load")
    ap.add_argument("--schema", default="staging_real_estate_authority_session")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--job", action="store_true")
    a = ap.parse_args(argv)
    if a.job:
        return job()
    if not a.schema.startswith(("scratch_", "staging_")):
        print(f"{SCHEMA}: a session loads only a scratch or staging schema")
        return 2
    from registers.real_estate_authority import check
    with db.connect(db.OWNER_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '600s'")
        with conn.transaction():
            counts = build(conn, a.schema, listing(conn))
        problems = check.reading(conn, a.schema)
    for k, v in counts.items():
        print(f"{SCHEMA}: {k}: {v}")
    print(f"{SCHEMA}: check: " + ("; ".join(problems) or "reconciles"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
