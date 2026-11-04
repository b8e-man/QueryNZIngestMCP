"""The lane's figures against the outside world (contract: the lane).

Neither publisher states a count of its grants beside them, so the outside
figures are the documents' own: exit 1 on any of

  1. nothing read: no national file, or no record of grants
  2. the national file's records counted afresh from its bytes (lines that
     open a record, by a reader that is not the lane's) differ from the
     records read; every record is a grant or a catch-log line
  3. a society on the Department's own list (granted.govt.nz, 21 October
     2026: 31 societies) has no grant in the Department's own file
  4. a record of grants that prints a total whose rows do not sum to it
  5. the reading does not reconcile (a grant with no ledger line, a recipient
     whose grants do not count up, a grantor with no publisher row), or a
     view carries an address column, a text value shaped like a street
     address (reported by key, never by value), or a row with no licence or
     attribution
  6. the national file's newest decision is more than 15 months old (the
     Department updates it once a year)

Every line printed is a count.

    python -m registers.grants.check [--database querynz_v4]
"""
import argparse
import datetime as dt
import json
import re
import os
import sys
import urllib.parse

from registers.grants import capture, read

SCHEMA = "grants"
ADDRESSISH = ("address", "street", "postal", "residential", "home", "email", "phone", "suburb", "postcode")
VIEWS = ("grants", "grant_recipients", "grant_publishers")
STALE_MONTHS = 15
_NUM = r"\d{1,4}[A-Za-z]?(?:\s*[-/]\s*\d{1,4}[A-Za-z]?)?"
_STREET = (r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Crescent|Cres|Terrace|Tce|Lane|Way|Parade|Highway|Hwy|"
           r"Grove|Close|Court|Ct|Rise|Quay|Square|Boulevard|Esplanade|Mews|Heights|Glade|Row|Promenade|Strand|Mall)")
_NOT_A_HOUSE = "".join(f"(?<!{re.escape(w)} )" for w in ("Highway", "Hwy", "SH", "No", "No.", "Act", "Section", "s"))
STREET = re.compile(rf"(?<![\w/.-]){_NOT_A_HOUSE}{_NUM},?\s+(?:[A-Z][\w'’.-]*\s+){{1,4}}{_STREET}\b"
                    rf"(?!\s+(?:Limited|Ltd|Incorporated|Inc|Trust|Club|School|Kindergarten|Church|Hall)\b)")


def records_in_bytes(data: bytes) -> int:
    """The CSV's records, counted without the lane's reader: newlines outside quotes, less the header."""
    n, quoted = 0, False
    for b in data:
        if b == 0x22:
            quoted = not quoted
        elif b == 0x0A and not quoted:
            n += 1
    if data and not data.endswith(b"\n"):
        n += 1
    return n - 1


def total_of(stated: str):
    m = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", stated or "")
    return float(m.group(1).replace(",", "")) if m else None


def reading(conn, schema: str = SCHEMA) -> list:
    T = lambda t: capture.table(schema, t)
    out = []
    one = lambda q: conn.execute(q).fetchone()[0]
    said = one(f"SELECT coalesce(sum(grants), 0) FROM {T('read_documents')}")
    rows = one(f"SELECT count(*) FROM {T('grants')}")
    if said != rows:
        out.append(f"{rows} grant rows against {said} in the ledger")
    n = one(f"SELECT count(*) FROM {T('read_documents')} WHERE records <> grants + set_aside")
    if n:
        out.append(f"{n} documents whose records are not grants plus set aside")
    n = one(f"SELECT count(*) FROM {T('grants')} g WHERE NOT EXISTS (SELECT 1 FROM {T('read_documents')} d "
            "WHERE d.document = g.document)")
    if n:
        out.append(f"{n} grants with no ledger line")
    n = one(f"SELECT coalesce(sum(grants), 0) FROM {T('recipients')}")
    if n != rows:
        out.append(f"recipients count {n} grants against {rows} grant rows")
    n = one(f"SELECT count(*) FROM {T('grants')} g WHERE NOT EXISTS (SELECT 1 FROM {T('recipients')} r "
            "WHERE r.key = g.recipient_key)")
    if n:
        out.append(f"{n} grants with no recipient row")
    n = one(f"SELECT count(*) FROM {T('grants')} g WHERE NOT EXISTS (SELECT 1 FROM {T('publishers')} p "
            "WHERE p.key = g.grantor_key) OR NOT EXISTS (SELECT 1 FROM {0} p WHERE p.key = g.publisher_key)"
            .format(T('publishers')))
    if n:
        out.append(f"{n} grants whose grantor or publisher has no publisher row")
    n = one(f"SELECT count(*) FROM {T('grants')} WHERE amount_nzd IS NOT NULL AND status <> 'Accepted'")
    if n:
        out.append(f"{n} grants not accepted carry an amount granted")
    n = one(f"SELECT count(*) FROM {T('grants')} WHERE period < '{read.WINDOW_FROM}'")
    if n:
        out.append(f"{n} grants before {read.WINDOW_FROM} (ruling 71)")
    return out


def views(conn, prefix: str = "pub.") -> list:
    out = []
    schema, _, stem = prefix.rstrip(".").partition(".")
    schema = schema or "pub"
    for v in VIEWS:
        name = (stem + v) if stem else v
        cols = list(conn.execute("SELECT column_name, data_type FROM information_schema.columns "
                                 "WHERE table_schema = %s AND table_name = %s", (schema, name)))
        if not cols:
            out.append(f"{v} is not there")
            continue
        extra = [c for c, _ in cols if any(w in c for w in ADDRESSISH)]
        if extra:
            out.append(f"{v} carries {', '.join(extra)}")
        if not {"licence", "attribution"} <= {c for c, _ in cols}:
            out.append(f"{v} carries no licence or attribution")
        else:
            n = conn.execute(f"SELECT count(*) FROM {schema}.{name} WHERE coalesce(licence, '') = '' OR coalesce(attribution, '') = ''"
                             ).fetchone()[0]
            if n:
                out.append(f"{v}: {n} rows with no licence or attribution")
        for c, typ in cols:
            if typ != "text" or c in ("key", "document", "reader", "profile", "place", "website", "attribution",
                                      "recipient_key", "role"):
                continue
            keys = [r[0] for r in conn.execute(f"SELECT key, {c} FROM {schema}.{name} WHERE {c} ~ '[0-9]'")
                    if r[1] and STREET.search(r[1])]
            if keys:
                out.append(f"{v}.{c}: {len(keys)} values shaped like a street address (first key {keys[0]})")
    return out


def outside(conn, schema: str = SCHEMA, read_bytes=None, today: dt.date = None) -> dict:
    from support.docstore.landing import read_bytes as rb
    read_bytes = read_bytes or rb
    T = lambda t: capture.table(schema, t)
    problems = []
    docs = conn.execute(f"SELECT document, list, url, profile, records, grants, set_aside, stated "
                        f"FROM {T('read_documents')}").fetchall()
    files = [d for d in docs if d[3] == read.DIA_CSV]
    pages = [d for d in docs if d[3] == read.LOTTERY_PAGE]
    unread = [d for d in docs if d[3] is None and d[1] != "society-file"]
    if not files:
        problems.append("no national file of class 4 grants read")
    if not pages:
        problems.append("no Lottery record of grants read")
    if unread:
        problems.append(f"{len(unread)} listed documents no profile recognises")
    for d in files:
        n = records_in_bytes(read_bytes(d[0]))
        if n != d[4]:
            problems.append(f"the national file {d[0][:12]}…: {n} records in its bytes, {d[4]} read")
    for d in pages:
        stated = d[7] if isinstance(d[7], dict) else json.loads(d[7] or "{}")
        if stated.get("total"):
            want = total_of(stated["total"])
            got = conn.execute(f"SELECT coalesce(sum(amount_nzd), 0) FROM {T('grants')} WHERE document = %s",
                               (d[0],)).fetchone()[0]
            if want is None or abs(float(got) - want) > 0.5:
                problems.append(f"the record {d[0][:12]}… prints a total of {stated['total']}; its rows sum to {got}")
    listed = [k for k, (_, _, on) in read.SOCIETIES.items() if on]
    with_grants = {r[0] for r in conn.execute(f"SELECT DISTINCT grantor_key FROM {T('grants')} "
                                              "WHERE publisher_key = 'dia' AND grantor_key <> 'lottery-grants-board'")}
    missing = sorted(set(listed) - with_grants) if files else []
    if missing:
        problems.append(f"{len(missing)} societies on the Department's list have no grant in its file: "
                        + ", ".join(missing))
    society_problems, society_figures = societies(conn, schema, docs, bool(files))
    problems += society_problems
    newest = conn.execute(f"SELECT max(decided_on) FROM {T('grants')} WHERE profile = %s", (read.DIA_CSV,)).fetchone()[0]
    today = today or dt.date.today()
    if newest and (today.year - newest.year) * 12 + today.month - newest.month > STALE_MONTHS:
        problems.append(f"the national file's newest decision is {newest}: stale")
    per_year = dict(conn.execute(f"SELECT period, count(*) FROM {T('grants')} WHERE profile = %s GROUP BY period "
                                 "ORDER BY period", (read.DIA_CSV,)).fetchall())
    return {"ok": not problems, "problems": problems, "files": len(files), "records_of_grants": len(pages),
            "file_records": sum(d[4] for d in files), "grants_by_year": per_year, "newest_decision": newest,
            "societies_listed": len(listed), "societies_with_grants": len(with_grants),
            "society_lists": society_figures}


#: an address that names a society's file as something other than a list of grants decided: a refund list, a form,
#: a policy, a guide, a report. Any other file with a text layer is taken to be a list (absence of a name is no proof)
NOT_A_LIST = re.compile(r"(?i)refund|returned|form\b|forms?[-_ .]|polic|guide|declaration|accountability|criteria|"
                        r"salary|writer|exclusion|privacy|annual[-_ ]?report|financial[-_ ]?statement|audit|consent")
#: society files known to be lists in a layout no profile reads yet, by hash: `unprofiled.list`, carded
UNPROFILED_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unprofiled.list")


def unprofiled() -> dict:
    with open(UNPROFILED_LIST, encoding="utf-8") as f:
        return {ln.split()[0]: ln.split(None, 2)[1:] for ln in f if ln.strip() and not ln.startswith("#")}


#: a society whose own lists differ from the national file for a reason known and carded: reported, not red
KNOWN_DIFFERENCES = {
    "we-care-community-trust": "its 2022 lists print 52 grants, $1,387,532; the national file 55, $1,669,449: three "
                               "grants the society's quarterly lists do not carry (card the-societies-own-grants-lists)",
}
TOLERANCE = 0.005      # a society's own lists against the national file, over the years both cover whole


def _covered_years(periods: list) -> set:
    """Calendar years every day of which the lists inside that year ('yyyy-mm-dd/yyyy-mm-dd', one year) cover: a list
    over two years (New Horizon's June to May) cannot be counted to either."""
    spans = sorted((dt.date.fromisoformat(p[:10]), dt.date.fromisoformat(p[11:21])) for p in periods
                   if "/" in p and p[:4] == p[11:15])
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + dt.timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    years = set()
    for a, b in merged:
        for y in range(a.year, b.year + 1):
            if a <= dt.date(y, 1, 1) and dt.date(y, 12, 31) <= b:
                years.add(y)
    return years


def societies(conn, schema, docs, national: bool) -> tuple:
    """The societies' own lists: (problems, figures). Red on: a list in a layout no profile reads and no card names;
    a list whose printed total its rows do not sum to; a society whose lists, over the years they cover whole and the
    national file holds, differ from the national file by more than half a per cent in applications decided or in
    the money granted."""
    T = lambda t: capture.table(schema, t)
    problems, figures = [], {"files": 0, "read": 0, "scans": 0, "not_lists": 0, "carded": 0, "compared": {}}
    carded = unprofiled()
    for d in (d for d in docs if d[1] == "society-file"):
        figures["files"] += 1
        stated = d[7] if isinstance(d[7], dict) else json.loads(d[7] or "{}")
        if d[3] is not None:
            figures["read"] += 1
            for col in ("requested", "granted"):
                if stated.get(f"total_{col}") is not None:
                    want = total_of(stated[f"total_{col}"])
                    got = stated.get(f"rows_{col}")
                    if want is None or got is None or abs(float(got) - want) > 0.5:
                        problems.append(f"the society list {d[0][:12]}… prints a {col} total of "
                                        f"{stated[f'total_{col}']}; its rows sum to {got}")
        elif stated.get("text_words", 0) < read.SCAN_WORDS:
            figures["scans"] += 1
        elif NOT_A_LIST.search(urllib.parse.unquote(d[2] or "")):
            figures["not_lists"] += 1
        elif d[0][:16] in carded:
            figures["carded"] += 1
        else:
            problems.append(f"the society list {(d[2] or '')[-60:]} ({d[0][:12]}…) is in a layout no profile reads")
    if not national:
        return problems, figures
    rows = conn.execute(f"SELECT grantor_key, period, status, count(*), coalesce(sum(amount_nzd), 0) "
                        f"FROM {T('grants')} WHERE publisher_key = grantor_key GROUP BY 1, 2, 3").fetchall()
    by = {}
    for soc, period, status, n, money in rows:
        by.setdefault(soc, []).append((period, status, n, float(money)))
    for soc, got in sorted(by.items()):
        years = _covered_years([p for p, *_ in got])
        nat = conn.execute(f"SELECT period, count(*), coalesce(sum(amount_nzd), 0) FROM {T('grants')} "
                           "WHERE publisher_key = 'dia' AND grantor_key = %s AND status IN ('Accepted', 'Declined') "
                           "GROUP BY 1", (soc,)).fetchall()
        both = sorted(years & {int(p) for p, _, _ in nat})
        if not both:
            continue
        statuses = {st for p, st, *_ in got if "/" in p and int(p[:4]) in both} or {"Accepted", "Declined"}
        nat = conn.execute(f"SELECT period, count(*), coalesce(sum(amount_nzd), 0) FROM {T('grants')} "
                           "WHERE publisher_key = 'dia' AND grantor_key = %s AND status = ANY(%s) GROUP BY 1",
                           (soc, sorted(statuses))).fetchall()     # a list of approvals only: approvals only
        theirs = [sum(n for p, n, _ in nat if int(p) in both), sum(float(m) for p, _, m in nat if int(p) in both)]
        ours = [0, 0.0]
        for period, status, n, money in got:
            if "/" in period and int(period[:4]) in both and period[:4] == period[11:15] and status in statuses:
                ours[0] += n
                ours[1] += money
        figures["compared"][soc] = {"years": both, "statuses": sorted(statuses), "decided": ours[0],
                                    "national": theirs[0],
                                    "granted": round(ours[1]), "national_granted": round(theirs[1])}
        differs = abs(ours[0] - theirs[0]) > TOLERANCE * theirs[0] or abs(ours[1] - theirs[1]) > TOLERANCE * theirs[1]
        figures["compared"][soc]["agrees"] = not differs
        if differs and soc in KNOWN_DIFFERENCES:
            figures["compared"][soc]["known"] = KNOWN_DIFFERENCES[soc]
        elif differs:
            problems.append(f"{soc}: its own lists for {both[0]} to {both[-1]} read {ours[0]} applications decided "
                            f"and ${ours[1]:,.0f} granted; the national file {theirs[0]} and ${theirs[1]:,.0f}")
    return problems, figures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.grants.check")
    ap.add_argument("--database", default="querynz_v4")
    a = ap.parse_args(argv)
    from support import db
    with db.connect(db.READ_KEY, a.database) as conn:
        conn.execute("SET statement_timeout = '60s'")
        if conn.execute("SELECT to_regclass('grants.read_documents')").fetchone()[0] is None:
            print(f"{SCHEMA}: check: nothing published yet (no load has run)")
            return 1
        out = outside(conn)
        out["problems"] += reading(conn) + views(conn)
    print(f"{SCHEMA}: check: " + json.dumps(out, default=str))
    return 0 if not out["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
