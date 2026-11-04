"""Loading (plan 1b.7, 4.1). The merge gate's staging step calls `load` to
build this lane's tables under a staging schema of the real database, and
`publish` to move the rows into the lane's own tables in one transaction
and refresh the published views. `sample.fill` uses the same pieces.

Capture, the Commission's statements, the join, the reading, insert. The
run record goes to support.jobrun. The catch log reconciles: every return
landed is one row in `returns` or at least one line in `set_aside` at a
return's stage (recognise | read | declaration | join), never both, and
`files` holds every return landed (`counts`). Lines at stage `commission`
name a Commission file or row the lane could not use or could not answer.

    statements(conn=None)     the listing rows and the newest spreadsheet per year, with their catch lines
    build(landed, store, ...) every reading, then the join (a path with no year takes the form's title's): a Build
    load(conn, schema)        all of it into `schema`
    publish(conn, staging)    the staged tables into the lane's own, in one transaction
"""
import os
import re
from dataclasses import dataclass, field

from support import jobrun
from support import reader as rd
from support.docstore import sha256_file
from support.docstore.landing import read_bytes
from registers.candidate_returns import capture, commission, join, read

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "candidate_returns"
PRIVATE = "candidate_returns_private"
TABLES = ("files", "returns", "commission", "set_aside", "donors")
PRIVATE_TABLES = ("addresses",)
FILE_COLUMNS = ("document", "names", "placed_by", "year", "surname", "given_names", "electorate", "party", "status",
                "replaced_by", "stated", "listing", "sheet_key")
RETURN_COLUMNS = ("key", "document", "page", "place", "donations", "part_a", "part_c", "part_d", "donations_check",
                  "expenses", "part_f", "part_g", "expenses_check", "loans", "loans_check", "signed", "year_as_printed",
                  "candidate_as_printed", "party_as_printed", "electorate_as_printed", "read_from", "reader", "profile",
                  "profile_version", "loaded_at", "donors_check", "issue")
COMMISSION_COLUMNS = ("key", "source", "file", "file_name", "year", "surname", "given_names", "electorate", "party",
                      "donations", "expenses", "loans", "received", "link", "problems", "sheet")
DONOR_COLUMNS = ("key", "return_key", "document", "page", "place", "ordinal", "donor", "amount", "dates", "contributions",
                 "read_from", "reader", "profile", "profile_version", "loaded_at", "issue")
COLUMNS_OF = {"files": FILE_COLUMNS, "returns": RETURN_COLUMNS, "commission": COMMISSION_COLUMNS,
              "set_aside": ("document", "stage", "reason", "at"), "donors": DONOR_COLUMNS,
              "addresses": ("key", "document", "address", "cell")}
RETURN_STAGES = ("recognise", "read", "declaration", "join")          # `part-a` is a part's stage: its row stands


@dataclass
class Statements:
    listing: list = field(default_factory=list)        # (ListingRow, page sha256, key)
    sheets: dict = field(default_factory=dict)         # year → (file sha256, file name, [SheetRow])
    catch: list = field(default_factory=list)          # (file sha256, reason)


@dataclass
class Build:
    files: list = field(default_factory=list)          # dicts under FILE_COLUMNS
    returns: list = field(default_factory=list)        # dicts under RETURN_COLUMNS
    donors: list = field(default_factory=list)         # dicts under DONOR_COLUMNS, with the address beside (private)
    commission: list = field(default_factory=list)     # dicts under COMMISSION_COLUMNS
    set_aside: list = field(default_factory=list)      # (document, stage, reason)
    results: dict = field(default_factory=dict)        # sha256 → read.Result
    joined: object = None


def _sha(path: str, conn) -> str:
    return capture.copy_one(path, conn).sha256 if conn is not None else sha256_file(path)


def statements(conn=None, folder: str = None) -> Statements:
    """The Commission's listing rows (de-duplicated across pages kept on different days: rows shift between pages)
    and, per election, its newest spreadsheet that is a table. Each file is landed by hash when `conn` is given."""
    out = Statements()
    for year, paths in capture.listing_files(folder).items():
        seen = set()
        for path in paths:
            sha = _sha(path, conn)
            with open(path, encoding="utf-8", errors="replace") as f:
                rows = commission.listing_rows(f.read())
            if not rows:
                out.catch.append((sha, f"{os.path.basename(path)}: a listing page with no table rows (a challenge page "
                                       f"the browser kept?)"))
            for i, r in enumerate(rows, 1):
                k = (r.href, commission.fold(r.surname), commission.fold(r.electorate))
                if k in seen:
                    continue
                seen.add(k)
                out.listing.append((r, sha, f"{sha}/{i}"))
    for year, paths in capture.spreadsheet_files(folder).items():
        for path in reversed(paths):                                         # newest version first
            sha = _sha(path, conn)
            with open(path, "rb") as f:
                data = f.read()
            try:
                rows = commission.spreadsheet_rows(data, path, year)
            except commission.NotATable as e:
                out.catch.append((sha, f"{os.path.basename(path)}: refused: {e}"))
                continue
            out.sheets[year] = (sha, os.path.basename(path), rows)
            break
    return out


def year_of(names: list):
    """The election a file's names state (`candidate-returns__2023__…`, `2020_Labour-Party_…`), or None (`Uploads__…`)."""
    ys = set()
    for n in names:
        b = os.path.basename(n)
        m = re.match(r"candidate-returns__(\d{4})__", b) or re.match(r"(\d{4})[_-]", capture.held_name(b))
        if m:
            ys.add(int(m.group(1)))
    return ys.pop() if len(ys) == 1 else None


def build(landed: dict, st: Statements, store: rd.Store, data_of, loaded_at: str = None) -> Build:
    """`landed` is {sha256: [old path, ...]}; `data_of(sha256)` gives a return's bytes."""
    out = Build()
    held = {s: sorted({capture.held_name(p) for p in ps}) for s, ps in landed.items()}
    results = {s: read.read_return(data_of(s), s, store, loaded_at=loaded_at) for s in sorted(landed)}
    out.results = results
    years = {s: year_of(ps) for s, ps in landed.items()}
    for s, r in results.items():                     # a path with no year (`Uploads__…`): the form's own title, where read
        if years[s] is None and r.declaration is not None and r.declaration.year:
            years[s] = r.declaration.year
    sheet = {y: rows for y, (_, _, rows) in st.sheets.items()}
    j = join.join(held, [r for r, _, _ in st.listing], sheet, years)
    out.joined = j
    listing_key = {id(r): (sha, k) for r, sha, k in st.listing}
    sheet_key = {id(r): f"{sha}/{r.line}" for y, (sha, _, rows) in st.sheets.items() for r in rows}

    for r, page_sha, k in st.listing:
        out.commission.append({"key": k, "source": "listing", "file": page_sha, "file_name": "listing", "year": r.year,
                               "surname": r.surname, "given_names": r.given, "electorate": r.electorate, "party": r.party,
                               "donations": r.donations, "expenses": r.expenses, "loans": None, "received": True,
                               "link": r.href or None, "problems": "; ".join(r.problems) or None, "sheet": None})
    for y, (sha, name, rows) in st.sheets.items():
        for r in rows:
            out.commission.append({"key": sheet_key[id(r)], "source": "spreadsheet", "file": sha, "file_name": name,
                                   "year": r.year, "surname": r.surname, "given_names": r.given,
                                   "electorate": r.electorate, "party": r.party, "donations": r.donations,
                                   "expenses": r.expenses, "loans": r.loans, "received": r.received, "link": None,
                                   "problems": "; ".join(r.problems) or None, "sheet": r.sheet})
    for sha, why in st.catch:
        out.set_aside.append((sha, "commission", why))
    for r in j.sheet_no_document:
        sha = sheet_key[id(r)].split("/")[0]
        why = "the Commission writes that no return was received" if not r.received else "no held return answers"
        out.set_aside.append((sha, "commission", f"spreadsheet row {r.line} ({r.surname}, {r.electorate}): {why}"))
    for r in j.listing_not_held:
        out.set_aside.append((listing_key[id(r)][0], "commission", f"the listing links {r.href}, which is not held"))
    for r in j.listing_no_link:
        out.set_aside.append((listing_key[id(r)][0], "commission",
                              f"a listing row ({r.surname}, {r.electorate}) links no return"))

    unplaced = dict(j.unplaced)
    for sha in sorted(landed):
        p = j.placed.get(sha)
        row = {"document": sha, "names": " | ".join(held[sha]), "placed_by": None, "year": years.get(sha),
               "surname": None, "given_names": None, "electorate": None, "party": None, "status": None,
               "replaced_by": None, "stated": None, "listing": None, "sheet_key": None}
        if p is not None:
            row.update({"placed_by": p.how, "year": p.year, "surname": p.surname, "given_names": p.given,
                        "electorate": p.electorate, "party": p.party, "status": p.status, "replaced_by": p.replaced_by,
                        "stated": p.stated, "listing": listing_key[id(p.listing)][0] if p.listing is not None else None,
                        "sheet_key": sheet_key.get(id(p.sheet)) if p.sheet is not None else None})
        out.files.append(row)
        result = results[sha]
        for stage, reason in result.set_aside:
            out.set_aside.append((sha, stage, reason))
        if result.row is None:
            continue
        if p is None:
            out.set_aside.append((sha, "join", unplaced.get(sha, "not placed")))
            continue
        f = result.row["filed"]
        out.returns.append({**{c: result.row.get(c) for c in ("key", "document", "page", "place", "read_from", "reader",
                                                               "profile", "profile_version", "loaded_at")},
                            **{c: f.get(c) for c in RETURN_COLUMNS if c in f}})
        out.donors += [{**d, "donor": d["name"], "contributions": d["yes_no"]} for d in result.donors]
    return out


def counts(b: Build) -> dict:
    """The catch log's reconciliation: returns in = rows + returns set aside, and nothing both."""
    aside = {d for d, stage, _ in b.set_aside if stage in RETURN_STAGES}
    rows = {r["document"] for r in b.returns}
    docs = {f["document"] for f in b.files}
    return {"returns": len(docs), "rows": len(rows), "set_aside": len(aside), "both": len(rows & aside),
            "neither": len(docs - rows - aside), "reconciles": len(docs) == len(rows) + len(aside) and not rows & aside,
            "commission_lines": sum(1 for _, s, _ in b.set_aside if s == "commission"),
            "donor_rows": len(b.donors), "part_a_set_aside": sum(1 for _, s, _ in b.set_aside if s == "part-a")}


# ---------------------------------------------------------------- the database

def private_of(schema: str) -> str:
    return PRIVATE if schema == SCHEMA else f"{schema[:55]}_private"


def table(schema: str, t: str, shared: bool = False) -> str:
    """Every module fills one shared scratch schema for the sample, so there this lane's tables carry its name."""
    return f"{schema}.{SCHEMA}_{t}" if shared else f"{schema}.{t}"


def sql(name: str, schema: str = SCHEMA, shared: bool = False) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    pre = f"{SCHEMA}_" if shared else ""
    return re.sub(r"\bcandidate_returns(_private)?\.",
                  lambda m: f"{private_of(schema) if m.group(1) else schema}.{pre}", text)


def create_tables(conn, schema: str, shared: bool = False) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {private_of(schema)}")
    conn.execute(sql("tables.sql", schema, shared))
    conn.execute(sql("private.sql", schema, shared))


def wipe(conn, schema: str, shared: bool = False) -> None:
    for t in TABLES:
        conn.execute(f"DELETE FROM {table(schema, t, shared)}")
    for t in PRIVATE_TABLES:
        conn.execute(f"DELETE FROM {table(private_of(schema), t, shared)}")


def _insert(conn, name: str, columns: tuple, row: dict) -> None:
    conn.execute(f"INSERT INTO {name} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
                 "ON CONFLICT DO NOTHING", tuple(row.get(c) for c in columns))


def insert(conn, schema: str, b: Build, shared: bool = False) -> None:
    t = lambda name: table(schema, name, shared)
    for r in b.files:
        _insert(conn, t("files"), FILE_COLUMNS, r)
    for r in b.returns:
        _insert(conn, t("returns"), RETURN_COLUMNS, r)
    for r in b.commission:
        _insert(conn, t("commission"), COMMISSION_COLUMNS, r)
    for d in b.donors:
        _insert(conn, t("donors"), DONOR_COLUMNS, d)
        _insert(conn, table(private_of(schema), "addresses", shared), COLUMNS_OF["addresses"], d)
    for d, stage, reason in b.set_aside:
        conn.execute(f"INSERT INTO {t('set_aside')} (document, stage, reason) VALUES (%s, %s, %s)", (d, stage, reason))


def load(conn, schema: str, log=print) -> int:
    """Every in-window return of the old folder landed by hash, the Commission's statements landed beside them, and
    the lane's tables built under `schema`. Returns the row count."""
    started = jobrun.now()
    create_tables(conn, schema)
    wipe(conn, schema)
    landed = {}
    for ref, path, _ in capture.copy_all(conn):
        landed.setdefault(ref.sha256, []).append(path)
    st = statements(conn)
    b = build(landed, st, rd.Store(), read_bytes)
    insert(conn, schema, b)
    c = counts(b)
    detail = (f"{c['returns']} returns: {c['rows']} rows, {c['set_aside']} set aside (reconciles: {c['reconciles']}); "
              f"{c['commission_lines']} Commission lines; into {schema}")
    log("candidate_returns: " + detail)
    jobrun.record("qv4-candidate-returns-load", c["reconciles"], detail, started, c)
    if not c["reconciles"]:
        raise RuntimeError("candidate_returns: the catch log does not reconcile: " + detail)
    return c["rows"]


def publish(conn, staging: str) -> None:
    """The lane's own tables wiped and refilled from the staged ones, and the views refreshed, in one transaction
    (contract: the lane)."""
    with conn.transaction():
        create_tables(conn, SCHEMA)
        wipe(conn, SCHEMA)
        for t in TABLES:
            cols = ", ".join(COLUMNS_OF[t])
            conn.execute(f"INSERT INTO {SCHEMA}.{t} ({cols}) SELECT {cols} FROM {staging}.{t}")
        for t in PRIVATE_TABLES:
            cols = ", ".join(COLUMNS_OF[t])
            conn.execute(f"INSERT INTO {PRIVATE}.{t} ({cols}) SELECT {cols} FROM {private_of(staging)}.{t}")
        conn.execute(sql("publish.sql"))


def main(argv=None) -> int:
    """The nightly job's entry (`python -m registers.candidate_returns.load`, `qv4-candidate-returns-load`): stage
    under `staging_candidate_returns_load`, then publish, as the merge gate's staging step does; `--schema` builds
    there and stops (a scratch proof)."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="registers.candidate_returns.load")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", help="build here and stop (a scratch proof); default: stage and publish")
    a = ap.parse_args(argv)
    from support import db
    with db.connect(db.OWNER_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '600s'")
        if a.schema:
            rows = load(conn, a.schema)
            conn.commit()
            print(f"candidate_returns: {rows} rows into {a.database}.{a.schema}")
            return 0
        staging = "staging_candidate_returns_load"
        load(conn, staging)
        conn.commit()
        publish(conn, staging)
        conn.commit()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
