"""How this lane's documents arrive (plan 1.10), two cases:

1. **Copied by hash from the old estate** (case one). The old estate's news
   database lists 351 InfoCouncil minutes PDFs it fetched (`incoming_news.
   documents`, 14 instances, 26 July to 18 October 2026) with their sha256 and
   the path of the file. That listing was exported once, on 22 October 2026
   (`export_listing`), landed by its hash and pinned here (`LISTING_SHA`). On
   22 October none of the 351 files is on node2: they sit on the old estate's
   other box, out of service (still so on 2 November: node1 does not answer).
   The capture copies a listed one by hash whenever its file is on this box
   and hashes true (`copy_all`, `support.docstore.landing.copy_from_old`,
   read-only). Where the old copy's bytes are not here, the capture fetches
   the council's own public copy once, like any other minutes PDF (politely,
   off-peak, through the gate; a challenge is a failed read), lands it by its
   own hash, and records whether those bytes are the old estate's (the listed
   hash) or differ (2 November 2026: the 347 the old estate held and the new
   estate did not read; before that they waited as `held by the old
   estate`). The old database keeps their text only, never their bytes. The
   old estate's other 1,159 InfoCouncil minutes were kept as stripped text,
   not bytes: there is no document to copy, so those are fetched.

2. **Captured once, politely** (case three), the job `qv4-council-minutes-
   capture`: each instance's listing (its default page: the year's meetings,
   `read.py`'s profile `infocouncil-meeting-listing`) at most weekly, and every
   minutes PDF a held listing names, once. Agendas and attachments are listed,
   not fetched. The minutes are landed and never read (plan 6.3: no read of
   attendance or resolutions; ruling 79). Through `support.fetchgate.open_url`
   and the landing wrapper only; one request at a time, `FLOOR_S` apart,
   off-peak (22:00 to 06:00 NZ time) unless `--anytime`, a budget per run.

A 403, 429, 5xx or challenge page (hard limit 6), a refusal of the gate, or a
listing answering 404 (the instance moved) holds that instance: it is
logged, set aside and not asked again until a session reads why and clears
`capture_held_hosts`; the run goes on to the next instance. A document that
fails is `failed` and never asked again. A redirect off the host is not
followed. The position on file is `position/council-meeting-platform-
infocouncil.md` (the integrator moves it to docs/legal/positions/).

    python -m registers.council_minutes.capture [--anytime] [--budget-s N] [--max-docs N]
    python -m registers.council_minutes.capture --copy-old      land what the old estate's files hold, by hash
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

import support.fetchgate as fg
from registers.council_minutes import read

SOURCE = SCHEMA = "council_minutes"
JOB = "qv4-council-minutes-capture"
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
LISTING_EVERY_DAYS = 7
DEFAULT_BUDGET_S = 2 * 3600
NZ = ZoneInfo("Pacific/Auckland")
HERE = os.path.dirname(os.path.abspath(__file__))
READING = "-- ── the reading"
#: until the integrator moves the position to docs/legal/positions/, a session points QV4_POSITIONS at a folder holding it
POSITIONS = os.environ.get("QV4_POSITIONS") or None
LISTING_NAME = "council-minutes-listing-2026-10-22.jsonl"
LISTING_SHA = "2264a8579224e796d450e61494b6c9285ace3efd7589ea672d90eb0be13bcb9b"
EXPORTED_AT = "2026-10-22T19:53:51+13:00"

#: the old estate's verified list (ingestion/councils/instances.py, 17 and 25 July 2026): base → council
INSTANCES = {
    "https://christchurch.infocouncil.biz": "Christchurch City Council",
    "https://huttcity.infocouncil.biz": "Hutt City Council",
    "https://kapiticoast.infocouncil.biz": "Kāpiti Coast District Council",
    "https://carterton.infocouncil.biz": "Carterton District Council",
    "https://palmerstonnorth.infocouncil.biz": "Palmerston North City Council",
    "https://horowhenua.infocouncil.biz": "Horowhenua District Council",
    "https://tararua.infocouncil.biz": "Tararua District Council",
    "https://hastings.infocouncil.biz": "Hastings District Council",
    "https://napier.infocouncil.biz": "Napier City Council",
    "https://wairoa.infocouncil.biz": "Wairoa District Council",
    "https://tasman.infocouncil.biz": "Tasman District Council",
    "https://waimate.infocouncil.biz": "Waimate District Council",
    "https://southland.infocouncil.biz": "Southland District Council",
    "https://taupo.infocouncil.biz": "Taupō District Council",
    "https://mackenzie.infocouncil.biz": "Mackenzie District Council",
    "https://waitaki.infocouncil.biz": "Waitaki District Council",
    "https://centralotago.infocouncil.biz": "Central Otago District Council",
    "https://northland.infocouncil.biz": "Northland Regional Council",
    "https://infocouncil.fndc.govt.nz": "Far North District Council",
    "https://westernbayofplenty.infocouncil.biz": "Western Bay of Plenty District Council",
    "https://infocouncil.tauranga.govt.nz": "Tauranga City Council",
    "https://infocouncil.dunedin.govt.nz": "Dunedin City Council",
    "https://infocouncil.boprc.govt.nz": "Bay of Plenty Regional Council",
    "https://hawkesbay.infocouncil.biz": "Hawke's Bay Regional Council",
}
COUNCIL_OF_HOST = {b.split("//", 1)[1]: c for b, c in INSTANCES.items()}


# ── pure pieces ───────────────────────────────────────────────────────────────

def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    """The lane's own schema holds its tables by their names; any other (a session's scratch schema, a staging
    schema) carries the lane's prefix."""
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


def capture_sql(schema: str = SCHEMA) -> str:
    import re
    with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
        text = f.read().split(READING)[0]
    pre = "" if schema == SCHEMA else f"{SCHEMA}_"
    return re.sub(rf"(?<![A-Za-z0-9_]){SCHEMA}\.", f"{schema}.{pre}", text)


def grid_rows(body: bytes) -> int:
    """The grid's own row count, counted apart from the reader (check.py holds the reading to it)."""
    return body.count(b'<tr class="bpsGridMenuItem">') + body.count(b'<tr class="bpsGridMenuAltItem">')


def old_key(url: str) -> str:
    """host/FILE (upper case): how an old listed document is matched to a listing's link."""
    host = fg.host_of(url)
    return f"{host}/{url.rsplit('/', 1)[-1].upper()}"


def listing(data: bytes) -> list:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def old_held(entries: list) -> dict:
    """host/FILE → the old estate's listed sha256."""
    return {old_key(e["url"]): e["sha256"] for e in entries if e.get("url") and e.get("sha256")}


# ── case one: the old estate's files ──────────────────────────────────────────

def export_listing(connect=None) -> bytes:
    """One line per InfoCouncil document the old estate lists, sorted; no text. Read-only, under a time limit;
    run once (22 October 2026)."""
    from support import db
    connect = connect or (lambda name: db.connect(db.OLD_READ_KEY, name, connect_timeout=10))
    lines = []
    with connect("incoming_news") as c:
        c.execute("SET statement_timeout = '60s'")
        for src, ref, url, fn, sha, path, pages, chars, status, created, supp in c.execute(
                "SELECT source, ref, url, filename, sha256, pdf_path, pages, char_count, status, created_at::text, "
                "suppressed_at IS NOT NULL FROM documents WHERE source LIKE %s OR source LIKE %s "
                "ORDER BY source, url, sha256", ("%.infocouncil.biz", "infocouncil.%")):
            lines.append(json.dumps({"source": src, "ref": ref, "url": url, "file": fn, "sha256": sha, "old_path": path,
                                     "pages": pages, "chars": chars, "status": status, "captured_at": created,
                                     "old_suppressed": supp}, ensure_ascii=False, sort_keys=True))
    return ("\n".join(lines) + "\n").encode("utf-8")


def scratch_dir() -> str:
    return os.environ.get("QV4_COUNCILS_EXPORT_DIR") or "/home/user/querynzv4-work/scratch/councils-1"


def land_listing(conn, sha: str = None):
    """The pinned listing, from the store (or the session's scratch folder where the once-only export wrote it),
    landed in `conn`'s document tables. Returns (DocumentRef, entries)."""
    from support.docstore.landing import land, path_for, read_bytes
    sha = sha or LISTING_SHA
    if os.path.exists(path_for(sha)):
        data = read_bytes(sha)
    else:
        p = os.path.join(scratch_dir(), LISTING_NAME)
        if not os.path.exists(p) or hashlib.sha256(open(p, "rb").read()).hexdigest() != sha:
            raise LookupError(f"the council minutes listing {sha} is neither in the document store nor at {p}")
        data = open(p, "rb").read()
    ref, _ = land(data, name=LISTING_NAME, source=SOURCE, conn=conn, fetched_at=EXPORTED_AT)
    return ref, listing(data)


def copy_all(conn, entries: list, only: set = None) -> tuple:
    """Every listed file present and true, landed by hash: ([(entry, DocumentRef)], [(sha, why)])."""
    from support.docstore.landing import copy_from_old, land, path_for, read_bytes
    held, aside = [], []
    for e in entries:
        sha = e["sha256"]
        if only is not None and sha not in only:
            continue
        if os.path.exists(path_for(sha)):
            ref, _ = land(read_bytes(sha), name=e["url"], source=SOURCE, conn=conn, name_kind="url",
                          fetched_at=e["captured_at"])
            held.append((e, ref))
            continue
        p = e.get("old_path")
        if not p or not os.path.exists(p):
            aside.append((sha, "not on this box: the old estate's file sits on its other box; copied when it is back"))
            continue
        with open(p, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
        if got != sha:
            aside.append((sha, f"the old file hashes to {got[:12]}, not the listed hash"))
            continue
        ref, _ = copy_from_old(p, SOURCE, conn)
        land(read_bytes(ref.sha256), name=e["url"], source=SOURCE, conn=conn, name_kind="url", fetched_at=e["captured_at"])
        held.append((e, ref))
    return held, aside


# ── the lane's capture tables ─────────────────────────────────────────────────

class Tables:
    """The capture's record over a psycopg connection in autocommit mode."""

    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.s = conn, schema
        self.T = lambda t: table(schema, t)

    def create(self):
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.s}")
        self.conn.execute(capture_sql(self.s))

    def try_lock(self) -> bool:
        return bool(self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0])

    def held_hosts(self) -> dict:
        return dict(self.conn.execute(f"SELECT host, why FROM {self.T('capture_held_hosts')}").fetchall())

    def hold(self, host, why):
        self.conn.execute(f"INSERT INTO {self.T('capture_held_hosts')} (host, why) VALUES (%s, %s) "
                          "ON CONFLICT DO NOTHING", (host, why[:500]))
        self.set_aside(host, "instance", why)

    def last_listing(self, host):
        return self.conn.execute(f"SELECT max(asked_at) FROM {self.T('capture_listings')} WHERE host = %s "
                                 "AND sha256 IS NOT NULL", (host,)).fetchone()[0]

    def listing(self, host, url, status, sha, rows, why):
        self.conn.execute(f"INSERT INTO {self.T('capture_listings')} (host, url, status, sha256, rows, why) "
                          "VALUES (%s, %s, %s, %s, %s, %s)", (host, url, status, sha, rows, why))

    def held_listings(self) -> list:
        """[(host, sha256)] of every listing landed, newest first."""
        return [tuple(r) for r in self.conn.execute(
            f"SELECT host, sha256 FROM {self.T('capture_listings')} WHERE sha256 IS NOT NULL "
            "ORDER BY asked_at DESC, listing_id DESC")]

    def known(self) -> set:
        return {r[0] for r in self.conn.execute(f"SELECT url FROM {self.T('capture_documents')}")}

    def old_waiting(self) -> set:
        """The URLs recorded `held by the old estate`: copied or fetched at the next run."""
        return {r[0] for r in self.conn.execute(f"SELECT url FROM {self.T('capture_documents')} "
                                                "WHERE state = 'held by the old estate'")}

    def document(self, url, host, file, state, sha, listed_in, why=None, asked=True):
        self.conn.execute(
            f"INSERT INTO {self.T('capture_documents')} (url, host, file, state, sha256, listed_in, asked_at, why) "
            "VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END, %s) ON CONFLICT (url) DO UPDATE SET "
            "state = EXCLUDED.state, sha256 = EXCLUDED.sha256, asked_at = EXCLUDED.asked_at, why = EXCLUDED.why",
            (url, host, file, state, sha, listed_in, asked, why))

    def set_aside(self, item, stage, reason):
        self.conn.execute(f"INSERT INTO {self.T('capture_set_aside')} (item, stage, reason) VALUES (%s, %s, %s)",
                          (str(item), stage, reason[:500]))


# ── a run ─────────────────────────────────────────────────────────────────────

class Run:
    def __init__(self, tables, *, land_fn, old: dict, read_fn, opener=None, clock=None, sleep=None, now=None,
                 budget_s: float = DEFAULT_BUDGET_S, max_docs: int = 100000, anytime: bool = False,
                 instances: dict = None, log=print, copy_old=None, fetch_old: bool = True):
        self.t, self.land_fn, self.old, self.read_fn, self.log = tables, land_fn, old, read_fn, log
        #: copy_old(url, listed sha256) -> the landed DocumentRef, or None when the old estate's file is not on this box
        #: (or does not hash true); fetch_old: then fetch the council's own copy, once
        self.copy_old, self.fetch_old = copy_old or (lambda url, sha: None), fetch_old
        self.opener = opener or (lambda url, timeout: fg.open_url(url, timeout=timeout, positions_dir=POSITIONS))
        self.clock = clock or time.monotonic
        self.pacer = fg.Pacer(now=self.clock, sleep=sleep or time.sleep)
        self.now = now or (lambda: dt.datetime.now(NZ))
        self.budget_s, self.max_docs, self.anytime = budget_s, max_docs, anytime
        self.instances = instances if instances is not None else INSTANCES
        self.started = self.clock()
        self.counts = {"requests": 0, "listings": 0, "landed": 0, "already_held": 0, "old_estate": 0, "failed": 0,
                       "held_hosts": 0, "set_aside": 0, "old_copied": 0, "old_fetched": 0, "old_fetched_differs": 0}
        self.stopped = ""

    def time_left(self) -> bool:
        if self.clock() - self.started >= self.budget_s:
            self.stopped = self.stopped or "budget spent"
            return False
        if not self.anytime and not off_peak(self.now()):
            self.stopped = self.stopped or "off-peak is over"
            return False
        return True

    def ask(self, url):
        """One gated, paced request: (Fetched, None) or (None, why it failed)."""
        self.pacer.wait(fg.host_of(url), FLOOR_S)
        self.counts["requests"] += 1
        try:
            f = self.opener(url, 90)
        except fg.Refused as exc:
            return None, f"refused by the gate: {str(exc)[:200]}"
        except Exception as exc:  # noqa: BLE001 — a transport failure is a failed read
            return None, f"transport: {type(exc).__name__}: {str(exc)[:200]}"
        if f.blocked:
            return None, f.blocked
        if f.status != 200 or not f.body:
            return None, f"HTTP {f.status}" + (f", redirected to {f.location}: not followed" if f.location else "")
        return f, None

    def listings(self, held: dict):
        for base, council in self.instances.items():
            host = base.split("//", 1)[1]
            if host in held or not self.time_left():
                continue
            last = self.t.last_listing(host)
            if last is not None and (dt.datetime.now(dt.timezone.utc) - last).days < LISTING_EVERY_DAYS:
                continue
            url = base + "/"
            f, why = self.ask(url)
            if f is None:
                self.t.listing(host, url, None, None, None, why)
                self.t.hold(host, f"the listing: {why}")
                held[host] = why
                self.counts["held_hosts"] += 1
                continue
            try:
                self.read_fn(f.body)
            except read.NotTheShape as exc:
                self.t.listing(host, url, f.status, None, None, str(exc))
                self.t.hold(host, f"the listing is not the shape: {exc}")
                held[host] = str(exc)
                self.counts["held_hosts"] += 1
                continue
            ref, new = self.land_fn(f.body, name=url, content_type="text/html")
            self.t.listing(host, url, f.status, ref.sha256, grid_rows(f.body), None)
            self.counts["listings"] += 1

    def todo(self, held: dict) -> list:
        """Every minutes PDF a held listing names and the capture has not met: [(url, host, file, listing sha)],
        newest listing first, in its row order."""
        from support.docstore.landing import read_bytes
        known, out, seen = self.t.known() - self.t.old_waiting(), [], set()
        for host, sha in self.t.held_listings():
            base = next((b for b in self.instances if b.endswith("//" + host)), f"https://{host}")
            for d in read.read_listing(read_bytes(sha), sha, base)["documents"]:
                if d["kind"] != "minutes" or d["format"] != "pdf" or d["url"] in known or d["url"] in seen:
                    continue
                seen.add(d["url"])
                out.append((d["url"], host, d["file"], sha))
        return out

    def documents(self, held: dict):
        asked = 0
        for url, host, file, listed_in in self.todo(held):
            old_sha = self.old.get(old_key(url))
            if old_sha:
                ref = self.copy_old(url, old_sha)
                if ref is not None:                          # the old estate's own bytes, by hash: no request
                    self.t.document(url, host, file, "landed", ref.sha256, listed_in,
                                    "copied by hash from the old estate's file", asked=False)
                    self.counts["old_copied"] += 1
                    continue
                if not self.fetch_old:
                    self.t.document(url, host, file, "held by the old estate", old_sha, listed_in,
                                    "copied by hash from the old estate's file when its box is back", asked=False)
                    self.counts["old_estate"] += 1
                    continue
            if host in held or not self.time_left():
                continue
            if asked >= self.max_docs:
                self.stopped = self.stopped or f"the document cap ({self.max_docs}) reached"
                break
            asked += 1
            f, why = self.ask(url)
            if f is None:
                self.t.document(url, host, file, "failed", None, listed_in,
                                why + (f"; the old estate listed {old_sha}, its file not on this box" if old_sha else ""))
                self.t.set_aside(url, "fetch", why)
                self.counts["failed"] += 1
                if not why.startswith(("HTTP 404", "transport")):
                    self.t.hold(host, f"a minutes document: {why}")
                    held[host] = why
                    self.counts["held_hosts"] += 1
                continue
            if not f.body.startswith(b"%PDF"):
                self.t.document(url, host, file, "set aside", None, listed_in, "not a PDF")
                self.t.set_aside(url, "shape", "a minutes PDF link answered with something that is not a PDF")
                self.counts["set_aside"] += 1
                continue
            ref, new = self.land_fn(f.body, name=url, content_type="application/pdf")
            why = None
            if old_sha:
                same = ref.sha256 == old_sha
                why = ("the old estate's file is not on this box: the council's copy fetched, "
                       + ("the old estate's bytes (its listed hash)" if same else f"not the old estate's bytes (it listed {old_sha})"))
                self.counts["old_fetched"] += 1
                self.counts["old_fetched_differs"] += 0 if same else 1
            self.t.document(url, host, file, "landed", ref.sha256, listed_in, why)
            self.counts["landed" if new else "already_held"] += 1

    def run(self) -> dict:
        held = self.t.held_hosts()
        self.listings(held)
        self.documents(held)
        return {**self.counts, "stopped": self.stopped}


def outcome(out: dict):
    """(ok, last words): green when something was asked and landed or nothing was due; red when every ask failed."""
    if out["requests"] and not (out["listings"] or out["landed"] or out["already_held"]):
        return False, (out["stopped"] or "done") + "; nothing landed"
    return True, out["stopped"] or "done"


def copier(conn, entries: list):
    """copy_old for a run: the old estate's file for (url, listed sha256), landed by hash when it is on this box and
    hashes true (copy_all), else None."""
    def copy_old(url, sha):
        got, _aside = copy_all(conn, [e for e in entries if e.get("sha256") == sha and old_key(e["url"]) == old_key(url)],
                               only={sha})
        return got[0][1] if got else None
    return copy_old


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, content_type):
        return land(data, name=name, source=SOURCE, conn=conn, name_kind="url", content_type=content_type)
    return land_fn


# ── adopting a session's capture record ───────────────────────────────────────

ADOPT_TABLES = ('capture_listings', 'capture_documents', 'capture_held_hosts', 'capture_set_aside')


def adopt(src, dst, src_schema: str, dst_schema: str = SCHEMA, log=print) -> dict:
    """Carry a session's proven capture record (its scratch schema in the sample database) into the lane's own schema
    on `dst`, once, so the first live run asks nothing the session already asked; each landed document's bytes are
    landed again on `dst` from the document store (no fetch). Refuses when the lane's record on `dst` is not empty."""
    from support.docstore.landing import land, names_of, path_for, read_bytes
    Tables(dst, dst_schema).create()
    if any(dst.execute(f"SELECT 1 FROM {table(dst_schema, t)} LIMIT 1").fetchone() for t in ADOPT_TABLES):
        raise RuntimeError(f"{SCHEMA}: the live capture record is not empty; nothing adopted")
    counts = {}
    for t in ADOPT_TABLES:
        cur = src.execute(f"SELECT * FROM {table(src_schema, t)}")
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        with dst.cursor().copy(f"COPY {table(dst_schema, t)} ({', '.join(cols)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        for c in cols:                                   # a serial id copied as it was: move its sequence past it
            seq = dst.execute("SELECT pg_get_serial_sequence(%s, %s)", (table(dst_schema, t), c)).fetchone()[0]
            if seq and rows:
                dst.execute(f"SELECT setval(%s, (SELECT max({c}) FROM {table(dst_schema, t)}))", (seq,))
        counts[t] = len(rows)
    shas = set()
    for t in ADOPT_TABLES:
        cols = [r[0] for r in src.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                                          "AND table_name = %s", (src_schema, table(src_schema, t).split(".", 1)[1]))]
        if "sha256" in cols:
            shas |= {r[0] for r in src.execute(f"SELECT sha256 FROM {table(src_schema, t)} WHERE sha256 IS NOT NULL")}
    landed = 0
    for sha in sorted(shas):
        if not os.path.exists(path_for(sha)):          # a hash the old estate holds, not this store: copied later
            continue
        for name in names_of(sha, src) or [sha]:
            land(read_bytes(sha), name=name, source=SOURCE, conn=dst, name_kind="url" if name.startswith("http") else "file")
        landed += 1
    counts["documents re-landed"] = landed
    for k, v in counts.items():
        log(f"{SCHEMA}: adopted {k}: {v}")
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.council_minutes.capture")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof)")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--max-docs", type=int, default=100000)
    ap.add_argument("--copy-old", action="store_true", help="land the old estate's files present on this box")
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--adopt", metavar="SCRATCH_SCHEMA", help="the integrator, once: carry a session's capture record "
                    "from querynz_v4_sample into the live schema")
    a = ap.parse_args(argv)
    from support import db, jobrun
    if a.adopt:
        with db.connect(db.OWNER_KEY, "querynz_v4_sample") as src, db.connect(db.OWNER_KEY, a.database, autocommit=True) as dst:
            adopt(src, dst, a.adopt)
        return 0
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            return 0
        _, entries = land_listing(conn)
        if a.copy_old:
            got, aside = copy_all(conn, entries)
            print(f"{SOURCE}: {len(entries)} listed by the old estate, {len(got)} landed by hash, {len(aside)} not here")
            return 0
        out = Run(t, land_fn=landing(conn), old=old_held(entries), read_fn=read.recognise, anytime=a.anytime,
                  budget_s=a.budget_s, max_docs=a.max_docs, copy_old=copier(conn, entries)).run()
    ok, last = outcome(out)
    detail = (f"{out['requests']} requests, {out['listings']} listings, {out['landed']} minutes landed, "
              f"{out['already_held']} already held, {out['old_copied']} copied from the old estate's files, "
              f"{out['old_fetched']} of the old estate's fetched from the council ({out['old_fetched_differs']} not its "
              f"bytes), {out['old_estate']} held by the old estate, {out['failed']} failed, "
              f"{out['held_hosts']} instances held, {out['set_aside']} set aside; {last}")
    print(f"{SOURCE}: {detail}")
    if a.database == "querynz_v4":
        jobrun.record(JOB, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
