"""How this lane's documents arrive: case 3 of plan 1.10, one capture of its
own, politely, through the fetch gate and the landing wrapper only. Shared by
both builds of the reading (`charities_a`, `charities_b`, plan step 4.1).

The source is the Charities Register's open data feed, an OData (version 2)
service at `www.odata.charities.govt.nz`: free, no login, read only, Crown
copyright under CC BY 3.0 NZ (the terms are on the open-data page, landed with
the capture). The old estate parsed it straight into tables and kept no file;
its client bypassed the fetch gate. This takes the idea (a verbatim copy, then
a reading) and none of the code.

What is copied, verbatim, as the feed's own JSON pages:

  * the keyed sets (`KEYED`): every organisation, officer and annual return,
    and the groups, the related-party transactions and `vOrganisations` (the
    organisation with its activities, sectors, beneficiaries and areas as the
    register lists them). Each is read in pages of `PAGE` rows, ordered by its
    key, the next page asked for by "key greater than the last one held"
    (never by `$skip`, which shifts when rows are added mid-copy);
  * the whole sets (`WHOLE`): the small code lists, one request each, and the
    documents about the feed (`DOCS`: its metadata, the open-data page with
    its terms, the data dictionary, the diagram, the site's terms of use and
    copyright, and the register's page on restricted information). Weekly.

A pass is one walk over one set: `full` (every row) or `changes` (rows whose
`ModifiedOn` is on or after a day before the last pass began). Its first page
asks for the feed's own count of rows matching ($inlinecount): the figure the
pass reconciles to. A pass that stops part-way (budget, off-peak over, a
failed read) resumes from its last key on the next run, so the first full copy
may take more than one night. A full pass is run again every `FULL_EVERY_DAYS`
so a row the register has since withheld or removed is seen to be gone.

Politeness (hard limit 7): one request at a time; `FLOOR_S` of rest after
each answer, and the gate's own floor from each start, whichever is slower;
pages of `PAGE`, the feed's own stated limit (it caps every query at 1,000
rows "to prevent an open query ... placing an unnecessary load"; `$returnall`
is never used); off-peak only unless `--anytime`; nothing fetched twice
(a page whose bytes are already held adds a name, not a document; the code
lists and documents are asked for weekly). A 403, 429, 5xx or a challenge page
is a failed read (hard limit 6): a catch-log line, and the run STOPS. Nothing
is retried in the same run, solved or got around. A lone transport failure (a
name lookup, a reset, a timeout) on a keyed set's page is a catch-log line: that
set's pass stays open and resumes next run, and the run goes on to the next
set. Three transport failures in a row stop the run. A gate refusal is never
caught, except on the documents about the feed, which are asked last, after
the register: there it ends their part and the run's line says so.

Every line printed is a count. No row, name or address is ever printed.

    python -m registers.charities.capture [--budget-s N] [--max-pages N] [--sets A,B] [--anytime]
    python -m registers.charities.capture --measure     # the held copy against the register's own count
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo

import support.fetchgate as fg

SOURCE = SCHEMA = "charities"
JOB = "qv4-charities-capture"
HOST = "www.odata.charities.govt.nz"
BASE = f"http://{HOST}"          # the service publishes itself on http; https answers the same
PAGE = 1000                      # the feed's own cap on one query
FLOOR_S = 5.0                    # rest after each answer; the gate's floor from each start binds too
OFF_PEAK = (22, 6)               # NZ local hours: start at 22:00, stop at 06:00
STOP_AFTER_FAILURES = 3
DEFAULT_BUDGET_S = 16200         # four and a half hours a night
FULL_EVERY_DAYS = 28
WHOLE_EVERY_DAYS = 7
OVERLAP = dt.timedelta(days=1)   # a changes pass starts a day before the last pass began
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
POSITIONS = None   # the position is in docs/legal/positions/ (moved at the merge of charities-capture-1); None is the gate's default

#: the keyed sets, in the order a run walks them: (name, key, whether it carries ModifiedOn). A set with
#: no ModifiedOn cannot be asked for its changes, so it is copied whole, weekly. Activities, Beneficiaries,
#: Sectors and SourceOfFunds look like code lists but hold every "Other - ..." entry a charity typed
#: (12,728, 7,540, 6,361 and 2,772 rows on 20 October 2026), so they are paged like the rest.
KEYED = (
    ("Groups", "GroupId", True),
    ("Activities", "ActivityId", False),
    ("Beneficiaries", "BeneficiaryId", False),
    ("Sectors", "SectorId", False),
    ("SourceOfFunds", "SourceOfFundsId", False),
    ("Organisations", "OrganisationId", True),
    ("vOrganisations", "OrganisationId", True),
    ("Officers", "OfficerId", True),
    ("AnnualReturn", "AnnualReturnId", True),
    ("AnnualReturnCloseRelationshipTransaction", "AnnualReturnCloseRelationshipTransactionId", True),
)
#: the register's own count of registered charities, asked and landed once at the start of each full pass of
#: Organisations, so the lane's check reads that day's count from a document, not from a note
REGISTERED = "Organisations:Registered"
REGISTERED_FILTER = "RegistrationStatus eq 'Registered'"
#: the code lists: each well under one page
WHOLE = ("AreaOfOperations", "AuditModifiedOpinionReceived", "LegalStructure", "ReportingCurrency", "ReportingTier",
         "MainActivity", "MainBeneficiary", "MainSector", "OfficerStatus", "RegistrationStatus")
#: the documents about the feed: name → URL. Landed as they are; never parsed here.
DOCS = {
    "$metadata": f"{BASE}/$metadata",
    "open-data-page": "https://www.charities.govt.nz/charities-in-new-zealand/the-charities-register/open-data/",
    "data-dictionary": "https://www.charities.govt.nz/__data/assets/excel_doc/0018/19116/Data-Dictionary-17.09.2025.xlsx",
    "erd": "https://www.charities.govt.nz/__data/assets/pdf_file/0023/148352/Charities-OData-ERD.pdf",
    "terms-of-use": "https://www.charities.govt.nz/terms-of-use",
    "copyright": "https://www.charities.govt.nz/copyright",
    "restricting-information": "https://www.charities.govt.nz/im-a-registered-charity/restricting-information",
}
CONTENT_TYPES = {"$metadata": "application/xml", "open-data-page": "text/html",
                 "data-dictionary": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "erd": "application/pdf", "terms-of-use": "text/html", "copyright": "text/html",
                 "restricting-information": "text/html"}


# ── pure pieces ───────────────────────────────────────────────────────────────

def _q(v: str) -> str:
    return urllib.parse.quote(v, safe="'(),:")


def odata_datetime(t: dt.datetime) -> str:
    """The feed's literal for a moment, in UTC without a zone: the feed
    writes ModifiedOn in UTC (`…Z`) and compares a literal as UTC (21
    October 2026: `ge datetime'2026-10-20T06:00:00'` counted 1 organisation,
    `'2026-10-19T19:00:00'` 228, the held rows' last change being 06:02 UTC).
    Seconds kept, microseconds dropped."""
    if t.tzinfo is not None:
        t = t.astimezone(dt.timezone.utc)
    return "datetime'" + t.replace(tzinfo=None, microsecond=0).isoformat() + "'"


def page_url(entity_set: str, key: str, after=None, since: dt.datetime = None, first: bool = False) -> str:
    """One page of a keyed set, ordered by its key, after the last key held."""
    conds = []
    if since is not None:
        conds.append(f"ModifiedOn ge {odata_datetime(since)}")
    if after is not None:
        conds.append(f"{key} gt {int(after)}")
    params = [("$format", "json"), ("$orderby", key), ("$top", str(PAGE))]
    if conds:
        params.append(("$filter", " and ".join(conds)))
    if first:
        params.append(("$inlinecount", "allpages"))
    return f"{BASE}/{entity_set}?" + "&".join(f"{k}={_q(v)}" for k, v in params)


def whole_url(entity_set: str) -> str:
    return f"{BASE}/{entity_set}?$format=json&$inlinecount=allpages"


def count_url(entity_set: str, key: str, filter_: str = None) -> str:
    """The feed's own count for a filter: one row asked for, the count with it.
    (`/$count` is capped at the feed's 1,000 like every query; `$inlinecount` is not.)"""
    params = [("$format", "json"), ("$top", "1"), ("$select", key), ("$inlinecount", "allpages")]
    if filter_:
        params.append(("$filter", filter_))
    return f"{BASE}/{entity_set}?" + "&".join(f"{k}={_q(v)}" for k, v in params)


def parse_page(body: bytes):
    """(stated count or None, rows) from one page of the feed's JSON. The feed
    wraps rows as {"d": [...]} or {"d": {"results": [...], "__count": "N"}}."""
    j = json.loads(body)
    d = j["d"]
    if isinstance(d, list):
        return None, d
    rows = d.get("results")
    if not isinstance(rows, list):
        raise ValueError("no results list")
    c = d.get("__count")
    return (int(c) if c is not None else None), rows


def page_keys(rows: list, key: str, after=None) -> list:
    """The page's keys, which must rise strictly and start after `after`; a
    page that does not is not trusted (a row could be lost or held twice)."""
    keys = [int(r[key]) for r in rows]
    prev = after
    for k in keys:
        if prev is not None and k <= prev:
            raise ValueError(f"key {k} does not follow {prev}")
        prev = k
    return keys


def off_peak(now_local: dt.datetime) -> bool:
    start, end = OFF_PEAK
    return now_local.hour >= start or now_local.hour < end


def plan_pass(last_full_done, last_done_started, open_pass: bool, now: dt.datetime, changes: bool = True):
    """What a keyed set gets on this run: ('resume', None), ('full', None),
    ('changes', since) or ('skip', None) for a set with no ModifiedOn copied
    whole within the week. Pure."""
    if open_pass:
        return "resume", None
    every = FULL_EVERY_DAYS if changes else WHOLE_EVERY_DAYS
    if last_full_done is None or now - last_full_done >= dt.timedelta(days=every):
        return "full", None
    if not changes:
        return "skip", None
    return "changes", last_done_started - OVERLAP


# ── the lane's tables ─────────────────────────────────────────────────────────

READING = "-- ── the reading"   # tables.sql's second part, the reading's tables, made by load.py


def tables_sql(schema: str = SCHEMA) -> str:
    """The capture's part of tables.sql, under `schema`."""
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        return f.read().split(READING)[0].replace(f"{SCHEMA}.", f"{schema}.")


class Tables:
    """The capture's record over a psycopg connection in autocommit mode, so
    each landing and the row that lists it are committed as they happen."""

    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema

    def create(self):
        self.conn.execute(tables_sql(self.s))

    def try_lock(self) -> bool:
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def open_pass(self, entity_set):
        r = self.conn.execute(f"SELECT pass_id, mode, since, next_key, pages FROM {self.s}.capture_passes "
                              "WHERE entity_set = %s AND finished_at IS NULL ORDER BY pass_id DESC LIMIT 1",
                              (entity_set,)).fetchone()
        return None if r is None else {"pass_id": r[0], "mode": r[1], "since": r[2], "next_key": r[3], "pages": r[4]}

    def last_done(self, entity_set, mode=None):
        """(finished_at, started_at) of the newest finished pass, of a mode if given."""
        sql = f"SELECT finished_at, started_at FROM {self.s}.capture_passes WHERE entity_set = %s AND finished_at IS NOT NULL"
        args = [entity_set]
        if mode:
            sql += " AND mode = %s"
            args.append(mode)
        r = self.conn.execute(sql + " ORDER BY finished_at DESC LIMIT 1", args).fetchone()
        return (None, None) if r is None else (r[0], r[1])

    def begin(self, entity_set, mode, since=None) -> dict:
        pid = self.conn.execute(f"INSERT INTO {self.s}.capture_passes (entity_set, mode, since) VALUES (%s, %s, %s) "
                                "RETURNING pass_id", (entity_set, mode, since)).fetchone()[0]
        return {"pass_id": pid, "mode": mode, "since": since, "next_key": None, "pages": 0}

    def add_page(self, p, entity_set, url, sha, rows, first_key, last_key, new, stated=None):
        p["pages"] += 1
        self.conn.execute(
            f"INSERT INTO {self.s}.capture_pages (pass_id, page_no, entity_set, url, sha256, rows, first_key, last_key, new) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (p["pass_id"], p["pages"], entity_set, url, sha, rows, first_key, last_key, new))
        self.conn.execute(
            f"UPDATE {self.s}.capture_passes SET pages = pages + 1, rows_landed = rows_landed + %s, "
            "next_key = COALESCE(%s, next_key), stated = COALESCE(%s, stated) WHERE pass_id = %s",
            (rows, last_key, stated, p["pass_id"]))
        if last_key is not None:
            p["next_key"] = last_key

    def finish(self, p):
        self.conn.execute(f"UPDATE {self.s}.capture_passes SET finished_at = now() WHERE pass_id = %s", (p["pass_id"],))

    def set_aside(self, pass_id, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.s}.capture_set_aside (pass_id, item, stage, reason) VALUES (%s, %s, %s, %s)",
                          (pass_id, item, stage, reason[:500]))
        if pass_id is not None:
            self.conn.execute(f"UPDATE {self.s}.capture_passes SET set_aside = set_aside + 1 WHERE pass_id = %s", (pass_id,))


# ── a run ─────────────────────────────────────────────────────────────────────

class Stop(RuntimeError):
    """The run stops here: a block, a challenge, the host not answering, or a page not to be trusted."""


class Run:
    def __init__(self, tables, *, land_fn, opener=None, clock=None, sleep=None, now_local=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_pages: int = 100000, anytime: bool = False,
                 sets=None, log=print):
        self.t, self.land_fn = tables, land_fn
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.now_local = now_local or (lambda: dt.datetime.now().astimezone())
        self.budget_s, self.max_pages, self.anytime, self.log = budget_s, max_pages, anytime, log
        self.sets = set(sets) if sets else None
        self.started = self.clock()
        self.last_end = None
        self.failures = 0
        self.last_failure = None
        self.waiting = []            # keyed sets whose page failed in transport this run; each resumes next run
        self.counts = {"requests": 0, "pages": 0, "rows": 0, "new": 0, "already_held": 0, "set_aside": 0,
                       "passes_finished": 0}
        self.stopped = ""

    def wanted(self, name) -> bool:
        return self.sets is None or name in self.sets

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if self.counts["requests"] >= self.max_pages:
            self.stopped = self.stopped or "page cap reached"
            return False
        if not self.anytime and not off_peak(self.now_local()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def get(self, url: str, pass_id=None):
        """One gated request after the rest. The Fetched, or None on a lone
        transport failure (a catch-log line); Stop on a block, a challenge, an
        answer from another host, or three failures in a row."""
        if self.last_end is not None:
            gap = self.last_end + FLOOR_S - self.clock()
            if gap > 0:
                self.sleep(gap)
        self.counts["requests"] += 1
        self.last_failure = None
        try:
            f = self.opener(url, 120)
        except fg.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 — a transport failure is a line, three in a row a stop
            self.last_end = self.clock()
            self.failures += 1
            self.last_failure = "transport"
            self._aside(pass_id, url, "fetch", f"transport: {type(exc).__name__}: {str(exc)[:200]}")
            if self.failures >= STOP_AFTER_FAILURES:
                raise Stop(f"{self.failures} transport failures in a row; the host may be in trouble")
            return None
        self.last_end = self.clock()
        self.failures = 0
        if f.blocked:
            self._aside(pass_id, url, "fetch", f.blocked)
            raise Stop(f.blocked)
        # the gate hands back a redirect off the host asked unfetched, in f.location (final_url is the URL asked)
        if f.status in fg.REDIRECT_STATUSES and f.location and fg.host_of(f.location) != fg.host_of(url):
            why = f"redirected to {fg.host_of(f.location)}: not landed, and the run stops"
            self._aside(pass_id, url, "fetch", why)
            raise Stop(why)
        if f.status != 200:
            self.last_failure = "status"
            self._aside(pass_id, url, "fetch", f"HTTP {f.status}")
            return None
        return f

    def _aside(self, pass_id, url, stage, why):
        self.t.set_aside(pass_id, url, stage, why)
        self.counts["set_aside"] += 1

    def _land(self, body, url, content_type="application/json"):
        ref, new = self.land_fn(body, name=url, source=SOURCE, name_kind="url", content_type=content_type)
        self.counts["new" if new else "already_held"] += 1
        return ref, new

    # the keyed sets
    def walk(self, entity_set: str, key: str, now: dt.datetime, changes: bool = True):
        p = self.t.open_pass(entity_set)
        what, since = plan_pass(self.t.last_done(entity_set, "full")[0], self.t.last_done(entity_set)[1],
                                p is not None, now, changes)
        if what == "skip":
            return
        if what != "resume":
            p = self.t.begin(entity_set, what, since)
        while self.time_left():
            first = p["pages"] == 0
            url = page_url(entity_set, key, p["next_key"], p["since"], first=first)
            f = self.get(url, p["pass_id"])
            if f is None and self.last_failure == "transport":
                # a lone transport failure (a name lookup, a reset) is a catch-log line, not a stop: this set's
                # pass stays open and resumes from its last key next run, and the run moves to the next set;
                # three in a row stop the run in get() (4 November 2026: a name lookup failed once on the
                # odata host between two good answers, and stopped every set after Groups)
                self.waiting.append(entity_set)
                self.log(f"{SOURCE}: {entity_set}: a page failed in transport; the pass resumes from key "
                         f"{p['next_key']} next run")
                return
            if f is None:
                raise Stop(f"{entity_set}: a page failed; the pass resumes from key {p['next_key']} next run")
            try:
                stated, rows = parse_page(f.body)
                keys = page_keys(rows, key, p["next_key"])
            except (ValueError, KeyError, TypeError) as exc:
                self._aside(p["pass_id"], url, "parse", f"not a page of {entity_set}: {type(exc).__name__}: {exc}"[:300])
                raise Stop(f"{entity_set}: a page could not be trusted")
            ref, new = self._land(f.body, url)
            self.t.add_page(p, entity_set, url, ref.sha256, len(rows), keys[0] if keys else None,
                            keys[-1] if keys else None, new, stated if first else None)
            self.counts["pages"] += 1
            self.counts["rows"] += len(rows)
            if first and entity_set == "Organisations" and p["mode"] == "full":
                self.registered()
            if len(rows) < PAGE:
                self.t.finish(p)
                self.counts["passes_finished"] += 1
                self.log(f"{SOURCE}: {entity_set} {p['mode']} pass {p['pass_id']} finished: {p['pages']} pages")
                return

    def registered(self):
        """The register's count of registered charities, as its own answer
        ($inlinecount, one row asked), landed by hash as a one-page pass of
        its own; the count is the pass's `stated`. A failed read is a
        catch-log line and the pass finishes with nothing landed."""
        p = self.t.begin(REGISTERED, "whole")
        url = count_url("Organisations", "OrganisationId", REGISTERED_FILTER)
        f = self.get(url, p["pass_id"])
        if f is not None:
            try:
                stated, rows = parse_page(f.body)
                if stated is None:
                    raise ValueError("no count in the answer")
            except (ValueError, KeyError, TypeError) as exc:
                self._aside(p["pass_id"], url, "parse", f"not the register's count: {type(exc).__name__}")
            else:
                ref, new = self._land(f.body, url)
                self.t.add_page(p, REGISTERED, url, ref.sha256, len(rows), None, None, new, stated)
                self.counts["pages"] += 1
        self.t.finish(p)
        self.counts["passes_finished"] += 1

    # the code lists and the documents about the feed
    def whole(self, name: str, url: str, now: dt.datetime, parse: bool, content_type: str):
        done, _ = self.t.last_done(name, "whole")
        if done is not None and now - done < dt.timedelta(days=WHOLE_EVERY_DAYS):
            return
        if not self.time_left():
            return
        p = self.t.begin(name, "whole")
        f = self.get(url, p["pass_id"])
        if f is None:
            return
        rows, stated = None, None
        if parse:
            try:
                stated, rs = parse_page(f.body)
                rows = len(rs)
            except (ValueError, KeyError, TypeError) as exc:
                self._aside(p["pass_id"], url, "parse", f"not a page of {name}: {type(exc).__name__}")
                return
            if rows >= PAGE:
                self._aside(p["pass_id"], url, "parse", f"{name} reached the feed's cap of {PAGE}: page it as a keyed set")
                self.t.finish(p)
                return
        ref, new = self._land(f.body, url, content_type)
        self.t.add_page(p, name, url, ref.sha256, rows or 0, None, None, new, stated)
        self.t.finish(p)
        self.counts["pages"] += 1
        self.counts["rows"] += rows or 0
        self.counts["passes_finished"] += 1

    def run(self) -> dict:
        """The register first (the keyed sets, then the code lists, all on the odata host), the documents
        about the feed last, so a block on, or a gate hold of, the documents' host can never stop the
        register being captured (decided 5 November 2026). A gate refusal is caught on the documents only:
        it ends their part, the register already landed, and the run's line says so."""
        now = self.now_local()
        try:
            for name, key, changes in KEYED:
                if self.wanted(name) and self.time_left():
                    self.walk(name, key, now, changes)
            for name in WHOLE:
                if self.wanted(name):
                    self.whole(name, whole_url(name), now, True, "application/json")
            try:
                for name, url in DOCS.items():
                    if self.wanted(name):
                        self.whole(name, url, now, False, CONTENT_TYPES[name])
            except fg.Refused as exc:
                raise Stop(f"the documents about the feed: the fetch gate refused {name} ({str(exc)[:200]}); "
                           "the register was captured before them") from exc
        except Stop as exc:
            self.stopped = f"stopped: {exc}"
        if self.waiting and not self.stopped.startswith("stopped:"):
            wait = f"{', '.join(self.waiting)} failed in transport and resume next run"
            self.stopped = f"{self.stopped}; {wait}" if self.stopped else wait
        return {**self.counts, "stopped": self.stopped, "waiting": list(self.waiting)}


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


# ── the measure: the held copy against the register's own count ──────────────

def count_registered(body: bytes) -> tuple:
    """(rows, registered) in one held page of Organisations. Counts only."""
    _, rows = parse_page(body)
    return len(rows), sum(1 for r in rows if r.get("RegistrationStatus") == "Registered")


def measure(conn, schema: str = SCHEMA, opener=None, read=None) -> dict:
    """The latest finished full pass of Organisations, counted from the held
    pages, against the feed's own count of registered charities asked now."""
    from support.docstore.landing import read_bytes
    read = read or read_bytes
    r = conn.execute(f"SELECT pass_id, stated, rows_landed, started_at, finished_at FROM {schema}.capture_passes "
                     "WHERE entity_set = 'Organisations' AND mode = 'full' AND finished_at IS NOT NULL "
                     "ORDER BY finished_at DESC LIMIT 1").fetchone()
    if r is None:
        return {"ok": False, "detail": "no finished full pass of Organisations is held"}
    pass_id, stated, landed, started, finished = r
    rows = registered = 0
    for (sha,) in conn.execute(f"SELECT sha256 FROM {schema}.capture_pages WHERE pass_id = %s ORDER BY page_no", (pass_id,)):
        n, k = count_registered(read(sha))
        rows += n
        registered += k
    opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
    f = opener(count_url("Organisations", "OrganisationId", "RegistrationStatus eq 'Registered'"), 60)
    if f.blocked or f.status != 200:
        return {"ok": False, "detail": f"the register's count could not be read: {f.blocked or f.status}"}
    register_count, _ = parse_page(f.body)
    return {"ok": registered == register_count and rows == stated, "pass_id": pass_id,
            "pass_started": started.isoformat(timespec="minutes"), "pass_finished": finished.isoformat(timespec="minutes"),
            "stated_at_start": stated, "rows_held": rows, "registered_held": registered,
            "registered_now": register_count, "difference": registered - register_count}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.charities.capture")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--max-pages", type=int, default=100000)
    ap.add_argument("--sets", default="", help="comma-separated set or document names; default all")
    ap.add_argument("--anytime", action="store_true", help="run outside off-peak (by hand, on Arthur's word)")
    ap.add_argument("--measure", action="store_true", help="the held copy against the register's own count")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db, jobrun
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        if a.measure:
            out = measure(conn, a.schema)
            print(f"{SOURCE}: measure: " + json.dumps(out))
            return 0 if out["ok"] else 1
        started = jobrun.now()
        t = Tables(conn, a.schema)
        t.create()
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            jobrun.record(JOB, True, "skipped: another run holds the lane", started, {})
            return 0
        run = Run(t, land_fn=landing(conn), budget_s=a.budget_s, max_pages=a.max_pages, anytime=a.anytime,
                  sets=[s for s in a.sets.split(",") if s] or None)
        out = run.run()
    ok = not out["stopped"].startswith("stopped:")
    detail = (f"{out['requests']} requests, {out['pages']} pages ({out['rows']} rows), {out['new']} new, "
              f"{out['already_held']} already held, {out['set_aside']} set aside, {out['passes_finished']} passes "
              f"finished; {out['stopped'] or 'done'}")
    print(f"{SOURCE}: {detail}")
    jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
