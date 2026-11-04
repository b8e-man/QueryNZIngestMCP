"""How this lane's documents arrive: case 3 of plan 1.10, through the fetch
gate and the landing wrapper only, each page or file once.

`listings.tsv` (this folder) is the survey's result: one line per council
listing page that links candidates' returns (council, the election years it
seeds, the address). A pass asks each listing page, lands it by hash, reads
it (`read.read_listing`) for the returns it links and the sub-listings it
names (a year's folder, a ward's page: followed up to `MAX_DEPTH`, same host
only), and records every return's address as wanted. The listings pass runs at most weekly and only off-peak. A files pass then asks
each wanted file that is not yet held, oldest election first (the 2019
returns' seven years under s 112F ran out on 12 October 2026, so a council
may take them down at any time), and lands it by hash. A return is HELD:
nothing here opens it (ruling 79).

Politeness (hard limit 7): one request at a time, at least `FLOOR_S` apart
to a host (the gate's own floor binds too), files only off-peak (22:00 to
06:00 NZ time) unless `--anytime`, a time budget per run. A 403, 429, 5xx or
challenge page is a failed read (hard limit 6): logged, never retried in
the run, and the host is not asked again in the run. A host the gate holds
(ruling 141: a 403 holds it until a person clears it) is asked nothing, and
the files wanted from it stay wanted rather than being spent as refused. Two transport failures
in a row end the host's run. A gate refusal is recorded and the host
skipped; it is never got around. A redirect to another host is not
followed unless the position names it (the gate judges each hop).

    python -m registers.local_elections.capture listings [--anytime] [--database D] [--schema S]
    python -m registers.local_elections.capture files [--anytime] [--budget-s N] [--max-files N]
    python -m registers.local_elections.capture adopt <capture-list.jsonl>   # the integrator: land from the store, no fetch
    python -m registers.local_elections.capture list > capture-list.jsonl    # what this database holds
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
from registers.local_elections import read

SOURCE = SCHEMA = "local_elections"
JOB_LISTINGS = "qv4-local-elections-listings"
JOB_FILES = "qv4-local-elections-files"
HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, "listings.tsv")
FLOOR_S = 5.0
OFF_PEAK = (22, 6)
DEFAULT_BUDGET_S = 7 * 3600
LISTINGS_EVERY_DAYS = 7
MAX_DEPTH = 2
MAX_PAGES_A_COUNCIL = 40
NZ = ZoneInfo("Pacific/Auckland")
#: until the integrator moves the position to docs/legal/positions/, a session runs with QV4_POSITIONS set
POSITIONS = os.environ.get("QV4_POSITIONS") or None
MAX_FILE_BYTES = 60 << 20
#: a redirect to one of these is a bot manager's challenge (Queenstown-Lakes to Radware's, 22 October 2026): blocked
CHALLENGE_HOSTS = ("perfdrive.com", "radware.com", "incapsula.com", "hcaptcha.com", "recaptcha.net", "challenges.cloudflare.com")


class FloorPacer(fg.Pacer):
    def wait(self, host: str, floor: float) -> float:
        return super().wait(host, max(floor, FLOOR_S))


PACER = FloorPacer()


def off_peak(t: dt.datetime) -> bool:
    h = t.astimezone(NZ).hour
    return h >= OFF_PEAK[0] or h < OFF_PEAK[1]


def table(schema: str, t: str) -> str:
    return f"{schema}.{t}" if schema == SCHEMA else f"{schema}.{SCHEMA}_{t}"


def seeds(path: str = SEEDS) -> list:
    """[(council, [years], url)] from listings.tsv; '#' lines are notes."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            council, years, url = line.rstrip("\n").split("\t")[:3]
            out.append((council.strip(), [int(y) for y in years.split(",") if y.strip()], url.strip()))
    return out


def council_words(council: str, url: str) -> tuple:
    host = (urllib.parse.urlsplit(url).hostname or "").split(".")
    return tuple(w for w in [host[1] if host[0] == "www" and len(host) > 1 else host[0]] + council.lower().split() if w)


class Tables:
    def __init__(self, conn, schema: str = SCHEMA):
        self.conn, self.schema = conn, schema

    def T(self, t):
        return table(self.schema, t)

    def create(self):
        with open(os.path.join(HERE, "tables.sql"), encoding="utf-8") as f:
            text = f.read().split("-- ── the reading")[0]
        if self.schema != SCHEMA:
            text = text.replace("CREATE SCHEMA IF NOT EXISTS local_elections;", f"CREATE SCHEMA IF NOT EXISTS {self.schema};")
            text = text.replace("local_elections.", f"{self.schema}.{SCHEMA}_")
        self.conn.execute(text)

    def try_lock(self) -> bool:
        return self.conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (self.T("capture"),)).fetchone()[0]

    def new_pass(self, mode: str) -> int:
        return self.conn.execute(f"INSERT INTO {self.T('capture_passes')} (mode) VALUES (%s) RETURNING pass_id",
                                 (mode,)).fetchone()[0]

    def end_pass(self, pid, requests, landed, failed, note):
        self.conn.execute(f"UPDATE {self.T('capture_passes')} SET finished_at = now(), requests = %s, landed = %s, "
                          f"failed = %s, note = %s WHERE pass_id = %s", (requests, landed, failed, note, pid))

    def page(self, pid, council, url, seed_year, depth, status, sha, state, why=None):
        self.conn.execute(
            f"INSERT INTO {self.T('capture_pages')} (pass_id, council, url, seed_year, depth, status, sha256, state, why) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (pid, council, url, seed_year, depth, status, sha, state, why))

    def want(self, council, url, listing_url, year) -> int:
        """1 when the file is new to the capture, 0 when it is already recorded."""
        return self.conn.execute(
            f"INSERT INTO {self.T('capture_files')} (url, council, listing_url, election_year, state) "
            f"VALUES (%s, %s, %s, %s, 'wanted') ON CONFLICT (url) DO NOTHING", (url, council, listing_url, year)).rowcount

    def not_linked(self, listing_url, urls) -> int:
        """A wanted file the page that named it no longer links (an address it moved, or one read wrongly before)
        is not asked: 'not linked', kept, never deleted."""
        return self.conn.execute(
            f"UPDATE {self.T('capture_files')} SET state = 'not linked', why = 'the listing no longer links it', "
            f"at = now() WHERE listing_url = %s AND state = 'wanted' AND NOT (url = ANY(%s))",
            (listing_url, list(urls))).rowcount

    def days_since_listings(self):
        r = self.conn.execute(f"SELECT max(finished_at) FROM {self.T('capture_passes')} WHERE mode = 'listings'").fetchone()
        if not r or r[0] is None:
            return None
        return (dt.datetime.now(dt.timezone.utc) - r[0]).total_seconds() / 86400

    def wanted(self) -> list:
        return [tuple(r) for r in self.conn.execute(
            f"SELECT url, council, election_year FROM {self.T('capture_files')} WHERE state = 'wanted' "
            f"ORDER BY election_year NULLS LAST, council, url")]

    def file(self, pid, url, status, sha, kind, size, state, why=None):
        self.conn.execute(
            f"UPDATE {self.T('capture_files')} SET pass_id = %s, status = %s, sha256 = %s, kind = %s, size = %s, "
            f"state = %s, why = %s, at = now() WHERE url = %s", (pid, status, sha, kind, size, state, why, url))


def fetch(url: str, max_bytes: int = None):
    """(Fetched or None, state, why)."""
    try:
        r = fg.open_url(url, timeout=60, positions_dir=POSITIONS, pacer=PACER, max_bytes=max_bytes)
    except fg.Refused as e:
        return None, "refused", str(e)[:300]
    except Exception as e:  # noqa: BLE001 — what the transport raises is a failed read too
        return None, "failed", f"{type(e).__name__}: {str(e)[:200]}"
    if r.blocked:
        return r, "blocked", r.blocked
    if r.status == 404 or r.status == 410:
        return r, "not found", f"HTTP {r.status}"
    if r.status in fg.REDIRECT_STATUSES and any(fg.host_of(r.location).endswith(h) for h in CHALLENGE_HOSTS):
        return r, "blocked", f"a redirect to a challenge ({fg.host_of(r.location)}); a challenged read is a failed read (hard limit 6)"
    if r.status in fg.REDIRECT_STATUSES:
        return r, "failed", f"HTTP {r.status} to {r.location} (another host: not followed)"
    if r.status != 200:
        return r, "failed", f"HTTP {r.status}"
    return r, "landed", None


class Run:
    def __init__(self, tables: Tables, land_fn, anytime=False, budget_s=DEFAULT_BUDGET_S, max_files=None,
                 fetch_fn=fetch, clock=None, log=print, seed_list=None, held_fn=None):
        self.t, self.land, self.anytime, self.budget_s = tables, land_fn, anytime, budget_s
        # the gate's hold on a host (ruling 141); an injected fetch is a test's site, never the live ledger's host
        self.held = held_fn or (fg.refused_by if fetch_fn is fetch else (lambda host: None))
        self.max_files, self.fetch, self.log = max_files, fetch_fn, log
        self.clock = clock or (lambda: dt.datetime.now(NZ))
        self.seed_list = seed_list
        self.requests = self.landed = self.failed = 0
        self.bad_hosts = {}
        self.t0 = time.monotonic()

    def _out_of_time(self):
        return time.monotonic() - self.t0 > self.budget_s

    def _ask(self, url, max_bytes=None):
        host = fg.host_of(url)
        if host in self.bad_hosts:
            return None, "skipped", f"host not asked again this run: {self.bad_hosts[host]}"
        if (held := self.held(host)) is not None:
            # ruling 141: a host the gate holds is asked nothing, and what is wanted from it stays wanted (no request
            # left the box; the gate's refusal is not an answer about the file), until a person clears the hold
            self.bad_hosts[host] = f"the fetch gate holds the host ({held})"
            return None, "skipped", self.bad_hosts[host]
        r, state, why = self.fetch(url, max_bytes)
        self.requests += 1
        if state in ("blocked", "refused"):
            self.bad_hosts[host] = why
        elif state == "failed" and r is None:
            self.bad_hosts[host] = self.bad_hosts.get(host) or None
            n = getattr(self, "_tf", {}).get(host, 0) + 1
            self._tf = {**getattr(self, "_tf", {}), host: n}
            if n >= 2:
                self.bad_hosts[host] = "two transport failures"
            else:
                self.bad_hosts.pop(host, None)
        if state != "landed":
            self.failed += 1
        return r, state, why

    def listings(self) -> dict:
        if not self.anytime:
            if not off_peak(self.clock()):
                self.log(f"{SOURCE}: outside 22:00 to 06:00 NZ time; no listing asked")
                return {"requests": 0, "landed": 0, "failed": 0, "stopped": "daytime"}
            since = self.t.days_since_listings() if hasattr(self.t, "days_since_listings") else None
            if since is not None and since < LISTINGS_EVERY_DAYS - 0.5:
                self.log(f"{SOURCE}: the last listings pass finished {since:.1f} days ago; none asked")
                return {"requests": 0, "landed": 0, "failed": 0, "stopped": "not due"}
        pid = self.t.new_pass("listings")
        rows, seen = 0, set()          # each page once a pass, though two seeds link it
        for council, years, url in (self.seed_list if self.seed_list is not None else seeds()):
            if self._out_of_time():
                break
            queue, asked_here = [(url, 0)], 0
            while queue and asked_here < MAX_PAGES_A_COUNCIL:
                u, depth = queue.pop(0)
                if u in seen:
                    continue
                seen.add(u)
                asked_here += 1
                r, state, why = self._ask(u)
                # the seed's one year is the seed page's own: a page it leads to (an archive, a ward) has its own
                seed_year = years[0] if len(years) == 1 and depth == 0 else None
                if state != "landed":
                    self.t.page(pid, council, u, seed_year, depth, r.status if r else None, None, state, why)
                    continue
                ref, _new = self.land(r.body, name=u, source=SOURCE, name_kind="url", content_type="text/html")
                self.landed += 1
                self.t.page(pid, council, u, seed_year, depth, r.status, ref.sha256, "landed")
                out = read.read_listing(r.body, u, council, seed_year, council_words(council, u))
                for row in out["rows"]:
                    if row["election_year"] is None or row["election_year"] >= read.WINDOW_FROM:
                        rows += self.t.want(council, row["file_url"], u, row["election_year"])
                if out["rows"]:     # a page that reads to nothing retires nothing: a reader at fault is not a move
                    self.t.not_linked(u, [row["file_url"] for row in out["rows"]])
                if depth < MAX_DEPTH:
                    queue += [(f, depth + 1) for f in out["follow"] if f not in seen and fg.host_of(f) == fg.host_of(u)]
        note = f"{rows} returns new to the capture"
        self.t.end_pass(pid, self.requests, self.landed, self.failed, note)
        return {"pass": pid, "requests": self.requests, "landed": self.landed, "failed": self.failed, "returns_new": rows}

    def files(self) -> dict:
        if not self.anytime and not off_peak(self.clock()):
            self.log(f"{SOURCE}: outside 22:00 to 06:00 NZ time; no file asked")
            return {"requests": 0, "landed": 0, "failed": 0, "stopped": "daytime"}
        pid = self.t.new_pass("files")
        stopped = ""
        for n, (url, council, year) in enumerate(self.t.wanted()):
            if self.max_files is not None and n >= self.max_files:
                stopped = f"max files {self.max_files}"
                break
            if self._out_of_time():
                stopped = "budget spent"
                break
            if not self.anytime and not off_peak(self.clock()):
                stopped = "06:00: off-peak ended"
                break
            r, state, why = self._ask(url, MAX_FILE_BYTES)
            if state == "skipped":
                continue
            if state == "landed" and len(r.body) >= MAX_FILE_BYTES:
                state, why = "too large", f"{MAX_FILE_BYTES >> 20} MB or more: not landed cut short"
            if state != "landed":
                self.t.file(pid, url, r.status if r else None, None, None, None, state, why)
                continue
            name = urllib.parse.unquote(url)
            ref, _new = self.land(r.body, name=name, source=SOURCE, name_kind="url", content_type="")
            self.landed += 1
            self.t.file(pid, url, r.status, ref.sha256, ref.kind, ref.size, "landed")
        note = stopped or "every wanted file asked"
        self.t.end_pass(pid, self.requests, self.landed, self.failed, note)
        return {"pass": pid, "requests": self.requests, "landed": self.landed, "failed": self.failed, "stopped": note}


def landing(conn):
    from support.docstore.landing import land

    def land_fn(data, *, name, source, name_kind, content_type):
        return land(data, name=name, source=source, conn=conn, name_kind=name_kind, content_type=content_type)
    return land_fn


def capture_list(conn, schema: str = SCHEMA):
    """Every page and file this database holds for the lane, one JSON line each: what `adopt` replays."""
    t = Tables(conn, schema)
    for r in conn.execute(f"SELECT DISTINCT ON (url) council, url, seed_year, depth, sha256 FROM {t.T('capture_pages')} "
                          f"WHERE state = 'landed' ORDER BY url, pass_id DESC"):
        yield {"what": "page", "council": r[0], "url": r[1], "seed_year": r[2], "depth": r[3], "sha256": r[4]}
    for r in conn.execute(f"SELECT council, url, listing_url, election_year, sha256, state, status, why "
                          f"FROM {t.T('capture_files')} ORDER BY url"):
        yield {"what": "file", "council": r[0], "url": r[1], "listing_url": r[2], "election_year": r[3],
               "sha256": r[4], "state": r[5], "status": r[6], "why": r[7]}


def adopt(conn, path: str, schema: str = SCHEMA, log=print) -> dict:
    """The integrator's step: what a session captured, landed into this database from the store's bytes, with no
    request to any host (each page or file once)."""
    from support.docstore.landing import land, read_bytes
    t = Tables(conn, schema)
    t.create()
    pid = t.new_pass("adopt")
    n = {"page": 0, "file": 0, "missing": 0}
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        sha = d.get("sha256")
        if sha:
            try:
                data = read_bytes(sha)
            except OSError:
                n["missing"] += 1
                continue
            land(data, name=d["url"], source=SOURCE, conn=conn, name_kind="url")
        if d["what"] == "page":
            t.page(pid, d["council"], d["url"], d["seed_year"], d["depth"], 200, sha, "landed")
        else:
            t.want(d["council"], d["url"], d["listing_url"], d["election_year"])
            if d["state"] != "wanted":
                t.file(pid, d["url"], d["status"], sha, None, None, d["state"], d["why"])
        n[d["what"]] += 1
    t.end_pass(pid, 0, n["page"] + n["file"], n["missing"], "adopted from a capture list")
    log(f"{SOURCE}: adopted {n['page']} pages, {n['file']} files; {n['missing']} hashes not in the store")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="registers.local_elections.capture")
    ap.add_argument("mode", choices=("listings", "files", "adopt", "list"))
    ap.add_argument("path", nargs="?")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak and the week guard (by hand: the survey, a proof)")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--max-files", type=int)
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=SCHEMA)
    a = ap.parse_args(argv)
    from support import db, jobrun
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if a.mode == "list":
            for d in capture_list(conn, a.schema):
                print(json.dumps(d, ensure_ascii=False))
            return 0
        if a.mode == "adopt":
            adopt(conn, a.path, a.schema)
            return 0
        if not t.try_lock():
            print(f"{SOURCE}: another run holds the lane; this one asks for nothing")
            return 0
        run = Run(t, land_fn=landing(conn), anytime=a.anytime, budget_s=a.budget_s, max_files=a.max_files)
        out = run.listings() if a.mode == "listings" else run.files()
    detail = ", ".join(f"{k} {v}" for k, v in out.items())
    print(f"{SOURCE}: {a.mode}: {detail}")
    ok = out.get("landed", 0) > 0 or out.get("stopped") in ("daytime", "not due") or out.get("requests", 0) == 0
    if a.database == "querynz_v4":
        jobrun.record(JOB_LISTINGS if a.mode == "listings" else JOB_FILES, ok, detail, started, out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
