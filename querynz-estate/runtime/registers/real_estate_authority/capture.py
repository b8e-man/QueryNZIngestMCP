"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only (track E).

The Real Estate Authority publishes its Complaints Assessment Committee
decisions (and the Disciplinary Tribunal and appeal decisions it files
beside them) in a "Decisions database" that a contractor runs at
`decisions.dotnous.com/reaa/v2/`; the Authority says they "remain on the
public register for 3 years". The old estate never captured them. The
position on file is `docs/legal/positions/real-estate-authority-decisions.md`.

The database is plain server pages. A listing for one year,
`default.aspx?qd3=during&qd1=<year>&Go=Submit+Search…&pagesel=<n>`, shows
"Search Results (N)" and ten decisions a page, each a date, a deciding body
and a link `abstract.aspx?case=<n>`. An abstract page links the decision's
PDFs under `/reaa/pdfs/`. Every listing page, abstract and PDF is landed by
its sha256; the tables keep only the numbers, the dates, the body and the
hashes, never a name.

A run, in order:

  1. list: every year from 2010 not yet listed, oldest first, and always the
     current and the previous year (decisions are still being published
     into them);
  2. fetch: the listed cases not yet held, the Committee's oldest first
     (they leave after three years), then the rest: the abstract, then
     each PDF it links that is not already held, until the budget, the item
     cap or the end of off-peak.

Politeness (hard limit 7): one request at a time, at least `FLOOR_S`
between requests (and the gate's own floor, whichever is slower), off-peak
only unless `--anytime`, nothing fetched twice. A 403, 429 or a challenge
page (the gate's verdict) is a block (hard limit 6): logged, and the run
STOPS. A 500, 502, 503 or 504 with no challenge on the page is the server's
own error: one failed read set aside with its status, then the run rests
`REST_S` and goes on, and that case waits for the next night. Three failed
reads in a row (server errors or transport failures) stop it too. A run that
stops early after landing something exits green with a "stopped early" line
and its counts; red only when nothing landed. A gate refusal is never caught.

    python -m registers.real_estate_authority.capture [--budget-s N] [--max-items N] [--list-only] [--anytime]
"""
import argparse
import datetime as dt
import html
import re
import sys
import os
import time
import urllib.parse

import support.fetchgate as fg

SOURCE = SCHEMA = "real_estate_authority"
JOB = "qv4-real-estate-authority-capture"
HOST = "decisions.dotnous.com"
BASE = f"https://{HOST}/reaa/v2/"
LISTING = BASE + "default.aspx"
FIRST_YEAR = 2010             # the database's year filter starts here
#: the body whose decisions leave the database after three years: its cases are fetched first, oldest first
#: (2015 lists 292 decisions, 2023 only 84: the Committee's older decisions are gone, the Tribunal's stay)
AT_RISK_BODY = "Complaints Assessment Committee Hearing"
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
STOP_AFTER_FAILURES = 3
SERVER_ERRORS = (500, 502, 503, 504)   # the server's own error, unless the page is a challenge
REST_S = 60.0                         # the gap after a failed read, before the next request
DEFAULT_BUDGET_S = 16200
HERE = os.path.dirname(os.path.abspath(__file__))

_RESULTS = re.compile(r"Search Results \((\d+)\)")
_PAGES = re.compile(r"Page (\d+) of (\d+)")
_ROW = re.compile(r'<div class="pure-u-md-1-3">\s*<h4>([^<]+)</h4>.*?abstract\.aspx\?case=(\d+)" title="([^"]+)"', re.S)
_PDF = re.compile(r'href="(/reaa/pdfs/[^"]+\.pdf)"', re.I)
_COMPLAINT = re.compile(r"^(C?\d+)", re.I)


# ── pure pieces ───────────────────────────────────────────────────────────────

def listing_url(year: int, page: int = 1) -> str:
    params = [("qd3", "during"), ("qd1", str(year)), ("Go", "Submit Search"), ("opgsize", "10"), ("Cpgs", "0"),
              ("Cpge", "9")]
    if page > 1:
        params.append(("pagesel", str(page)))
    return LISTING + "?" + urllib.parse.urlencode(params)


def abstract_url(case_id: int) -> str:
    return f"{BASE}abstract.aspx?case={int(case_id)}"


def parse_listing(page: bytes):
    """(num_found, pages, [(case_id, decision_date, body)]) from a listing page."""
    t = page.decode("utf-8", "replace")
    m = _RESULTS.search(t)
    if not m:
        raise ValueError("no 'Search Results (N)' on the page")
    p = _PAGES.search(t)
    rows, seen = [], set()
    for date_s, case, title in _ROW.findall(t):
        case = int(case)
        if case in seen:
            continue
        seen.add(case)
        try:
            when = dt.datetime.strptime(html.unescape(date_s).strip(), "%d %b %Y").date()
        except ValueError:
            when = None
        rows.append((case, when, re.sub(r"\s+Details$", "", html.unescape(title)).strip()))
    return int(m.group(1)), (int(p.group(2)) if p else 1), rows


def pdf_links(page: bytes) -> list:
    """The decision PDFs an abstract links, as absolute URLs, in page order."""
    out = []
    for href in _PDF.findall(page.decode("utf-8", "replace")):
        url = f"https://{HOST}" + urllib.parse.quote(html.unescape(href), safe="/%")
        if url not in out:
            out.append(url)
    return out


def complaint_number(url: str):
    m = _COMPLAINT.match(urllib.parse.unquote(url.rsplit("/", 1)[1]))
    return m.group(1).upper() if m else None


def off_peak(now_local: dt.datetime) -> bool:
    start, end = OFF_PEAK
    return now_local.hour >= start or now_local.hour < end


def complete_years(rows) -> set:
    """The years whose every listing page has been read, from (year, page,
    pages) rows. A year cut short (a page that failed) is not listed: the
    next run lists it again from page one."""
    seen, pages = {}, {}
    for year, page, n in rows:
        seen.setdefault(year, set()).add(page)
        pages[year] = max(pages.get(year, 0), n)
    return {y for y in seen if len(seen[y]) >= pages[y]}


def years_to_list(today: dt.date, listed: set) -> list:
    years = list(range(FIRST_YEAR, today.year + 1))
    return [y for y in years[:-2] if y not in listed] + years[-2:]


# ── the lane's tables ─────────────────────────────────────────────────────────

#: the line in tables.sql that begins the reading's tables: the capture makes only the tables above it
READING = "-- ── the reading"


def tables_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        return f.read().split(READING)[0].replace(f"{SCHEMA}.", f"{schema}.")


def reading_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        return (READING + f.read().split(READING, 1)[1]).replace(f"{SCHEMA}_private.", f"{schema}_private.").replace(
            f"{SCHEMA}.", f"{schema}.")


class Tables:
    """The lane's tables over a psycopg connection in autocommit mode."""

    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema

    def create(self):
        self.conn.execute(tables_sql(self.s))

    def try_lock(self) -> bool:
        """One run of the lane at a time, whoever started it (the scheduler or a
        hand run): a session advisory lock, which holds no row and no snapshot
        and is let go with the connection."""
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def listed_years(self) -> set:
        return complete_years(self.conn.execute(f"SELECT year, page, pages FROM {self.s}.listings"))

    def add_listing(self, year, page, num_found, pages, sha, url):
        self.conn.execute(f"INSERT INTO {self.s}.listings (year, page, num_found, pages, listing, url) "
                          "VALUES (%s, %s, %s, %s, %s, %s)", (year, page, num_found, pages, sha, url))

    def upsert_cases(self, year, rows, sha):
        for case_id, when, body in rows:
            self.conn.execute(f"INSERT INTO {self.s}.cases (case_id, year, decision_date, body, listing) "
                              "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (case_id) DO NOTHING",
                              (case_id, year, when, body, sha))

    def pending(self, limit: int) -> list:
        cur = self.conn.execute(
            f"SELECT case_id FROM {self.s}.cases WHERE captured_at IS NULL AND case_id::text NOT IN "
            f"(SELECT item FROM {self.s}.set_aside WHERE stage = 'abstract') "
            "ORDER BY (body <> %s), decision_date NULLS LAST, case_id LIMIT %s", (AT_RISK_BODY, limit))
        return [r[0] for r in cur]

    def held_urls(self, case_id) -> set:
        return {r[0] for r in self.conn.execute(f"SELECT source_url FROM {self.s}.documents WHERE case_id = %s", (case_id,))}

    def add_document(self, case_id, url, number, sha):
        self.conn.execute(f"INSERT INTO {self.s}.documents (case_id, source_url, complaint_number, document) "
                          "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (case_id, url, number, sha))

    def captured(self, case_id, abstract_sha):
        self.conn.execute(f"UPDATE {self.s}.cases SET abstract = %s, captured_at = now() WHERE case_id = %s",
                          (abstract_sha, case_id))

    def set_aside(self, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.s}.set_aside (item, stage, reason) VALUES (%s, %s, %s)",
                          (str(item), stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Stop(RuntimeError):
    """The run stops here: a block, a challenge, or the host not answering."""


class Run:
    def __init__(self, tables, *, land_fn, opener=None, pacer=None, gate_pacer=None, clock=None, now_local=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_items: int = 100000, anytime: bool = False, log=print):
        self.t, self.land_fn, self.opener = tables, land_fn, opener or fg.open_url
        self.pacer = pacer or fg.Pacer()
        self.gate_pacer = gate_pacer
        self.clock = clock or time.monotonic
        self.now_local = now_local or (lambda: dt.datetime.now().astimezone())
        self.budget_s, self.max_items, self.anytime, self.log = budget_s, max_items, anytime, log
        self.started = self.clock()
        self.failures = 0
        self.tried = set()
        self.counts = {"requests": 0, "listings": 0, "listed": 0, "cases": 0, "landed": 0, "already_held": 0,
                       "set_aside": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now_local()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def aside(self, item, stage, reason):
        self.t.set_aside(item, stage, reason)
        self.counts["set_aside"] += 1

    def get(self, url: str):
        """One gated, paced request: the Fetched, or None after a failed read
        (a transport failure, or a server error with no challenge on the page),
        set aside with its reason, the next request resting `REST_S`. Raises
        Stop on a block, a challenge or three failed reads in a row; a gate
        refusal is never caught."""
        self.pacer.wait(HOST, REST_S if self.failures else FLOOR_S)
        self.counts["requests"] += 1
        try:
            kw = {"pacer": self.gate_pacer} if self.gate_pacer is not None else {}
            f = self.opener(url, timeout=60, **kw)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001
            return self.failed(url, f"transport: {type(exc).__name__}: {str(exc)[:200]}")
        if f.status in SERVER_ERRORS and not fg.looks_challenged(200, f.body):
            return self.failed(url, f"HTTP {f.status}: the server's own error; set aside, the run rests and goes on")
        self.failures = 0
        if f.blocked:
            self.aside(url, "fetch", f.blocked)
            raise Stop(f.blocked)
        elsewhere = fg.host_of(f.location) if f.status in fg.REDIRECT_STATUSES and f.location else HOST
        if elsewhere != HOST:
            # the gate judged the URL asked and hands back a redirect off it unfetched, in f.location
            why = f"redirected to {elsewhere}: not landed, and the run stops"
            self.aside(url, "fetch", why)
            raise Stop(why)
        return f

    def failed(self, url, why):
        self.failures += 1
        self.aside(url, "fetch", why)
        if self.failures >= STOP_AFTER_FAILURES:
            raise Stop(f"{self.failures} failed reads in a row; the host may be in trouble")
        return None

    def land(self, f, kind):
        return self.land_fn(f.body, name=f.url, source=SOURCE, name_kind="url",
                            content_type="application/pdf" if kind == "pdf" else "text/html")

    def list_year(self, year: int):
        page, pages = 1, 1
        while page <= pages:
            if not self.time_left():
                return
            url = listing_url(year, page)
            f = self.get(url)
            if f is None or f.status != 200:
                self.aside(f"{year}/{page}", "listing", "a failed read" if f is None else f"HTTP {f.status}")
                return
            try:
                num_found, pages, rows = parse_listing(f.body)
            except ValueError as exc:
                self.aside(f"{year}/{page}", "listing", str(exc))
                return
            ref, _ = self.land(f, "page")
            self.counts["listings"] += 1
            self.t.upsert_cases(year, rows, ref.sha256)
            self.t.add_listing(year, page, num_found, pages, ref.sha256, url)
            self.counts["listed"] += len(rows)
            if not rows:
                break
            page += 1
        self.log(f"{SOURCE}: {year} listed ({pages} pages)")

    def capture_case(self, case_id: int):
        f = self.get(abstract_url(case_id))
        if f is None:
            return
        if f.status != 200:
            self.aside(case_id, "abstract", f"HTTP {f.status}")
            return
        if not pdf_links(f.body) and b"DECISION" not in f.body:
            self.aside(case_id, "abstract", "no decision on the page")
            return
        ref, _ = self.land(f, "page")
        held = self.t.held_urls(case_id)
        complete = True
        for url in pdf_links(f.body):
            if url in held:
                continue
            if not self.time_left():
                return
            p = self.get(url)
            if p is None:
                complete = False
                continue
            if p.status != 200 or not p.body.startswith(b"%PDF"):
                self.aside(url, "pdf", f"HTTP {p.status}" + ("" if p.status != 200 else ", not a PDF"))
                continue
            pref, new = self.land(p, "pdf")
            self.t.add_document(case_id, url, complaint_number(url), pref.sha256)
            self.counts["landed" if new else "already_held"] += 1
        if complete:
            self.t.captured(case_id, ref.sha256)
            self.counts["cases"] += 1

    def fetch_pending(self):
        done = 0
        while done < self.max_items and self.time_left():
            # a case tried this run and not held (a failed read) waits for the next night: nothing asked twice
            batch = [c for c in self.t.pending(min(100, self.max_items - done) + len(self.tried)) if c not in self.tried]
            if not batch:
                break
            for case_id in batch:
                if done >= self.max_items or not self.time_left():
                    return
                self.tried.add(case_id)
                self.capture_case(case_id)
                done += 1

    def run(self, today: dt.date, list_only: bool = False) -> dict:
        try:
            for y in years_to_list(today, self.t.listed_years()):
                if not self.time_left():
                    break
                self.list_year(y)
            if not list_only:
                self.fetch_pending()
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def outcome(out: dict):
    """(ok, the last words of the run's line). A run that stopped early (a
    block, a challenge, a host in trouble) after landing something is green
    with a "stopped early" line: a polite stop is not a failure. Red only
    when it stopped with nothing landed."""
    stopped = out["stopped"]
    if not stopped.startswith("stopped:"):
        return True, stopped or "done"
    if out["listings"] or out["cases"] or out["landed"]:
        return True, "stopped early: " + stopped[len("stopped:"):].strip()
    return False, stopped + "; nothing landed"


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.real_estate_authority.capture")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--max-items", type=int, default=100000)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--anytime", action="store_true", help="run outside off-peak (by hand, on purpose)")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db, jobrun
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            jobrun.record(JOB, True, "skipped: another run holds the lane", started, {})
            return 0
        out = Run(t, land_fn=landing(conn), budget_s=a.budget_s, max_items=a.max_items,
                  anytime=a.anytime).run(dt.date.today(), list_only=a.list_only)
    ok, last = outcome(out)
    detail = (f"{out['listings']} listing pages, {out['listed']} cases listed, {out['cases']} cases held, "
              f"{out['landed']} PDFs landed, {out['set_aside']} set aside; {last}")
    print(f"{SOURCE}: {detail}")
    jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
