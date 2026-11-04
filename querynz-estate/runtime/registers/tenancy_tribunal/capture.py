"""How this lane's documents arrive: case 3 of plan 1.10, captured once,
politely, through the fetch gate and the landing wrapper only (track E).

The Tenancy Tribunal's orders are published by the Ministry of Justice for
three years and then taken down (each listing row carries its own
`unpublishedDate`). The old estate never captured them. The position on file
is `docs/legal/positions/tenancy-tribunal-decisions.md`.

The search page at `forms.justice.govt.nz/search/TT/` is a script over a
listing service, `/forms/publicSolrProxy/solr/TTV2/select`, which answers
JSON. The lane asks it for one published month at a time, each row whole
(ruling 143 supersedes ruling 58's field list): the order rows read from it
(`FIELDS`) carry the numbers and the dates only, and each row whole, the
party names and the tenancy address among its fields, is kept in
`tenancy_tribunal_private.listing_rows`. A month listed with the field list
before 4 November 2026 is listed again, whole, once. Each order's PDF is then
fetched from `/search/Documents/TTV2/` and landed by its sha256.

A run, in order:

  1. list: every month of the three-year window not yet listed, oldest
     first, and always the current and the previous month (orders are still
     being published into them). Each listing response is itself landed (it
     is the citation for the rows), and its count is the source's own count
     for that month (check.py).
  2. fetch: the listed orders not yet held, the soonest to be taken down
     first, until the budget, the item cap or the end of off-peak.

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` between
requests to the host (and the gate's own floor, whichever is slower),
off-peak only unless `--anytime`, nothing fetched twice (an order already
held is never asked for again). A 403, 429, 5xx or a challenge page is a
failed read (hard limit 6): it is logged in the catch log and the run STOPS;
nothing is retried, solved or got around. Three transport failures in a row
stop the run too. A refusal from the gate is never caught. While the gate
holds the host (ruling 141) a run asks nothing at all and ends well, saying
so: only a person clears the hold, and the next run after that goes on.

    python -m registers.tenancy_tribunal.capture [--budget-s N] [--max-items N] [--list-only] [--anytime]
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.parse

import support.fetchgate as fg

SOURCE = SCHEMA = "tenancy_tribunal"
JOB = "qv4-tenancy-tribunal-capture"
HOST = "forms.justice.govt.nz"
LISTING = f"https://{HOST}/forms/publicSolrProxy/solr/TTV2/select"
DOCUMENTS = f"https://{HOST}/search/Documents/TTV2/"
#: the fields an order row is read from; the listing is asked for its rows whole
FIELDS = ("id", "applicationNumber_s", "publishedDate_dt", "unpublishedDate_s", "decisionDateIndex_l",
          "orderDetailJson_s", "tenancyMBIEOrder_txt")
ROWS = 1000                   # rows per listing request; a month is about 900
FLOOR_S = 5.0                 # the position's floor; the gate's, if slower, binds too
OFF_PEAK = (22, 6)            # NZ local hours: start at 22:00, stop at 06:00
WINDOW_MONTHS = 37            # three years and the month in hand
STOP_AFTER_FAILURES = 3
DEFAULT_BUDGET_S = 16200      # four and a half hours a night
HERE = os.path.dirname(os.path.abspath(__file__))


# ── pure pieces ───────────────────────────────────────────────────────────────

def first(v):
    return v[0] if isinstance(v, list) and v else (None if isinstance(v, list) else v)


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def next_month(m: dt.date) -> dt.date:
    return (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def window(today: dt.date, n: int = WINDOW_MONTHS) -> list:
    """The months of the window, oldest first, ending with today's."""
    out = [month_start(today)]
    while len(out) < n:
        out.insert(0, month_start(out[0] - dt.timedelta(days=1)))
    return out


def listing_url(month: dt.date, start: int = 0, rows: int = ROWS) -> str:
    q = f"publishedDate_dt:[{month.isoformat()}T00:00:00Z TO {next_month(month).isoformat()}T00:00:00Z}}"
    params = [("q", q), ("fq", "jurisdictionCode_s:TT"),
              ("sort", "publishedDate_dt asc,id asc"), ("start", str(start)), ("rows", str(rows)), ("wt", "json")]
    return LISTING + "?" + urllib.parse.urlencode(params)


def count_url(month: dt.date) -> str:
    return listing_url(month, 0, 0)


def decode(body: bytes) -> bytes:
    """The listing service answers gzip whether asked or not: the document is
    the JSON, the transfer encoding is not."""
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def parse_listing(body: bytes):
    """(numFound, docs) from a listing response's bytes."""
    j = json.loads(decode(body))
    r = j["response"]
    return int(r["numFound"]), list(r.get("docs") or [])


def _date(s):
    s = (s or "").strip()
    if not s:
        return None
    if s[:8].isdigit() and len(s) >= 8 and "-" not in s[:8]:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return dt.date.fromisoformat(s[:10])


def pdf_url(order: dict, mbie: bool) -> str:
    """As the search page's own script builds it (abstract.theme.tt.js)."""
    if mbie and order.get("publishedOrderPdfName"):
        return DOCUMENTS + "PDF/" + urllib.parse.quote(order["publishedOrderPdfName"])
    return DOCUMENTS + urllib.parse.quote(str(order["orderId"])) + ".pdf"


def order_rows(doc: dict, listing_sha: str) -> list:
    """One row per order the listing row names. Only the fields in FIELDS are
    read; nothing else is ever copied into a row."""
    raw = doc.get("orderDetailJson_s") or []
    raw = raw if isinstance(raw, list) else [raw]
    orders = json.loads("[" + ",".join(raw) + "]") if raw else []
    mbie = str(first(doc.get("tenancyMBIEOrder_txt")) or "").lower() == "yes"
    out = []
    for o in orders:
        out.append({
            "order_id": str(o["orderId"]),
            "case_id": str(doc["id"]),
            "application_number": str(first(doc.get("applicationNumber_s")) or o.get("applicationId") or ""),
            "published_date": _date(first(doc.get("publishedDate_dt"))),
            "decision_date": _date(str(first(doc.get("decisionDateIndex_l")) or "")),
            "date_of_issue": o.get("dateOfIssue"),
            "unpublished_date": _date(first(doc.get("unpublishedDate_s"))),
            "source_url": pdf_url(o, mbie),
            "listing": listing_sha,
        })
    return out


def off_peak(now_local: dt.datetime) -> bool:
    start, end = OFF_PEAK
    return now_local.hour >= start or now_local.hour < end


def months_to_list(today: dt.date, listed: set) -> list:
    """Months never listed, oldest first, then the previous and the current
    month again (orders are still being published into them)."""
    win = window(today)
    out = [m for m in win[:-2] if m not in listed]
    return out + win[-2:]


# ── the lane's tables ─────────────────────────────────────────────────────────

def tables_sql(schema: str = SCHEMA) -> str:
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        return f.read().replace(f"{SCHEMA}_private", f"{schema}_private").replace(f"{SCHEMA}.", f"{schema}.")


class Tables:
    """The lane's tables over a psycopg connection in autocommit mode, so each
    landing and the row that records it are committed as they happen."""

    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema

    def create(self):
        self.conn.execute(tables_sql(self.s))

    def try_lock(self) -> bool:
        """One run of the lane at a time, whoever started it (the scheduler or a
        hand run): a session advisory lock, which holds no row and no snapshot
        and is let go with the connection."""
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def listed_months(self) -> set:
        """Months listed whole; a month read with the old field list is listed again."""
        return {r[0] for r in self.conn.execute(f"SELECT DISTINCT month FROM {self.s}.listings WHERE whole")}

    def add_listing(self, month, num_found, rows_read, sha, url):
        self.conn.execute(f"INSERT INTO {self.s}.listings (month, num_found, rows_read, listing, url, whole) "
                          "VALUES (%s, %s, %s, %s, %s, true)", (month, num_found, rows_read, sha, url))

    def keep_rows(self, month, docs, sha):
        """Each listing row whole into the private twin (ruling 143)."""
        for d in docs:
            self.conn.execute(f"INSERT INTO {self.s}_private.listing_rows (case_id, listing, month, fields) "
                              "VALUES (%s, %s, %s, %s) ON CONFLICT (case_id, listing) DO NOTHING",
                              (str(d.get("id")), sha, month, json.dumps(d, ensure_ascii=False)))

    def upsert_orders(self, rows):
        for r in rows:
            self.conn.execute(
                f"INSERT INTO {self.s}.orders (order_id, case_id, application_number, published_date, decision_date, "
                "date_of_issue, unpublished_date, source_url, listing) VALUES (%(order_id)s, %(case_id)s, "
                "%(application_number)s, %(published_date)s, %(decision_date)s, %(date_of_issue)s, "
                "%(unpublished_date)s, %(source_url)s, %(listing)s) ON CONFLICT (order_id) DO UPDATE SET "
                "unpublished_date = EXCLUDED.unpublished_date, listing = EXCLUDED.listing", r)

    def pending(self, limit: int) -> list:
        cur = self.conn.execute(
            f"SELECT order_id, source_url FROM {self.s}.orders WHERE document IS NULL "
            "AND order_id NOT IN (SELECT item FROM " + self.s + ".set_aside WHERE stage = 'fetch') "
            "ORDER BY unpublished_date NULLS LAST, published_date, order_id LIMIT %s", (limit,))
        return [(r[0], r[1]) for r in cur]

    def captured(self, order_id, sha):
        self.conn.execute(f"UPDATE {self.s}.orders SET document = %s, captured_at = now() WHERE order_id = %s",
                          (sha, order_id))

    def set_aside(self, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.s}.set_aside (item, stage, reason) VALUES (%s, %s, %s)",
                          (item, stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Stop(RuntimeError):
    """The run stops here: a block, a challenge, or the host not answering."""


class Run:
    def __init__(self, tables, *, land_fn, opener=None, pacer=None, gate_pacer=None, clock=None, now_local=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_items: int = 100000, anytime: bool = False, log=print,
                 held=None):
        self.t, self.land_fn, self.opener = tables, land_fn, opener or fg.open_url
        # the gate's hold on the host (ruling 141); an injected opener is a test's site, never the live ledger's host
        self.held = held or ((lambda: fg.refused_by(HOST)) if opener is None else (lambda: None))
        self.pacer = pacer or fg.Pacer()
        self.gate_pacer = gate_pacer
        self.clock = clock or time.monotonic
        self.now_local = now_local or (lambda: dt.datetime.now().astimezone())
        self.budget_s, self.max_items, self.anytime, self.log = budget_s, max_items, anytime, log
        self.started = self.clock()
        self.failures = 0
        self.counts = {"requests": 0, "listings": 0, "listed": 0, "landed": 0, "already_held": 0, "set_aside": 0,
                       "rows_kept": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now_local()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def get(self, url: str):
        """One gated, paced request. Returns the Fetched (a 404 is the host
        answering); None on a transport failure, which is a catch-log line;
        raises Stop on a block, a challenge or three failures in a row.
        A gate refusal (fg.Refused) is never caught."""
        self.pacer.wait(HOST, FLOOR_S)
        self.counts["requests"] += 1
        try:
            kw = {"pacer": self.gate_pacer} if self.gate_pacer is not None else {}
            f = self.opener(url, timeout=60, **kw)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a line, three in a row a stop
            self.failures += 1
            self.t.set_aside(url, "fetch", f"transport: {type(exc).__name__}: {str(exc)[:200]}")
            self.counts["set_aside"] += 1
            if self.failures >= STOP_AFTER_FAILURES:
                raise Stop(f"{self.failures} transport failures in a row; the host may be in trouble")
            return None
        self.failures = 0
        if f.blocked:
            self.t.set_aside(url, "fetch", f.blocked)
            self.counts["set_aside"] += 1
            raise Stop(f.blocked)
        elsewhere = fg.host_of(f.location) if f.status in fg.REDIRECT_STATUSES and f.location else HOST
        if elsewhere != HOST:
            # the gate judged the URL asked and hands back a redirect off it unfetched, in f.location
            why = f"redirected to {elsewhere}: not landed, and the run stops"
            self.t.set_aside(url, "fetch", why)
            self.counts["set_aside"] += 1
            raise Stop(why)
        return f

    def list_month(self, month: dt.date):
        start, rows_read, num_found, last_sha, first_url = 0, 0, None, None, None
        while True:
            url = listing_url(month, start)
            f = self.get(url)
            if f is None or f.status != 200:
                self.t.set_aside(month.isoformat(), "listing", f"HTTP {getattr(f, 'status', 'none')} for {url}")
                self.counts["set_aside"] += 1
                return
            body = decode(f.body)
            try:
                num_found, docs = parse_listing(body)
            except (ValueError, KeyError) as exc:
                self.t.set_aside(month.isoformat(), "listing", f"not a listing: {type(exc).__name__}")
                self.counts["set_aside"] += 1
                return
            ref, _ = self.land_fn(body, name=url, source=SOURCE, name_kind="url", content_type="application/json")
            self.counts["listings"] += 1
            last_sha, first_url = ref.sha256, first_url or url
            rows = [r for d in docs for r in order_rows(d, ref.sha256)]
            self.t.upsert_orders(rows)
            self.t.keep_rows(month, docs, ref.sha256)
            self.counts["listed"] += len(rows)
            self.counts["rows_kept"] += len(docs)
            rows_read += len(docs)
            start += len(docs)
            if not docs or start >= num_found:
                break
        self.t.add_listing(month, num_found, rows_read, last_sha, first_url)
        self.log(f"{SOURCE}: {month:%Y-%m} listed: {rows_read} of {num_found}")

    def fetch_pending(self):
        done = 0
        while done < self.max_items and self.time_left():
            batch = self.t.pending(min(200, self.max_items - done))
            if not batch:
                break
            for order_id, url in batch:
                if done >= self.max_items or not self.time_left():
                    break
                f = self.get(url)
                done += 1
                if f is None:
                    continue
                if f.status != 200 or not f.body.startswith(b"%PDF"):
                    self.t.set_aside(order_id, "fetch", f"HTTP {f.status}" + ("" if f.status != 200 else ", not a PDF"))
                    self.counts["set_aside"] += 1
                    continue
                ref, new = self.land_fn(f.body, name=url, source=SOURCE, name_kind="url", content_type="application/pdf")
                self.t.captured(order_id, ref.sha256)
                self.counts["landed" if new else "already_held"] += 1

    def run(self, today: dt.date, list_only: bool = False) -> dict:
        if (why := self.held()) is not None:
            # ruling 141: a held host is asked nothing, by no request of any kind, until a person clears it; the run
            # is not a failure (it did what it must), and the light says the gap from its declaration
            self.stopped = f"held: the fetch gate holds {HOST} ({why}); nothing asked until a person clears it"
            self.log(f"{SOURCE}: {self.stopped}")
            return {**self.counts, "stopped": self.stopped}
        try:
            if self.time_left():
                for m in months_to_list(today, self.t.listed_months()):
                    if not self.time_left():
                        break
                    self.list_month(m)
            if not list_only:
                self.fetch_pending()
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.tenancy_tribunal.capture")
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
        run = Run(t, land_fn=landing(conn), budget_s=a.budget_s, max_items=a.max_items, anytime=a.anytime)
        out = run.run(dt.date.today(), list_only=a.list_only)
    ok = not out["stopped"].startswith("stopped:")
    detail = (f"{out['listings']} listings, {out['listed']} orders listed, {out['rows_kept']} listing rows kept whole, "
              f"{out['landed']} landed, "
              f"{out['already_held']} already held, {out['set_aside']} set aside; {out['stopped'] or 'done'}")
    print(f"{SOURCE}: {detail}")
    jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
