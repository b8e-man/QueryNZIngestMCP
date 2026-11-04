"""The lane's checks: against what it read, and against the register itself.
Prints counts only and exits 1 when any check fails.

1. **The capture's measure** (`capture.measure`, as the capture had it): the
   newest full pass of Organisations, counted from the held pages, against
   the feed's own count at the pass's start and the register's count of
   registered charities asked now (two requests through the fetch gate). The
   register moves, so a difference passes only when no larger than the rows
   it marks modified after the moment compared: during the pass, for the
   pass's own count; since the pass began, for the count asked now.
2. **Every row of every captured page is a typed row or a set-aside with
   its reason** (the reconciliation): every page the capture lists for a set
   is in the `read_pages` ledger, each page's rows equal its typed rows plus
   its catch-log lines, and the tables and the catch log hold exactly those.
3. **The register's own count on the capture day.** The feed's own count of
   each set at the start of its full pass against the rows landed; and the
   register's count of registered charities landed with the newest full pass
   of Organisations (`read.registered_count`), or, for a pass before the
   capture landed it, the count the capture session asked on 20 October 2026
   (`REGISTER_COUNT`), against the registered charities held, within the
   organisations the register marks modified after the count.
4. **The register's own view agrees:** its `vOrganisations` names each
   charity's main sector, activity and beneficiary and its group; ours must
   give the same names for every charity captured in the same state.
5. **No officer name column holds a date or an address** (`read.name_fault`)
   once the reading has withheld them.

    python -m registers.charities.check [--offline]
    python -m registers.charities.check --schema scratch_charities_full [--database querynz_v4_sample]

Run bare (as the board runs it) it reads the lane's live tables, `charities`
in querynz_v4, with the read-only login, and holds the `pub.` views to them
(row counts only); the private twin carries no grant to that login, and no
check here reads it. `--schema` names a session's scratch proof, read in
querynz_v4_sample with the owner's login unless `--database` says otherwise.
`--offline` leaves out check 1 (no request is made). The job's own run
(`load.job`) holds a reading to checks 2 to 5 before it publishes.
"""
import argparse
import collections
import contextlib
import datetime as dt
import json
import sys

from registers.charities import capture, load, read

REGISTER_COUNT = {"registered": 29265, "organisations": 46132,
                  "at": dt.datetime(2026, 10, 20, 7, 30, tzinfo=read.NZ),
                  "source": "the feed's $inlinecount for RegistrationStatus eq 'Registered', asked by the "
                            "charities-capture session (docs/merges/charities-capture-1.md); passes from the next "
                            "full copy land the count as a document"}
TABLE_OF = {"Groups": "groups", "Organisations": "charities", "Officers": "officers", "AnnualReturn": "returns"}
NAME_COLUMNS = ("full_name", "first_name", "middle_name", "last_name")
LIVE, SAMPLE = "querynz_v4", "querynz_v4_sample"
#: each published view and the lane's table it shows, row for row
VIEWS = {"pub.charities": "charities", "pub.charity_officers": "officers", "pub.charity_returns": "returns"}


def outside(conn, opener=None, read_bytes=None) -> dict:
    """Check 1: the capture's measure, judged against the rows the register
    moved (two requests through the gate; `opener` for tests)."""
    from support.docstore.landing import read_bytes as rb
    read_bytes = read_bytes or rb
    opener = opener or (lambda url, timeout: capture.fg.open_url(url, timeout=timeout, positions_dir=capture.POSITIONS))
    m = capture.measure(conn, opener=opener, read=read_bytes)
    if "pass_id" not in m:
        return {**m, "ok": False}
    started = conn.execute(f"SELECT started_at FROM {capture.SCHEMA}.capture_passes WHERE pass_id = %s",
                           (m["pass_id"],)).fetchone()[0]
    moved_in_pass = 0
    for (sha,) in conn.execute(f"SELECT sha256 FROM {capture.SCHEMA}.capture_pages WHERE pass_id = %s", (m["pass_id"],)):
        moved_in_pass += sum(1 for r in capture.parse_page(read_bytes(sha))[1]
                             if (read.feed_moment(r.get("ModifiedOn")) or started) > started)
    f = opener(capture.count_url("Organisations", "OrganisationId",
                                 f"ModifiedOn ge {capture.odata_datetime(started)}"), 60)
    if f.blocked or f.status != 200:
        return {**m, "ok": False, "detail": f"the register's count of modified rows could not be read: {f.blocked or f.status}"}
    moved_since, _ = capture.parse_page(f.body)
    rows_ok = abs(m["rows_held"] - (m["stated_at_start"] or 0)) <= moved_in_pass
    reg_ok = abs(m["difference"]) <= moved_since
    return {**m, "modified_during_the_pass": moved_in_pass, "modified_since_the_pass_began": moved_since,
            "ok": rows_ok and reg_ok}


def reconcile(conn, schema: str, listed: dict, shared: bool = False) -> list:
    """Problems, as plain lines; empty when every row is accounted for.
    `listed`: feed set → [sha256] the capture lists."""
    T = lambda t: load.table(schema, t, shared)
    out = []
    ledger = {r[0]: r[1:] for r in conn.execute(
        f"SELECT document, entity_set, rows, typed, set_aside, skipped FROM {T('read_pages')}")}
    for s, shas in listed.items():
        missing = [x for x in shas if x not in ledger]
        if missing:
            out.append(f"{s}: {len(missing)} listed page(s) not read")
    for sha, (s, rows, typed, aside, skipped) in ledger.items():
        if rows != typed + aside or skipped:
            out.append(f"{s} page {sha[:12]}: {rows} rows, {typed} typed + {aside} set aside, {skipped} passed over")
    by_set = collections.defaultdict(lambda: [0, 0])
    for s, rows, typed, aside, skipped in ledger.values():
        by_set[s][0] += typed
        by_set[s][1] += aside
    asides = dict(conn.execute(f"SELECT entity_set, count(*) FROM {T('read_set_aside')} GROUP BY 1").fetchall())
    codes = dict(conn.execute(f"SELECT code_list, count(*) FROM {T('codes')} GROUP BY 1").fetchall())
    for s, (typed, aside) in by_set.items():
        if s in TABLE_OF:
            held = conn.execute(f"SELECT count(*) FROM {T(TABLE_OF[s])}").fetchone()[0]
        else:
            held = codes.get(s, 0)
        if held != typed:
            out.append(f"{s}: the ledger says {typed} typed, the table holds {held}")
        if asides.get(s, 0) != aside:
            out.append(f"{s}: the ledger says {aside} set aside, the catch log holds {asides.get(s, 0)}")
    unreasoned = conn.execute(f"SELECT count(*) FROM {T('read_set_aside')} WHERE coalesce(reason, '') = '' "
                              "OR coalesce(stage, '') = ''").fetchone()[0]
    if unreasoned:
        out.append(f"{unreasoned} catch-log line(s) without a stage or a reason")
    return out


def register_count(capture_conn) -> dict:
    """The register's count of registered charities to hold the reading to:
    the one landed with the newest full pass of Organisations, else the
    capture session's of 20 October 2026."""
    landed = read.registered_count(capture_conn)
    if landed:
        return {"registered": landed[0], "at": landed[1], "source": f"landed with the pass, document {landed[2]}"}
    return REGISTER_COUNT


def counts(conn, schema: str, capture_conn, read_bytes, shared: bool = False) -> dict:
    """The held copy against the register's own counts (check 3)."""
    T = lambda t: load.table(schema, t, shared)
    out = {"sets": {}}
    for s in ("Organisations", "Officers", "AnnualReturn", "Groups"):
        st = read.stated(capture_conn, s)
        if st is None:
            out["sets"][s] = {"held": None}
            continue
        stated, landed, started, finished = st
        out["sets"][s] = {"stated_at_pass_start": stated, "landed": landed,
                          "pass": f"{started.isoformat(timespec='minutes')} to {finished.isoformat(timespec='minutes')}",
                          "typed": conn.execute(f"SELECT count(*) FROM {T(TABLE_OF[s])} WHERE absent_since IS NULL").fetchone()[0],
                          "set_aside": conn.execute(f"SELECT count(*) FROM {T('read_set_aside')} WHERE entity_set = %s "
                                                    "AND stage <> 'supersede'", (s,)).fetchone()[0]}
    reg = register_count(capture_conn)
    at = reg["at"]
    typed_reg, typed_after = conn.execute(
        f"SELECT count(*) FILTER (WHERE status = 'Registered'), count(*) FILTER (WHERE source_modified_at >= %s) "
        f"FROM {T('charities')} WHERE absent_since IS NULL", (at,)).fetchone()       # the register's count: rows it still holds
    aside_reg = aside_after = 0
    places = collections.defaultdict(set)
    for doc, place in conn.execute(f"SELECT document, place FROM {T('read_set_aside')} WHERE entity_set = 'Organisations' "
                                   "AND stage <> 'supersede'"):
        places[doc].add(place)
    for doc, want in places.items():
        for r in read.parse_page(read_bytes(doc))[1]:
            if f"OrganisationId={r['OrganisationId']}" in want:
                aside_reg += read.text(r.get("RegistrationStatus")) == "Registered"
                m = read.feed_moment(r.get("ModifiedOn"))
                aside_after += bool(m and m >= at)
    held = typed_reg + aside_reg
    moved = typed_after + aside_after
    diff = held - reg["registered"]
    out["registered"] = {"register_on_capture_day": reg["registered"], "register_source": reg["source"],
                         "register_asked_at": at.isoformat(timespec="minutes"), "held": held, "typed": typed_reg,
                         "set_aside": aside_reg, "difference": diff, "modified_after_the_count": moved,
                         "ok": abs(diff) <= moved}
    return out


def resolution(conn, schema: str, v_pages: list, read_bytes, shared: bool = False) -> dict:
    """Ours against the register's own `vOrganisations` names (check 4)."""
    T = lambda t: load.table(schema, t, shared)
    ours = {r[0]: r[1:] for r in conn.execute(
        f"SELECT organisation_id, main_sector, main_activity, main_beneficiary, group_name, source_modified_at "
        f"FROM {T('charities')}")}
    fields = ("MainSectorName", "MainActivityName", "MainBeneficiaryName", "GroupName")
    out = collections.Counter()
    seen = set()
    for sha in reversed(v_pages):
        for r in read.parse_page(read_bytes(sha))[1]:
            oid = r["OrganisationId"]
            if oid in seen or oid not in ours:
                continue
            seen.add(oid)
            mine = ours[oid]
            if read.feed_moment(r.get("ModifiedOn")) != mine[4]:
                out["moved between the two captures"] += 1
                continue
            out["compared"] += 1
            for i, f in enumerate(fields):
                if read.text(r.get(f)) != mine[i]:
                    out[f"{f} differs"] += 1
    out["not in the view"] = len(set(ours) - seen)
    return dict(out)


def names(conn, schema: str, shared: bool = False) -> dict:
    """Check 5: officer name columns that still hold a date or an address,
    by column (counts; the values are never read out)."""
    T = lambda t: load.table(schema, t, shared)
    out = collections.Counter()
    cols = ", ".join(NAME_COLUMNS)
    for row in conn.execute(f"SELECT {cols} FROM {T('officers')}"):
        for c, v in zip(NAME_COLUMNS, row):
            if read.name_fault(v):
                out[c] += 1
    return dict(out)


def reading(conn, schema: str, capture_conn, read_bytes, shared: bool = False) -> dict:
    """Checks 2 to 5: the reading held to its pages and to the register."""
    listed = load.listings(capture_conn)
    lines = reconcile(conn, schema, listed, shared)
    c = counts(conn, schema, capture_conn, read_bytes, shared)
    v = resolution(conn, schema, [s for s, _ in read.pages(capture_conn, "vOrganisations")], read_bytes, shared)
    differs = sum(n for k, n in v.items() if k.endswith("differs"))
    faults = names(conn, schema, shared)
    problems = list(lines)
    if not c["registered"]["ok"]:
        problems.append(f"registered charities: held {c['registered']['held']}, the register "
                        f"{c['registered']['register_on_capture_day']}, beyond the {c['registered']['modified_after_the_count']} moved")
    if differs or not v.get("compared"):
        problems.append(f"the register's view: {differs} name(s) differ over {v.get('compared', 0)} compared")
    if faults:
        problems.append(f"officer name columns holding a date or an address: {faults}")
    return {"reconciles": not lines, "problems": problems, "counts": c, "resolution": v, "name_faults": faults,
            "ok": not problems}


def views(conn) -> list:
    """The published views against the lane's tables they show: problems,
    as plain lines (counts only)."""
    out = []
    for v, t in VIEWS.items():
        if conn.execute("SELECT to_regclass(%s)", (v,)).fetchone()[0] is None:
            out.append(f"{v} is not published")
            continue
        shown = conn.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
        held = conn.execute(f"SELECT count(*) FROM {load.table(load.SCHEMA, t)}").fetchone()[0]
        if shown != held:
            out.append(f"{v} shows {shown} rows, {load.SCHEMA}.{t} holds {held}")
    return out


def target(schema: str, database: str = None) -> tuple:
    """(login, database) to read `schema` in: the live schema in querynz_v4
    with the read-only login; a scratch proof in the sample with the owner's
    (a session's scratch schema carries no grant to the reader)."""
    from support import db
    database = database or (LIVE if schema == load.SCHEMA else SAMPLE)
    return (db.READ_KEY if database == LIVE else db.OWNER_KEY), database


def main(argv=None) -> int:
    from support import db
    from support.docstore.landing import read_bytes
    ap = argparse.ArgumentParser(prog="python -m registers.charities.check")
    ap.add_argument("--schema", default=load.SCHEMA, help="the lane's live tables; a session's scratch schema for its proof")
    ap.add_argument("--database", help=f"{LIVE} for the live schema, {SAMPLE} for any other")
    ap.add_argument("--offline", action="store_true", help="leave out the capture's measure (no request)")
    a = ap.parse_args(argv)
    key, database = target(a.schema, a.database)
    with contextlib.ExitStack() as stack:
        src = stack.enter_context(db.connect(db.READ_KEY, LIVE))
        src.execute("SET statement_timeout = '60s'")
        conn = src if (key, database) == (db.READ_KEY, LIVE) else stack.enter_context(db.connect(key, database))
        conn.execute("SET statement_timeout = '120s'")
        if conn.execute("SELECT to_regclass(%s)", (load.table(a.schema, "read_pages"),)).fetchone()[0] is None:
            print(f"charities: check RED: nothing loaded under {database}.{a.schema} (no read_pages)")
            return 1
        f = {"reading": reading(conn, a.schema, src, read_bytes)}
        if a.schema == load.SCHEMA:
            f["views"] = views(conn)
        if not a.offline:
            f["capture_measure"] = outside(src, read_bytes=read_bytes)
    problems = f["reading"]["problems"] + f.get("views", [])
    if not a.offline and not f["capture_measure"]["ok"]:
        problems.append("the capture's measure fails")
    ok = not problems
    held = f["reading"]["counts"]["sets"]
    print(f"charities: check {'green' if ok else 'RED'} on {database}.{a.schema}: "
          + ", ".join(f"{s} {n.get('typed')}" for s, n in held.items()) + "".join(f"; {p}" for p in problems))
    print(json.dumps(f, indent=1, default=str))
    print("charities: check " + ("green" if ok else "RED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
