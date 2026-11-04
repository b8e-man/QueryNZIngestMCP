"""The lane's check against the outside world (contract: the lane): the
MCP's courts corpus against what the lane made of it, and the reading's own
account.

  1. The count: every record of the corpus (the pull's arrivals, one per
     record id) is a `documents` row whose outcome is read, waiting on a
     reader (the page reader for a page with no text layer, the text reader
     for the model reading), set aside, or caught; a record in none fails,
     and so does a row read with no reading behind it (a judgment row, a case
     row or a sheet). The old listing's judgments the corpus lacks are
     counted as catch-log lines (stage `listing`), never rows.
  2. parsed / partial / unparsed, and the per-field missing counts.
  3. Suppression: judgments flagged and their kinds, names withheld; a
     published party name in a judgment under suppression (the Crown and a
     court-printed initial apart) fails; a model-read name on a document a
     suppression reaches (judges, counsel, agencies and the Crown apart)
     fails; a withheld name present in a published table fails; a row
     flagged under a suppression whose name is not kept whole, with the
     source's words, in courts_private.withheld_names fails (ruling 142).
  4. Every role a counsel line is "for" held by a party of the caption
     (`caption.roles_unaccounted`), re-read from the stored readings of a
     fixed sample of judgments: more than `ROLES_TOLERATED` short fails. A
     judgment whose unaccounted roles are the court's own printing (an
     intervener the caption does not list; an appeal captioned Plaintiff and
     Defendant) is counted apart with its reason
     (`caption.roles_source_exception`), never as short.
  6. Identifying details (Arthur, 3 November 2026) are private: counted by
     kind from `courts_private.identifiers` where the login can read it;
     a published view or a reading table with a column named for a kind of
     detail fails, so does a `pub.` view that reads any `_private` table, a
     publish.sql that names the private schema or the table, and a detail
     whose document is not a document of the reading. One view is ruled
     (ruling 1, 3 November 2026): `pub.court_company_numbers`, a company's
     NZBN or company number by document, kind, value and page, for the
     links lane, held to its exact text and its four columns.
  5. The profile check (ruling 130): every document read by the text reader,
     or waiting on it, has its piece count by its profile's reading rule; a
     document under a whole rule is within its budget; a document the rule
     cannot split is counted set aside at read, never waiting. The counts of
     documents by pieces needed, and the pieces by profile, are printed.

  7. The extract lists (Arthur, 3 November 2026): the lane's code against
     each profile's extract list (`extracts.problems`, support/profiles/
     align.py), each `lands` column against the database's catalog, and
     every document read or waiting on the text reader recorded in
     docs.extractions for every field it has had (`extracts.expected`);
     `extraction.behind` printed per profile.
  8. The MCP's own judgment date (`doc_date`) and citation beside the
     document's reading (Arthur, 3 November 2026): agreements,
     disagreements (a few record keys, never a name) and the judgments
     the MCP's filled where the document gave none (`mcp_agreement`).

    account(conn, schema, shared=False)    dict
    python -m registers.courts.check [--schema courts] [--database querynz_v4] [--sample]

Read-only. Exit 1 on a failure.
"""
import sys

import os
import re

from registers.courts import capture
from registers.courts import identifiers as IDS
from registers.courts import load as L
from registers.courts import model_read
from registers.courts import pieces as PC
from registers.courts import read as R

#: a column of that name in a published view or a reading table would carry an identifying detail
FORBIDDEN_COLUMNS = {k for k in IDS.KINDS if k != "other"} | {"identifier", "identifiers", "home_address",
                                                               "residential_address", "street_address", "dob"}
ROLES_TOLERATED = 2
ROLES_SAMPLE = 200          # judgments re-read for the counsel-role check (lessons: a check scans a fixed sample)


def account(conn, schema: str = L.SCHEMA, shared: bool = False, mcp_schema: str = None) -> dict:
    t = lambda name: L.table(schema, name, shared)  # noqa: E731
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
    out = {"failures": []}
    docs = q(f"SELECT key, document, kind, outcome, profile FROM {t('documents')}")
    out["records"] = len(docs)
    out["outcomes"] = dict(q(f"SELECT outcome, count(*) FROM {t('documents')} GROUP BY 1 ORDER BY 1"))
    out["profiles"] = dict(q(f"SELECT coalesce(profile, '(none)'), count(*) FROM {t('documents')} GROUP BY 1 ORDER BY 2 DESC"))
    allowed = {"read", R.WAIT_PAGES, R.WAIT_TEXT, "set aside", "caught"}
    for key, _, _, outcome, _ in docs:
        if outcome not in allowed:
            out["failures"].append(f"{key[-40:]}: outcome {outcome!r} is none of read, waiting, set aside, caught")
    # a record the pull took that the lane has no row for
    if mcp_schema or not shared:
        ms = mcp_schema or capture.MCP_SCHEMA
        held = conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'arrivals'", (ms,)).fetchone()
        if held:
            # by the load's stamp (every row's loaded_at): what the pull landed after the load read it is the next load's
            stamp = q(f"SELECT min(loaded_at) FROM {t('documents')}")[0][0]
            taken = q(f"SELECT count(DISTINCT record_id) FROM {ms}.arrivals WHERE corpus = %s "
                      f"AND (%s::timestamptz IS NULL OR landed_at <= %s::timestamptz)", capture.CORPUS, stamp, stamp)[0][0]
            out["taken by the pull"] = taken
            mcp_rows = sum(1 for d in docs if not d[0].startswith(capture.OWN_PREFIX))
            if taken != mcp_rows:
                out["failures"].append(f"the pull took {taken} records, the lane has {mcp_rows} document rows from it")
    # each file the own capture landed (ruling 140) is one row, unless the MCP holds the same file by hash
    own_rows = sum(1 for d in docs if d[0].startswith(capture.OWN_PREFIX))
    if conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'own_files'",
                    (L.SCHEMA,)).fetchone():
        mcp_docs = {d[1] for d in docs if d[1] and not d[0].startswith(capture.OWN_PREFIX)}
        stamp = q(f"SELECT min(loaded_at) FROM {t('documents')}")[0][0]
        landed = {r[0] for r in q(f"SELECT DISTINCT sha256 FROM {L.SCHEMA}.own_files WHERE status = 'landed' AND sha256 IS NOT NULL "
                                  f"AND (%s::timestamptz IS NULL OR fetched_at <= %s::timestamptz)", stamp, stamp)}
        out["landed by the own capture"] = len(landed)
        expected = len(landed - mcp_docs)
        if expected != own_rows:
            out["failures"].append(f"the own capture landed {len(landed)} files, {len(landed) - expected} of them the MCP's "
                                   f"by hash, so {expected} rows are owed; the lane has {own_rows}")
    elif own_rows:
        out["failures"].append(f"{own_rows} rows of the own capture with no ledger behind them")
    # a row read has its reading: a judgment, a case, or a sheet (citation, case numbers or a date read)
    judged = {r[0] for r in q(f"SELECT document FROM {t('judgments')}")}
    cased = {r[0] for r in q(f"SELECT document FROM {t('cases')}")}
    sheets = {r[0] for r in q(f"SELECT document FROM {t('documents')} WHERE outcome IN ('read', %s) AND "
                              f"(citation IS NOT NULL OR cardinality(case_numbers) > 0 OR dated IS NOT NULL OR summary IS NOT NULL)", R.WAIT_TEXT)}
    for key, doc, kind, outcome, profile in docs:
        if outcome in ("read", R.WAIT_TEXT):
            if profile in R.JUDGMENT_SLUGS and doc not in judged:
                out["failures"].append(f"{key[-40:]}: a judgment read with no judgment row")
            elif profile == R.CASE_PAGE and doc not in cased:
                out["failures"].append(f"{key[-40:]}: a case page read with no case row")
    out["sheets with a fact read"] = len(sheets)
    # the profile check: pieces by the profile's reading rule (ruling 130)
    out["pieces"], out["pieces by profile"] = _pieces(conn, t, docs, out["failures"])
    # the MCP's own date and citation beside the document's reading (Arthur, 3 November 2026): ours wins where both exist
    out["mcp"], out["mcp disagreements"] = mcp_agreement(conn, t)
    # a document is its bytes: a file under several records is read once, each record's row carrying the reading
    out["records sharing a file"] = q(f"SELECT count(*) - count(DISTINCT document) FROM {t('documents')} WHERE document IS NOT NULL")[0][0]
    for sha, n in q(f"SELECT document, count(*) FROM {t('cases')} GROUP BY 1 HAVING count(*) > 1") + \
            q(f"SELECT document, count(*) FROM {t('judgments')} GROUP BY 1 HAVING count(*) > 1"):
        out["failures"].append(f"{sha[:12]}…: a file read {n} times")
    aside = q(f"SELECT stage, count(*) FROM {t('set_aside')} GROUP BY 1 ORDER BY 1")
    out["set aside"] = dict(aside)
    out["status"] = dict(q(f"SELECT status, count(*) FROM {t('judgments')} GROUP BY 1 ORDER BY 1"))
    out["courts"] = dict(q(f"SELECT coalesce(court, '?'), count(*) FROM {t('judgments')} GROUP BY 1 ORDER BY 2 DESC"))
    out["missing"] = dict(q(f"SELECT m, count(*) FROM {t('judgments')}, unnest(missing) m GROUP BY 1 ORDER BY 1"))
    for col in ("registry", "judges", "heading", "hearing"):
        out["missing"][f"{col} (not printed or not read)"] = q(f"SELECT count(*) FROM {t('judgments')} WHERE {col} IS NULL")[0][0]
    out["missing"]["outcome (none in the orders)"] = q(f"SELECT count(*) FROM {t('judgments')} WHERE outcome = '{{}}'")[0][0]
    out["parties"] = dict(zip(("parties", "withheld", "anonymised", "crown", "low"), q(
        f"SELECT count(*), count(*) FILTER (WHERE withheld), count(*) FILTER (WHERE anonymised), "
        f"count(*) FILTER (WHERE crown), count(*) FILTER (WHERE confidence = 'low') FROM {t('judgment_parties')}")[0]))
    out["people"] = dict(zip(("names", "withheld", "persons", "bodies", "documents"), q(
        f"SELECT count(*), count(*) FILTER (WHERE withheld), count(*) FILTER (WHERE kind = 'person'), "
        f"count(*) FILTER (WHERE kind = 'body'), count(DISTINCT document) FROM {t('people')}")[0]))
    out["people"].update(dict(q(f"SELECT role, count(*) FROM {t('people')} GROUP BY 1 ORDER BY 2 DESC")))
    out["cases"] = dict(zip(("cases", "with a citation", "with a judgment date", "with a hearing date", "links", "links to a held document"), q(
        f"SELECT count(*), count(citation), count(date_of_judgment), count(date_of_hearing), "
        f"(SELECT count(*) FROM {t('case_links')}), (SELECT count(linked_document) FROM {t('case_links')}) FROM {t('cases')}")[0]))
    out["suppression"] = {"judgments flagged": q(f"SELECT count(*) FROM {t('judgments')} WHERE suppression")[0][0],
                          "names withheld": out["parties"]["withheld"], "model-read names withheld": out["people"]["withheld"],
                          "cases withheld": q(f"SELECT count(*) FROM {t('cases')} WHERE suppression")[0][0],
                          **dict(q(f"SELECT k, count(*) FROM {t('judgments')}, unnest(suppression_kinds) k GROUP BY 1 ORDER BY 1"))}
    leaked = q(f"SELECT p.key FROM {t('judgment_parties')} p JOIN {t('judgments')} j ON j.key = p.judgment "
               "WHERE j.suppression AND p.name IS NOT NULL AND NOT p.crown AND NOT p.anonymised")
    for (k,) in leaked:
        out["failures"].append(f"{k[:12]}…{k[64:]}: a name published in a judgment under suppression")
    # a model-read name on a document a suppression reaches: the judgment's own, or a document of its citation or case;
    # the keep rule is the load's own (model_read.kept_sql), one rule for both
    kept = model_read.kept_sql("n.")
    reach = q(f"""
        WITH s AS (SELECT document, citation, case_slug FROM {t('judgments')} WHERE suppression)
        SELECT n.key FROM {t('people')} n
         WHERE n.name IS NOT NULL AND NOT {kept}
           AND (n.document IN (SELECT document FROM s)
                OR (n.citation IS NOT NULL AND n.citation IN (SELECT citation FROM s WHERE citation IS NOT NULL))
                OR (n.case_slug IS NOT NULL AND n.case_slug IN (SELECT case_slug FROM s WHERE case_slug IS NOT NULL)))""")
    for (k,) in reach:
        out["failures"].append(f"{k[:12]}…{k[64:]}: a model-read name published on a document a suppression reaches")
    shown = q(f"SELECT count(*) FROM {t('judgment_parties')} WHERE withheld AND (name IS NOT NULL OR capacity IS NOT NULL)")[0][0]
    shown += q(f"SELECT count(*) FROM {t('people')} WHERE withheld AND name IS NOT NULL")[0][0]
    shown += q(f"SELECT count(*) FROM {t('cases')} WHERE withheld IS NOT NULL AND case_name IS NOT NULL")[0][0]
    if shown:
        out["failures"].append(f"{shown} withheld names still in a published table")
    out["suppression"]["names kept privately"] = _kept_privately(conn, schema, shared, t, out["failures"])
    orders = q(f"SELECT count(*) FROM {t('suppression_orders')}")[0][0] if _exists(conn, t("suppression_orders")) else 0
    out["suppression"]["orders in the ledger"] = orders
    out["identifiers"] = _identifiers(conn, schema, shared, out["failures"])
    # the lane and its profiles aligned (support/profiles/align.py), every `lands` column in this database, and every
    # document read recorded in docs.extractions at its profile's current fields
    out["alignment"] = _alignment(conn, schema, shared, out["failures"])
    out["extractions behind"] = _extractions(conn, t, out["failures"], shared)
    short, excepted = roles_review(conn, schema, shared)
    out["roles short"] = len(short)
    # the source's own printing (caption.roles_source_exception): each judgment counted with its reason, never tolerated
    out["roles the source's own"] = {k[:12]: reason for k, reason in excepted}
    if len(short) > ROLES_TOLERATED:
        out["failures"].append(f"{len(short)} judgments whose counsel lines name a role no party holds (tolerated {ROLES_TOLERATED})")
    return out


def _kept_privately(conn, schema: str, shared: bool, t, failures: list):
    """Ruling 142 (4 November 2026): a suppression is a flag, never a loss. Every row flagged (a party, a model-read
    name, a case) whose name left the row has it kept whole in the private table, with the source's words, keyed by
    the row; a row flagged with no name kept fails. Counts only; a login that cannot read the private schema is told so."""
    priv = L.private_of(schema)
    W = L.table(priv, "withheld_names", shared)
    if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (priv,)).fetchone() or not _exists(conn, W):
        return None
    if not conn.execute("SELECT has_schema_privilege(%s, 'USAGE')", (priv,)).fetchone()[0]:
        return "not readable by this login"
    lost = 0
    # a case page may print no case name at all, so only the parties and the model-read names are held to it
    for tname in ("judgment_parties", "people"):
        lost += conn.execute(f"SELECT count(*) FROM {t(tname)} r WHERE withheld AND r.name IS NULL AND NOT EXISTS "
                             f"(SELECT 1 FROM {W} w WHERE w.key = r.key AND w.held_in = %s AND w.name <> '' "
                             f"AND w.suppressed AND w.suppression_words <> '')", (tname,)).fetchone()[0]
    if lost:
        failures.append(f"{lost} row(s) flagged under a suppression whose name is not kept in {priv}.withheld_names")
    return conn.execute(f"SELECT count(*) FROM {W}").fetchone()[0]


#: ruling 1 (Arthur, 3 November 2026): the one view that reads the private table, for the links lane, by its exact text:
#: the document, kind, value and page of a company's NZBN or company number, nothing else
NUMBERS_VIEW = "court_company_numbers"
NUMBERS_KINDS = ("nzbn", "company_number")
NUMBERS_COLUMNS = ("document", "kind", "value", "page")
NUMBERS_VIEW_SQL = (f"CREATE OR REPLACE VIEW pub.{NUMBERS_VIEW} AS\n"
                    f"SELECT {', '.join(NUMBERS_COLUMNS)} FROM {L.PRIVATE}.identifiers WHERE kind IN "
                    f"({', '.join(repr(k) for k in NUMBERS_KINDS)});")


def publish_sql_names_private(text: str) -> bool:
    """publish.sql, its comments apart and the ruled numbers view (`NUMBERS_VIEW_SQL`, byte for byte) apart, names the
    private schema or the identifiers table."""
    body = "\n".join(ln.split("--", 1)[0].rstrip() for ln in text.splitlines())
    body = body.replace(NUMBERS_VIEW_SQL, "", 1)
    return bool(re.search(r"_private|\bidentifiers\b|withheld_names", body))


def numbers_view_problems(conn) -> list:
    """The ruled numbers view as the database holds it: its columns exactly `NUMBERS_COLUMNS`, the private table its only
    source, and no row of a kind but `NUMBERS_KINDS`. Absent (not yet published) is no problem."""
    cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'pub' AND "
                                       "table_name = %s ORDER BY ordinal_position", (NUMBERS_VIEW,)).fetchall()]
    if not cols:
        return []
    out = []
    if tuple(cols) != NUMBERS_COLUMNS:
        out.append(f"pub.{NUMBERS_VIEW} carries {cols}, not {list(NUMBERS_COLUMNS)}")
    other = conn.execute(f"SELECT count(*) FROM pub.{NUMBERS_VIEW} WHERE kind <> ALL(%s)", (list(NUMBERS_KINDS),)).fetchone()[0]
    if other:
        out.append(f"pub.{NUMBERS_VIEW} has {other} rows of a kind outside {list(NUMBERS_KINDS)}")
    return out


def _identifiers(conn, schema: str, shared: bool, failures: list) -> dict:
    """The private details counted by kind (never a value); the walls around them checked."""
    reading = [L.table(schema, n, shared).split(".", 1)[1] for n in L.TABLES]
    cols = conn.execute("SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE "
                        "(table_schema = 'pub' AND table_name LIKE 'court%%') OR (table_schema = %s AND table_name = ANY(%s))",
                        (schema, reading)).fetchall()
    for s, tname, col in cols:
        if col.lower() in FORBIDDEN_COLUMNS:
            failures.append(f"{s}.{tname} has a column {col!r}: an identifying detail in a published or reading table")
    for view, src in conn.execute("SELECT DISTINCT view_name, table_schema FROM information_schema.view_table_usage WHERE "
                                  "view_schema = 'pub' AND view_name LIKE 'court%%' AND right(table_schema, 8) = '_private'").fetchall():
        if view != NUMBERS_VIEW:
            failures.append(f"pub.{view} reads the private schema {src}")
    failures.extend(numbers_view_problems(conn))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish.sql"), encoding="utf-8") as f:
        if publish_sql_names_private(f.read()):
            failures.append("publish.sql names the private schema or one of its tables")
    priv = L.private_of(schema)
    name = L.table(priv, "identifiers", shared)
    if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (priv,)).fetchone():
        return {}
    if not conn.execute("SELECT has_schema_privilege(%s, 'USAGE')", (priv,)).fetchone()[0]:
        return {"not readable by this login": 0}
    if not _exists(conn, name):
        return {}
    by = dict(conn.execute(f"SELECT kind, count(*) FROM {name} GROUP BY 1 ORDER BY 2 DESC").fetchall())
    by["documents"] = conn.execute(f"SELECT count(DISTINCT document) FROM {name}").fetchone()[0]
    stray = conn.execute(f"SELECT count(*) FROM {name} i WHERE NOT EXISTS (SELECT 1 FROM {L.table(schema, 'documents', shared)} d "
                         "WHERE d.document = i.document)").fetchone()[0]
    if stray:
        failures.append(f"{stray} identifying detail(s) of a document the reading does not hold")
    return by


def _alignment(conn, schema: str, shared: bool, failures: list) -> dict:
    """What the lane's code produces against each profile's extract list, and each `lands` column against the database."""
    from support.profiles import align
    from registers.courts import extracts
    code = extracts.problems()
    live = align.live_problems(conn, extracts.LANE, extracts.where(schema, shared))
    failures.extend(f"alignment: {p}" for p in code + live)
    return {"profiles": len(extracts.SLUGS), "lands columns": len(align.lands_of(extracts.LANE)),
            "problems": len(code), "columns missing": len(live)}


def _extractions(conn, t, failures: list, shared: bool = False) -> dict:
    """docs.extractions by profile: per field, the documents read that are still owed it (extraction.behind). A
    document read (or waiting on the text reader) lacking a row for a field it has had by the lane's rule
    (`extracts.expected`) fails: the load records them in its own transaction. Only a document the store registers
    (docs.documents) can carry a row: live, one it does not register fails; the sample's store registers only some of
    its files, so there they are counted, not failed."""
    from support.docstore import extraction
    from registers.courts import extracts
    rows = conn.execute(f"SELECT DISTINCT document, profile, outcome, read_from FROM {t('documents')} "
                        "WHERE document IS NOT NULL AND profile IS NOT NULL AND outcome IN ('read', %s)", (R.WAIT_TEXT,)).fetchall()
    held = extraction.held(conn, [r[0] for r in rows])
    unheld = len({r[0] for r in rows} - held)
    if unheld and not shared:
        failures.append(f"{unheld} documents read that the store does not register (docs.documents): no ledger row can be kept")
    by_profile, pixels = {}, []
    for sha, slug, outcome, how in rows:
        if sha not in held:
            continue
        by_profile.setdefault(slug, {}).setdefault(outcome, []).append(sha)
        if how in ("pixels", "mixed"):
            pixels.append(sha)
    if pixels:
        by_profile.setdefault(R.SCANNED, {})["read"] = pixels
    out = {"(read, not registered by the store)": {"documents": unheld}} if unheld else {}
    for slug, groups in sorted(by_profile.items()):
        for outcome, shas in sorted(groups.items()):
            behind = extraction.behind(conn, slug, shas)
            want = extracts.expected(slug, outcome) if slug != R.SCANNED else {extracts.PAGE_TEXT}
            owed = {f: n for f, n in behind.items() if n}
            if owed:
                out[f"{slug} ({outcome}, {len(shas)})"] = owed
            for f in sorted(want):
                if behind.get(f, len(shas)):
                    failures.append(f"{slug}: {behind.get(f, len(shas))} of {len(shas)} documents {outcome} have no "
                                    f"docs.extractions row for {f} at its current iteration")
    return out


#: the document keys a disagreement names, at most (keys only, never a name)
MCP_KEYS_SHOWN = 5


def mcp_agreement(conn, t) -> tuple:
    """The MCP record's `doc_date` and `citation` against the judgment's own reading, per record of a judgment read:
    ({count: n}, {"date"|"citation": [record keys]}). A date or citation the document gave none of and the MCP's
    stands in (basis `mcp doc_date`, `mcp citation`) is counted as filled, never as an agreement."""
    rows = conn.execute(
        f"SELECT d.key, d.mcp_doc_date, d.mcp_citation, j.judgment_date, j.date_basis, j.citation, j.citation_basis "
        f"FROM {t('documents')} d JOIN {t('judgments')} j ON j.document = d.document "
        f"WHERE d.mcp_doc_date IS NOT NULL OR d.mcp_citation IS NOT NULL ORDER BY d.key").fetchall()
    out = {k: 0 for k in ("records carrying doc_date", "date agrees", "date disagrees", "date filled from the MCP",
                          "records carrying citation", "citation agrees", "citation disagrees", "citation filled from the MCP")}
    out["records carrying doc_date"] = conn.execute(
        f"SELECT count(*) FROM {t('documents')} WHERE mcp_doc_date IS NOT NULL").fetchone()[0]
    out["records carrying citation"] = conn.execute(
        f"SELECT count(*) FROM {t('documents')} WHERE mcp_citation IS NOT NULL").fetchone()[0]
    keys = {"date": [], "citation": []}
    norm = lambda c: re.sub(r"\s+", "", c or "").upper()  # noqa: E731
    for key, mdate, mcite, jdate, dbasis, jcite, cbasis in rows:
        if mdate is not None and jdate is not None:
            if dbasis == R.MCP_DATE_BASIS:
                out["date filled from the MCP"] += 1
            elif jdate == mdate:
                out["date agrees"] += 1
            else:
                out["date disagrees"] += 1
                keys["date"].append(key)
        if mcite and jcite:
            if cbasis == R.MCP_CITATION_BASIS:
                out["citation filled from the MCP"] += 1
            elif norm(jcite) == norm(mcite):
                out["citation agrees"] += 1
            else:
                out["citation disagrees"] += 1
                keys["citation"].append(key)
    return out, {k: v[:MCP_KEYS_SHOWN] for k, v in keys.items()}


def mcp_line(out: dict) -> str:
    """The check's line for the MCP's date and citation: counts, then the disagreeing record keys."""
    return ("mcp: " + ", ".join(f"{a} {b}" for a, b in out["mcp"].items())
            + "".join(f"; {k} disagrees at {', '.join(v)}" for k, v in out["mcp disagreements"].items() if v))


def _pieces(conn, t, docs: list, failures: list) -> tuple:
    bands = {"1": 0, "2": 0, "3-5": 0, "6-10": 0, "over 10": 0}
    by_profile, total, over = {}, 0, 0
    rows = conn.execute(f"SELECT key, profile, pieces, text_chars FROM {t('documents')} WHERE outcome IN ('read', %s) AND document IS NOT NULL",
                        (R.WAIT_TEXT,)).fetchall()
    rules = {}
    for key, profile, pieces, chars in rows:
        if profile not in rules:
            try:
                rules[profile] = PC.rule_of(profile)
            except LookupError as exc:
                rules[profile] = None
                failures.append(str(exc))
        rule = rules[profile]
        if pieces is None or pieces < 1:
            failures.append(f"{key[-40:]}: read by the text reader with no piece plan by its profile's rule")
            continue
        if rule and rule["split"] == "whole" and (pieces != 1 or (chars or 0) > rule["budget_chars"]):
            failures.append(f"{key[-40:]}: a whole-rule document of {chars} characters in {pieces} piece(s), over the budget of {rule['budget_chars']}")
        band = "1" if pieces == 1 else "2" if pieces == 2 else "3-5" if pieces <= 5 else "6-10" if pieces <= 10 else "over 10"
        bands[band] += 1
        total += pieces
        over += pieces > 1
        by_profile[profile] = by_profile.get(profile, 0) + pieces
    bands["documents over the budget"] = over
    bands["total pieces"] = total
    bands["cannot split (set aside at read)"] = conn.execute(
        f"SELECT count(*) FROM {t('set_aside')} WHERE stage = 'read' AND reason LIKE 'the text reader cannot read it:%%'").fetchone()[0]
    return bands, dict(sorted(by_profile.items(), key=lambda kv: -kv[1]))


def _exists(conn, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]


def roles_short(conn, schema: str, shared: bool = False, limit: int = ROLES_SAMPLE) -> list:
    """Judgments whose counsel lines name a role no party holds and the
    source's own printing does not account for."""
    return roles_review(conn, schema, shared, limit)[0]


def roles_review(conn, schema: str, shared: bool = False, limit: int = ROLES_SAMPLE) -> tuple:
    """(short, excepted): judgments whose counsel lines name a role no party
    holds, re-read from the stored text-layer readings of a fixed sample (by
    md5 of the key; the counsel lines are never stored), split into the parse
    misses and the (key, reason) pairs that are the source's own printing
    (`caption.roles_source_exception`)."""
    from support import reader as rd
    from support.docread.read import TEXT_MODEL
    from registers.courts import caption
    store, out, excepted = rd.Store(), [], []
    rows = conn.execute(f"SELECT key, document, profile, profile_version, caption_shape FROM {L.table(schema, 'judgments', shared)} "
                        f"ORDER BY md5(key) LIMIT %s", (limit,)).fetchall()
    for key, doc, slug, version, shape in rows:
        try:
            texts = {p: store.get(rd.reading_key(doc, p, TEXT_MODEL, {"tool": "pdftotext -layout"}, slug, version)).text
                     for p in (1, 2)}
        except rd.MissingReading:
            continue
        j = caption.Judgment(counsel_roles=caption._counsel_roles(texts[1] + "\n" + texts[2]), caption_shape=shape)
        j.parties = [caption.Party(name="", role=r[0], position=0, block=0) for r in conn.execute(
            f"SELECT role FROM {L.table(schema, 'judgment_parties', shared)} WHERE judgment = %s", (key,))]
        short = caption.roles_unaccounted(j)
        if short:
            reason = caption.roles_source_exception(j, short)
            if reason:
                excepted.append((key, reason))
            else:
                out.append(key)
    return out, excepted


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    schema = argv[argv.index("--schema") + 1] if "--schema" in argv else L.SCHEMA
    database = argv[argv.index("--database") + 1] if "--database" in argv else "querynz_v4"
    shared = "--sample" in argv
    from support import db
    with db.connect(db.OWNER_KEY if shared or schema != L.SCHEMA else db.READ_KEY, database) as conn:
        conn.execute("SET statement_timeout = '120s'")
        out = account(conn, schema, shared)
    print(f"corpus {capture.CORPUS}: {out['records']} records" + (f" ({out['taken by the pull']} taken by the pull)" if "taken by the pull" in out else ""))
    for k in ("outcomes", "profiles", "pieces", "pieces by profile", "set aside", "status", "courts", "missing", "parties", "people", "cases", "suppression", "identifiers", "alignment"):
        print(f"{k}: " + ", ".join(f"{a} {b}" for a, b in out[k].items()))
    print(mcp_line(out))
    print(f"sheets with a fact read: {out['sheets with a fact read']}; records sharing a file: {out['records sharing a file']}; "
          f"roles short: {out['roles short']} (tolerated {ROLES_TOLERATED})")
    print("extractions behind (documents still owed a field, by profile): " +
          ("; ".join(f"{p}: " + ", ".join(f"{f} {n}" for f, n in owed.items()) for p, owed in out["extractions behind"].items()) or "none"))
    for k, reason in out["roles the source's own"].items():
        print(f"roles the source's own: {k}… {reason}")
    for f in out["failures"]:
        print("FAIL " + f)
    return 1 if out["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
