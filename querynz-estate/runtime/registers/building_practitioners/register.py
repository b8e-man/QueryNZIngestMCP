"""The register of licensed building practitioners (`kete-lbp.mbie.govt.nz`):
its capture and its reading. Copied on ruling 132 (Arthur, 2 November
2026, "copy: Building practitioners register"), recorded as the position's
`authorised: register` line; without that line nothing here asks the
register anything.

The register answers a GET search with every match on one page, no paging:
a table of Full Name, Town/City, Region and Licensed?, each name linking to
the practitioner's page by the register's own id (`/practitioner/?id=<guid>`).
A search with no criterion is too heavy for it (it did not answer in 60 s,
2 November), so a pass asks it the seven licence classes and the nineteen
areas of practice, one at a time: 26 searches, the largest (Carpentry)
21,372 rows and 18 MB. A class search lists the class's current holders
only (with or without "include not currently licensed", 446 either way for
Foundations), so the copy is the current register; a practitioner who
holds no current class is not reached (a card).

Each practitioner's page gives the practitioner number, the names, the date
a class was first granted, the region and the town. The page also prints a
postcode, an email address and telephone numbers: read whole into the
private twin (`contacts`, ruling 142), never onto the lane's table. Its five
sub-tables (companies, qualifications, classes with dates, suspensions,
discipline) load by a POST the fetch gate does not make, and are not read
(a card); the classes come from the searches instead.

Politeness (hard limit 7): one request at a time, at least `capture.FLOOR_S`
apart (the host states no crawl delay: its robots file is a 404), off-peak
unless `--anytime`; the searches at most weekly; a practitioner's page
fetched once and again only after `REFRESH_DAYS`, and never when the
document store already holds it under its address (cached, so nothing is
fetched twice). A 403, 429 or challenge stops the run (hard limit 6); a
server's own 5xx is set aside and three failures in a row stop it.

Every line printed is a count.
"""
import datetime as dt
import html
import re
import urllib.parse

from registers.building_practitioners import capture

HOST = "kete-lbp.mbie.govt.nz"
SEARCH_URL = f"https://{HOST}/advanced-building-practitioner-search/"
DETAIL_URL = f"https://{HOST}/practitioner/?id="
CLASSES = ("Bricklaying and Blocklaying", "Carpentry", "Design", "External Plastering", "Foundations", "Roofing", "Site")
#: area of practice → its licence class (the register's own two lists, 2 November 2026)
AREAS = {
    "Design 1": "Design", "Design 2": "Design", "Design 3": "Design",
    "Site 1": "Site", "Site 2": "Site", "Site 3": "Site",
    "Concrete or Clay Tile Roof": "Roofing", "Profiled Metal Roof and/or Wall Cladding": "Roofing",
    "Metal Tile Roof": "Roofing", "Roof Membrane": "Roofing", "Torch on Roof Membrane": "Roofing",
    "Liquid Membrane Roof": "Roofing", "Shingle or Slate Roof": "Roofing",
    "Solid Plastering": "External Plastering", "Proprietary Plastering Cladding System": "External Plastering",
    "Concrete Foundation Walls and Concrete Slab-on-Ground": "Foundations",
    "Concrete or Timber Pile Foundations": "Foundations",
    "Veneer": "Bricklaying and Blocklaying", "Structural Masonry": "Bricklaying and Blocklaying",
}
QUERIES = tuple([("lclass", c) for c in CLASSES] + [("aop", a) for a in AREAS])
LIST_EVERY_DAYS = 7
REFRESH_DAYS = 90
LIST_TIMEOUT_S = 300
DETAIL_TIMEOUT_S = 60
PROFILE_LIST = "lbp-register-search-page"
PROFILE_DETAIL = "lbp-register-practitioner-page"
READER = "registers.building_practitioners.register 1"
KEY_PREFIX = "building_practitioners/lbp"
NZ = capture.NZ

_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ROW = re.compile(r'<tr>\s*<td>\s*<a href="/practitioner/\?id=(' + _GUID + r')">(.*?)</a>\s*</td>\s*<td>(.*?)</td>\s*'
                  r'<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', re.S)
_TBODY = re.compile(r'<table id="data"[^>]*class="table table-striped table-fluid">.*?<tbody[^>]*>(.*?)</tbody>', re.S)
_HEADS = ("Full Name", "Town/City", "Region", "Licensed?")
_SELECT = r'<select name="{}"[^>]*>(.*?)</select>'
_SELECTED = re.compile(r'<option selected value="([^"]*)"')
_ENTITY = re.compile(r'_EntityFormView_EntityID" value="(' + _GUID + r')"')
#: the fields read from a practitioner's page onto the lane's table; the postcode, email, phones, fax and website beside
#: them (`CONTACT_FIELDS`) are read into the private twin (ruling 142)
FIELDS = {"first": "firstname", "middle": "middlename", "last": "lastname", "number": "olp_practitionerid",
          "first_granted": "olp_datefirstgranted", "region": "olp_address1_regionalcouncil", "town": "address1_city"}
CONTACT_FIELDS = ("address1_postalcode", "olp_primaryemailpr", "olp_mobilenumberpr", "olp_daytimephonepr",
                  "olp_eveningphonepr", "olp_faxpr", "websiteurl")
_NUMBER = re.compile(r"[A-Z]{1,3}\d{4,8}")
#: a town that names an address by its shape (ruling 102), measured on the register's 21,372 Carpentry towns
#: (2 November 2026): a street address, a street word, a rural delivery number, a box or bag. Postcodes typed
#: into the town (about 120) are not addresses and are not flagged.
_STREET_WORD = (r"Street|St|Road|Rd|Avenue|Ave|Terrace|Tce|Drive|Dr|Place|Pl|Crescent|Cres|Lane|Ln|Way|Grove|Quay|"
                r"Highway|Hwy|Parade|Square|Sq|Esplanade|Rise|Close|Boulevard|Blvd|Mews|Court|Ct")
ADDRESS_SHAPE = re.compile(r"\b(?:" + _STREET_WORD + r")\b\.?(?!\w)|\bR\.?\s?D\.?\s*\d|\bp\.?\s*o\.?\s*box\b|"
                           r"\bprivate\s+bag\b|\b\d{1,5}[A-Za-z]?\s+[A-Z][a-z]+\s+(?:" + _STREET_WORD + r")\b", re.I)


def versions() -> dict:
    """{profile slug: version} for the register's two page profiles (the ledger, else the lane's proposal)."""
    import os
    from support import profiles
    proposed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile-proposed.jsonl")
    out = {}
    for slug in (PROFILE_LIST, PROFILE_DETAIL):
        p = profiles.profile(slug) or profiles.profile(slug, path=proposed)
        if p is None:
            raise LookupError(f"no profile {slug}: a reading is made from a profile (profiles before readers)")
        out[slug] = int(p["version"])
    return out


# ── pure pieces ───────────────────────────────────────────────────────────────

def search_url(field: str, value: str) -> str:
    return SEARCH_URL + "?" + urllib.parse.urlencode({field: value})


def detail_url(guid: str) -> str:
    return DETAIL_URL + guid


def clean(s):
    if s is None:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def names_address(v) -> bool:
    return bool(v and ADDRESS_SHAPE.search(v))


def read_list(body: bytes):
    """({'query': (field, value), 'rows': [{guid, town, region, licensed}]}, '') or (None, why). The name a row
    shows is not kept: the practitioner's page gives the names."""
    try:
        t = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not UTF-8 text"
    heads = re.findall(r"<th[^>]*>(.*?)</th>", t, re.S)
    if [clean(h) for h in heads[-4:]] != list(_HEADS):
        return None, "no results table headed Full Name, Town/City, Region, Licensed?"
    query = []
    for field in ("lclass", "aop"):
        m = re.search(_SELECT.format(field), t, re.S)
        sel = _SELECTED.search(m.group(1)) if m else None
        if sel:
            query.append((field, html.unescape(sel.group(1))))
    if len(query) != 1:
        return None, f"{len(query)} search criteria selected on the page; a pass asks one"
    tb = _TBODY.search(t)
    if not tb:
        return None, "no results table body"
    rows = _ROW.findall(tb.group(1))
    if tb.group(1).count("<tr") != len(rows):
        return None, f"the table holds {tb.group(1).count('<tr')} rows and {len(rows)} read"
    return {"query": query[0], "rows": [{"guid": g, "town": clean(town), "region": clean(region),
                                         "licensed": clean(lic)} for g, _name, town, region, lic in rows]}, ""


def _value(t: str, field: str):
    m = re.search(r'<input[^>]*\bid="' + field + r'"[^>]*>', t)
    if not m:
        return None, False
    v = re.search(r'\bvalue="([^"]*)"', m.group(0))
    return (clean(v.group(1)) if v else None), True


def nz_day(v):
    """The register's UTC instant ('2012-03-14T11:00:00.0000000Z') as the New Zealand day it is."""
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z", v or "")
    if not m:
        return None
    t = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}+00:00")
    return t.astimezone(NZ).date()


def read_detail(body: bytes):
    """({guid, number, first, middle, last, first_granted, region, town}, '') or (None, why)."""
    try:
        t = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not UTF-8 text"
    if "Practitioner Details" not in t:
        return None, "no Practitioner Details section"
    g = _ENTITY.search(t)
    if not g:
        return None, "no record id on the page"
    out = {"guid": g.group(1)}
    for k, field in FIELDS.items():
        v, present = _value(t, field)
        if not present:
            return None, f"no {field} field"
        out[k] = v
    if not out["number"] or not _NUMBER.fullmatch(out["number"].replace(" ", "")):
        return None, "no practitioner number of the register's shape"
    out["number"] = out["number"].replace(" ", "")
    raw = out["first_granted"]
    out["first_granted"] = nz_day(raw)
    if raw and out["first_granted"] is None:
        return None, "a first-granted date that is not the register's instant"
    if not (out["first"] or out["last"]):
        return None, "no name"
    out["contacts"] = [(f, v) for f, v in ((f, _value(t, f)[0]) for f in CONTACT_FIELDS) if v]
    return out, ""


def classes_of(listed: dict) -> dict:
    """guid → [{'class', 'areas'}] from the pass's searches: a class search names the class, an area search its
    area and, through `AREAS`, its class."""
    out = {}
    for (field, value), rows in listed.items():
        cls = value if field == "lclass" else AREAS.get(value)
        for r in rows:
            d = out.setdefault(r["guid"], {})
            areas = d.setdefault(cls, set())
            if field == "aop":
                areas.add(value)
    return {g: [{"class": c, "areas": sorted(a)} for c, a in sorted(d.items())] for g, d in out.items()}


def row(detail: dict, sha: str, classes: list, listed: bool, versions: dict) -> dict:
    name = " ".join(x for x in (detail["first"], detail["middle"], detail["last"]) if x)
    return {"key": f"{KEY_PREFIX}/{detail['number']}", "licence_number": detail["number"], "name": name,
            "first_name": detail["first"], "middle_names": detail["middle"], "last_name": detail["last"],
            "suppressed": False, "licence_classes": classes,
            "status": "licensed" if listed else "not on the current listing",
            "area": detail["town"], "area_names_address": names_address(detail["town"]), "region": detail["region"],
            "first_granted_on": detail["first_granted"], "register_url": detail_url(detail["guid"]),
            "register_id": detail["guid"], "contacts": detail.get("contacts") or [],
            "document": sha, "page": 1, "place": f"practitioner={detail['number']}", "read_from": "text",
            "reader": READER, "profile": PROFILE_DETAIL, "profile_version": versions[PROFILE_DETAIL]}


def plan(open_pass, last_done, now: dt.datetime) -> str:
    if open_pass is not None:
        return "resume"
    if last_done is None or now - last_done >= dt.timedelta(days=LIST_EVERY_DAYS):
        return "full"
    return "details"


def due(guids, fetched: dict, now: dt.datetime) -> list:
    """The practitioners whose page is to be asked for: never fetched first, then the stalest past REFRESH_DAYS."""
    never = sorted(g for g in guids if g not in fetched)
    stale = sorted((fetched[g], g) for g in guids if g in fetched and now - fetched[g] >= dt.timedelta(days=REFRESH_DAYS))
    return never + [g for _, g in stale]


# ── the capture's tables ──────────────────────────────────────────────────────

class Tables(capture.Tables):
    def reg_open_pass(self):
        r = self.conn.execute(f"SELECT pass_id, next_query FROM {self.s}.capture_register_passes WHERE finished_at IS NULL "
                              "ORDER BY pass_id DESC LIMIT 1").fetchone()
        return None if r is None else {"pass_id": r[0], "next_query": r[1]}

    def reg_last_done(self):
        r = self.conn.execute(f"SELECT max(finished_at) FROM {self.s}.capture_register_passes").fetchone()
        return r[0] if r else None

    def reg_begin(self) -> dict:
        pid = self.conn.execute(f"INSERT INTO {self.s}.capture_register_passes DEFAULT VALUES RETURNING pass_id").fetchone()[0]
        return {"pass_id": pid, "next_query": 0}

    def reg_add_list(self, p, n, field, value, url, sha, rows, new):
        self.conn.execute(f"INSERT INTO {self.s}.capture_register_lists (pass_id, query_no, field, value, url, sha256, "
                          "rows, new) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (p["pass_id"], n, field, value, url, sha, rows, new))
        self.conn.execute(f"UPDATE {self.s}.capture_register_passes SET next_query = %s, lists = lists + 1, rows = rows + %s "
                          "WHERE pass_id = %s", (n + 1, rows, p["pass_id"]))
        p["next_query"] = n + 1

    def reg_finish(self, p):
        self.conn.execute(f"UPDATE {self.s}.capture_register_passes SET finished_at = now() WHERE pass_id = %s", (p["pass_id"],))

    def reg_lists(self):
        """The newest pass's searches with a page landed (a pass in progress included): [(sha256, field, value)]."""
        r = self.conn.execute(f"SELECT max(pass_id) FROM {self.s}.capture_register_lists").fetchone()
        if not r or r[0] is None:
            return []
        return [tuple(x) for x in self.conn.execute(f"SELECT sha256, field, value FROM {self.s}.capture_register_lists "
                                                    "WHERE pass_id = %s ORDER BY query_no", (r[0],))]

    def reg_fetched(self) -> dict:
        return {g: t for g, t in self.conn.execute(f"SELECT guid, max(fetched_at) FROM {self.s}.capture_register_details "
                                                    "GROUP BY guid")}

    def reg_add_detail(self, guid, url, sha, new, fetched_at=None):
        self.conn.execute(f"INSERT INTO {self.s}.capture_register_details (guid, url, sha256, new, fetched_at) "
                          "VALUES (%s, %s, %s, %s, coalesce(%s, now())) ON CONFLICT DO NOTHING", (guid, url, sha, new, fetched_at))

    def reg_adopt(self, guid, url) -> bool:
        """A practitioner's page the document store already holds under its address (another schema's run landed
        it): recorded here, not fetched again."""
        from support.docstore import landing
        shas = landing.find_by_name(url, self.conn)
        if not shas:
            return False
        names = landing.names_for(self.conn, shas)
        newest = max(names, key=lambda n: (n[3] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)))
        self.reg_add_detail(guid, url, newest[0], False, newest[3])
        return True


# ── a run ─────────────────────────────────────────────────────────────────────

class Run(capture.Run):
    def __init__(self, tables, *, max_details: int = 100000, read_bytes=None, adopt: bool = True, **kw):
        kw.setdefault("max_pages", 10 ** 9)
        super().__init__(tables, **kw)
        self.max_details, self.adopt = max_details, adopt
        if read_bytes is None:
            from support.docstore.landing import read_bytes
        self.read_bytes = read_bytes
        self.counts.update({"searches": 0, "listed": 0, "details": 0, "adopted": 0, "due": 0, "passes_finished": 0})

    def lists(self, p):
        while p["next_query"] < len(QUERIES):
            if not self.time_left():
                return False
            n = p["next_query"]
            field, value = QUERIES[n]
            url = search_url(field, value)
            f = self.get(url, p["pass_id"], timeout=LIST_TIMEOUT_S)
            if f is None:
                raise capture.Stop(f"a search failed; the pass resumes from search {n + 1} of {len(QUERIES)} next run")
            out, why = read_list(f.body)
            if out is None or out["query"] != (field, value):
                self._aside(p["pass_id"], url, "parse", why or "the page answers another search")
                raise capture.Stop("a search page could not be trusted")
            ref, new = self._land(f.body, url)
            self.t.reg_add_list(p, n, field, value, url, ref.sha256, len(out["rows"]), new)
            self.counts["searches"] += 1
            self.counts["listed"] += len(out["rows"])
        self.t.reg_finish(p)
        self.counts["passes_finished"] += 1
        self.log(f"{capture.SOURCE}: register pass {p['pass_id']} listed: {len(QUERIES)} searches")
        return True

    def details(self):
        guids = set()
        for sha, _field, _value in self.t.reg_lists():
            out, _ = read_list(self.read_bytes(sha))
            guids |= {r["guid"] for r in (out or {}).get("rows", [])}
        todo = due(guids, self.t.reg_fetched(), self.now())
        self.counts["due"] = len(todo)
        unread = 0
        for guid in todo:
            if self.counts["details"] >= self.max_details or not self.time_left():
                return
            url = detail_url(guid)
            if self.adopt and self.t.reg_adopt(guid, url):
                self.counts["adopted"] += 1
                continue
            f = self.get(url, None, timeout=DETAIL_TIMEOUT_S)
            if f is None:
                continue
            out, why = read_detail(f.body)
            if out is None or out["guid"] != guid:
                self._aside(None, url, "parse", why or "the page is another practitioner's")
                unread += 1
                if unread >= capture.STOP_AFTER_FAILURES:
                    raise capture.Stop(f"{unread} practitioner pages in a row not of the register's shape")
                continue
            unread = 0
            ref, new = self._land(f.body, url)
            self.t.reg_add_detail(guid, url, ref.sha256, new)
            self.counts["details"] += 1

    def run(self) -> dict:
        try:
            p = self.t.reg_open_pass()
            what = plan(p, self.t.reg_last_done(), self.now())
            if what == "full":
                p = self.t.reg_begin()
            listed = self.lists(p) if p is not None else True
            if listed:
                self.details()
        except capture.Stop as exc:
            self.stopped = f"stopped: {exc}"
        return {**self.counts, "stopped": self.stopped}


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="registers.building_practitioners.register")
    ap.add_argument("--anytime", action="store_true", help="outside off-peak (by hand: a proof or a first night)")
    ap.add_argument("--max-details", type=int, default=100000)
    ap.add_argument("--budget-s", type=float, default=27000)
    ap.add_argument("--database", default="querynz_v4")
    ap.add_argument("--schema", default=capture.SCHEMA)
    a = ap.parse_args(argv)
    try:
        capture.register()
    except capture.Held as exc:
        print(f"{capture.SOURCE}: {exc}")
        return 0
    from support import db, jobrun
    started = jobrun.now()
    with db.connect(db.OWNER_KEY, a.database, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '60s'")
        t = Tables(conn, a.schema)
        t.create()
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (JOB,)).fetchone()[0]:
            print(f"{capture.SOURCE}: another run holds the register; this one asks for nothing")
            return 0
        out = Run(t, land_fn=capture.landing(conn), anytime=a.anytime, max_details=a.max_details,
                  budget_s=a.budget_s).run()
    ok = not out["stopped"].startswith("stopped:")
    detail = (f"{out['requests']} requests, {out['searches']} searches ({out['listed']} rows), {out['due']} pages due, "
              f"{out['details']} fetched, {out['adopted']} already held, {out['new']} new, {out['set_aside']} set aside; "
              f"{out['stopped'] or 'done'}")
    print(f"{capture.SOURCE}: register: {detail}")
    if a.database == "querynz_v4" and a.schema == capture.SCHEMA:
        jobrun.record(JOB, ok, detail, started, out)
    sys.stdout.flush()
    return 0 if ok else 1


JOB = "qv4-building-practitioners-register-capture"

if __name__ == "__main__":
    import sys
    sys.exit(main())
