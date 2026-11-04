"""The reading: each landed document, recognised by its shape under a profile,
into one row per grant and one per recipient as published, each stamped with
its reader, its profile and version, and read from text. Nothing here calls a
model, and nothing here looks a recipient up anywhere.

Two layouts are read (more are carded by class in docs/status/grants.md):

  dia-class4-grants-csv        the Department of Internal Affairs' national
                               file of class 4 grants, "Grants from Gaming
                               Machine Profits" (CC BY 4.0): one record per
                               application a society approved, declined or
                               refunded, as the society reported it to the
                               Department. Recognised by its header line
  lottery-record-of-grants-page  a Community Matters page headed "<year>
                               round <n> Lottery <committee> record of grants"
                               with one table, Name | Amount; an asterisk on
                               an amount marks a multi-year grant, as the
                               page's own footnote says. Recognised by its
                               heading and its table's head

A grant row carries two publishers: `publisher_key`, who published the
document (the Department), and `grantor_key`, who made the grant (the society
or the Lottery committee). The recipient is kept exactly as printed, with the
business number and charity number only where the publisher prints a valid
one. A recipient that no organisation word, business number or charity number
shows to be an organisation is kept as printed and marked so; it is never
looked up (hard limit 15: no address is read, and none is printed by these
layouts).

Items in equal items out plus items set aside, document by document: every
record is a grant row or a catch-log line, and a reading that does not
reconcile raises.

    recognise(data)                    the profile slug, or None
    read_document(data, sha, name)     Reading
    recipients(grants)                 one row per recipient as published, per grantor
"""
import collections
import csv
import datetime as dt
import hashlib
import html
import io
import os
import re
from dataclasses import dataclass, field

from keys.dates import filed_date
from keys.names import is_organisation
from keys.numbers import charity_number, nzbn as nzbn_ok
from support import profiles

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profiles-proposed.jsonl")
READER = "registers.grants.read 1"
DIA_CSV = "dia-class4-grants-csv"
LOTTERY_PAGE = "lottery-record-of-grants-page"
WINDOW_FROM = 2017      # ruling 71: the window is 2017 on
SCAN_WORDS = 60         # a PDF carrying fewer words than this on its text layer is a scan
EXCEL_EPOCH = dt.date(1899, 12, 30)

#: the publishers this lane knows: key → (name, kind, website, licence, attribution). The societies are the
#: Department's own list (granted.govt.nz, 21 October 2026: 31 societies with their sites), with the societies the
#: national file names that the list no longer carries; `NAME_FORMS` maps every form the file prints to its key.
DIA = "dia"
LOTTERY = "lottery-grants-board"
CC_BY_4 = "CC BY 4.0"
DIA_ATTRIBUTION = ("Source: Te Tari Taiwhenua Department of Internal Affairs, Grants from Gaming Machine Profits "
                   "(class 4 grants data), licensed under CC BY 4.0")
LOTTERY_ATTRIBUTION = ("Source: Te Tari Taiwhenua Department of Internal Affairs, Community Matters, Te Puna Tahua "
                       "Lottery Grants Board record of grants, licensed under CC BY 4.0")
#: a society's own list carries no licence the survey saw: its facts are read and cited, its words quoted, under the
#: position docs/legal/positions/class-4-society-grant-publications.md (a lawyer confirms before anything is sold)
SOCIETY_LICENCE = "none stated: facts read and cited under the position class-4-society-grant-publications"
SOCIETIES = {
    # key: (name as the Department's list prints it, website as listed, on the list of 21 October 2026)
    "air-rescue-services": ("Air Rescue Services Limited", "https://www.airrescueservices.co.nz", True),
    "akarana-community-trust": ("The Akarana Community Trust Limited", "https://www.akaranacommunitytrust.co.nz", True),
    "aotearoa-gaming-foundation": ("Aotearoa Gaming Foundation", None, False),
    "aotearoa-gaming-trust": ("Aotearoa Gaming Trust", "https://www.agt.nz", True),
    "bendigo-valley": ("The Bendigo Valley Sports and Charity Foundation", None, False),
    "blue-sky-community-trust": ("Bluesky Community Trust Limited", "https://www.bluesky.org.nz", True),
    "blue-waters-community-trust": ("Blue Waters Community Trust", None, False),
    "constellation-communities-trust": ("Constellation Communities Trust Limited", "http://constellationtrust.org.nz/", True),
    "dragon-community-trust": ("Dragon Community Trust Limited", "https://www.dragon.org.nz", True),
    "first-light-community-foundation": ("First Light Community Foundation Limited", "https://www.firstlightfoundation.co.nz", True),
    "four-winds-foundation": ("Four Winds Foundation Limited", "https://www.fourwindsfoundation.co.nz/MCCFCT", True),
    "grassroots-trust-central": ("Grassroots Trust Central Limited", "https://www.grassrootstrustcentral.co.nz/", True),
    "grassroots-trust": ("Grassroots Trust Limited", "https://www.grassrootstrust.co.nz", True),
    "ilt-foundation": ("ILT Foundation", "https://www.iltfoundation.org.nz", True),
    "kaiwaka-sports-association": ("Kaiwaka Sports Association Incorporated", None, False),
    "kiwi-gaming-foundation": ("Kiwi Gaming Foundation", "https://www.kiwigaming.org.nz", True),
    "lion-foundation": ("The Lion Foundation 2008", "https://lionfoundation.nz", True),
    "mainland-foundation": ("Mainland Foundation Limited", "https://www.mainlandfoundation.co.nz", True),
    "manukau-counties-community-facilities": ("Manukau Counties Community Facilities Charitable Trust", "https://www.fourwindsfoundation.co.nz/MCCFCT", True),
    "milestone-foundation": ("Milestone Foundation Limited", "http://www.milestonefoundation.co.nz", True),
    "mt-wellington": ("Mt Wellington", None, False),
    "new-horizon-community-trust": ("New Horizon Community Trust Limited", "https://www.newhorizoncommunitytrust.co.nz/", True),
    "nz-community-trust": ("New Zealand Community Trust", "https://www.nzct.org.nz", True),
    "one-foundation": ("One Foundation Limited", "https://www.onefoundation.nz/", True),
    "oxford-sports-trust": ("Oxford Sports Trust Inc", "http://www.oxfordsportstrust.org.nz", True),
    "pelorus-trust": ("Pelorus Trust", "https://www.pelorustrust.net.nz", True),
    "pub-charity": ("Pub Charity Limited", "https://www.pubcharitylimited.org.nz", True),
    "rano-community-trust": ("Rano Community Trust Limited", "https://rano.org.nz/", True),
    "redwood-trust": ("Redwood Trust Incorporated", "http://www.redwoodtrust.org.nz", True),
    "tab-new-zealand": ("TAB New Zealand", None, False),
    "north-and-south-trust": ("The North and South Trust Limited", "https://www.nstl.co.nz", True),
    "trusts-community-foundation": ("The Trusts Community Foundation Limited", "https://www.ttcfltd.org.nz", True),
    "trillian-trust": ("Trillian Trust Limited", "https://www.trillian.nz", True),
    "trust-aoraki": ("Trust Aoraki Limited", "https://www.trustaoraki.co.nz", True),
    "trust-house-foundation": ("Trust House Foundation", "https://trusthouse.co.nz", True),
    "we-care-community-trust": ("We Care Community Trust Limited", "https://wecare.org.nz", True),
    "youthtown": ("Youthtown Incorporated", "https://youthtownfunding.org.nz/", True),
}
#: every society name form the national file prints (21 October 2026: 47 forms), folded, → its key
NAME_FORMS = {
    "air rescue services": "air-rescue-services", "akarana community trust": "akarana-community-trust",
    "aotearoa gaming foundation": "aotearoa-gaming-foundation", "aotearoa gaming trust": "aotearoa-gaming-trust",
    "bendigo valley sports and charity foundation": "bendigo-valley",
    "blue sky community trust": "blue-sky-community-trust", "bluesky community trust": "blue-sky-community-trust",
    "blue waters community trust": "blue-waters-community-trust",
    "constellation communities trust": "constellation-communities-trust",
    "dragon community trust": "dragon-community-trust",
    "first light community foundation": "first-light-community-foundation",
    "four winds foundation": "four-winds-foundation", "grassroots trust central": "grassroots-trust-central",
    "grassroots trust": "grassroots-trust", "ilt foundation": "ilt-foundation",
    "kaiwaka sports association": "kaiwaka-sports-association", "kiwi gaming foundation": "kiwi-gaming-foundation",
    "lion foundation": "lion-foundation", "lion foundation 2008": "lion-foundation",
    "mainland foundation": "mainland-foundation",
    "manukau community facilities charitable trust": "manukau-counties-community-facilities",
    "manukau counties community facilities charitable trust": "manukau-counties-community-facilities",
    "milestone foundation": "milestone-foundation", "mt wellington": "mt-wellington",
    "new horizon community trust": "new-horizon-community-trust", "new zealand community trust": "nz-community-trust",
    "one foundation": "one-foundation", "oxford sports trust": "oxford-sports-trust", "pelorus trust": "pelorus-trust",
    "pub charity": "pub-charity", "rano community trust": "rano-community-trust", "redwood trust": "redwood-trust",
    "tab new zealand": "tab-new-zealand", "north and south trust": "north-and-south-trust",
    "trusts community foundation": "trusts-community-foundation", "trillian trust": "trillian-trust",
    "trust aoraki": "trust-aoraki", "trust house foundation": "trust-house-foundation",
    "we care community trust": "we-care-community-trust", "wecare community trust": "we-care-community-trust",
    "youthtown": "youthtown",
}
_SUFFIX = re.compile(r"\b(limited|ltd|incorporated|inc)\.?$")


def society_key(name: str):
    """The key of the society a name form names, or None (the record is set aside, never guessed)."""
    s = re.sub(r"\s+", " ", (name or "").strip().lower())
    s = re.sub(r"^the ", "", s)
    for _ in range(2):
        s = _SUFFIX.sub("", s).strip()
    return NAME_FORMS.get(s)


def publishers() -> list:
    """One row per publisher or grantor: the Department, the Lottery Grants Board, and every society."""
    out = [{"key": DIA, "name": "Te Tari Taiwhenua Department of Internal Affairs", "kind": "government department",
            "website": "https://www.dia.govt.nz", "on_departments_list": None, "licence": CC_BY_4,
            "attribution": DIA_ATTRIBUTION,
            "role": "publishes the national file of class 4 grants and the Lottery records of grants"},
           {"key": LOTTERY, "name": "Te Puna Tahua Lottery Grants Board", "kind": "statutory board",
            "website": "https://www.communitymatters.govt.nz/lottery-grants-board", "on_departments_list": None,
            "licence": CC_BY_4, "attribution": LOTTERY_ATTRIBUTION,
            "role": "makes Lottery grants through its committees (Gambling Act 2003, Part 4)"}]
    for k, (name, site, listed) in sorted(SOCIETIES.items()):
        out.append({"key": k, "name": name, "kind": "class 4 society", "website": site, "on_departments_list": listed,
                    "licence": SOCIETY_LICENCE, "attribution": f"Source: {name}, its own list of grants approved and "
                                                               "declined (Gambling Act 2003, s 110(4))",
                    "role": "makes class 4 grants from gaming machine proceeds (Gambling Act 2003, s 110(4): "
                            "publishes its grants at least annually)"})
    return out


@dataclass
class Reading:
    slug: str = None
    version: int = None
    grants: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)
    records: int = 0
    stated: dict = field(default_factory=dict)      # what the document states of itself (a count, a total)
    notes: collections.Counter = field(default_factory=collections.Counter)


def profile(slug: str) -> dict:
    """The ledger's newest version; until the integrator appends them, the lane's proposed lines."""
    p = profiles.profile(slug) or profiles.profile(slug, path=PROPOSED)
    if p is None:
        raise LookupError(f"no document profile {slug}")
    return p


# ── recognition, by shape ─────────────────────────────────────────────────────

def _first_line(data: bytes) -> list:
    line = data[:4096].split(b"\n", 1)[0].rstrip(b"\r").decode("utf-8-sig", "replace")
    try:
        return next(csv.reader([line]), [])
    except csv.Error:          # not a CSV (a file a society walk landed): no header
        return []


_H1 = re.compile(r"<h1[^>]*>(?P<h>(?:(?!<h1).)*?)</h1>", re.S | re.I)
_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t([dh])\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", fragment or ""))).strip()


def headings(page: str) -> list:
    return [t for t in (text_of(m.group("h")) for m in _H1.finditer(page)) if t]


def recognise(data: bytes):
    """The slug of the profile whose shape the document has, or None."""
    if data.startswith(b"%PDF"):
        from registers.grants import society
        return society.recognise(data)
    if _first_line(data) == profile(DIA_CSV)["recognise"]["header_exact"]:
        return DIA_CSV
    head = data[:600000].decode("utf-8", "replace")
    if "<html" not in head[:2000].lower():
        return None
    r = profile(LOTTERY_PAGE)["recognise"]
    if not any(re.search(r["heading_pattern"], h, re.I) for h in headings(head)):
        return None
    tables = _TABLE.findall(head)
    for t in tables:
        rows = _ROW.findall(t)
        if rows and [text_of(c[1]) for c in _CELL.findall(rows[0])] == r["table_head"]:
            return LOTTERY_PAGE
    return None


# ── the Department's national file ────────────────────────────────────────────

def decode_field(raw: bytes, notes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        notes["a field read as Windows-1252"] += 1
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            notes["a field read as Latin-1"] += 1
            return raw.decode("latin-1")


def records(data: bytes, notes) -> tuple:
    """(header, [(record no, {column: value})]): the CSV parsed as bytes, each field decoded on its own."""
    text = data.decode("latin-1")          # one byte, one character: the CSV's structure survives any encoding
    if text.startswith("ï»¿"):
        text = text[3:]
    rows = csv.reader(io.StringIO(text, newline=""))
    header = [decode_field(h.encode("latin-1"), notes) for h in next(rows)]
    out = []
    for i, r in enumerate(rows, 1):
        out.append((i, [decode_field(f.encode("latin-1"), notes) for f in r]))
    return header, out


_AMOUNT = re.compile(r"^-?\d+(?:\.\d{1,2})?$")


def amount(raw: str):
    s = (raw or "").strip().replace(",", "").lstrip("$")
    if not s or s.upper() == "NULL" or not _AMOUNT.match(s):
        return None
    return float(s)


def a_date(raw: str, notes, what: str):
    """A date as published: d/mm/yyyy (day first), or a spreadsheet day number (counted)."""
    s = (raw or "").strip()
    if not s or s.upper() == "NULL":
        return None
    if re.fullmatch(r"\d{5}", s):
        notes[f"{what}: a spreadsheet day number"] += 1
        return EXCEL_EPOCH + dt.timedelta(days=int(s))
    d = filed_date(s) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s) else None
    if d is None:
        notes[f"{what}: not a date, kept as published"] += 1
    return d


def blank(s):
    s = (s or "").strip()
    return None if not s or s.upper() == "NULL" else s


def recipient_kind(name: str, nzbn, cc) -> str:
    if nzbn or cc:
        return "organisation (a number printed)"
    if is_organisation(name or ""):
        return "organisation (by its name)"
    return "not shown to be an organisation"


def read_dia_csv(data: bytes, sha: str, only=None) -> Reading:
    """`only`: the record numbers to read (the sample's `key: dia N` lines); None reads every record."""
    p = profile(DIA_CSV)
    out = Reading(DIA_CSV, int(p["version"]))
    header, recs = records(data, out.notes)
    if header != p["recognise"]["header_exact"]:
        raise ValueError("the header is not the profile's")
    if only is not None:
        recs = [(n, f) for n, f in recs if n in only]
    out.records = len(recs)
    width = len(header)
    for n, f in recs:
        place = f"record {n}"
        if len(f) != width:
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": f"{len(f)} fields, not {width}"})
            continue
        g = dict(zip(header, f))
        soc = society_key(g["Society_Name"])
        if soc is None:
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": "the society named is not on the lane's list of name forms"})
            continue
        name = blank(g["Organisation_Name"])
        if name is None:
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": "no recipient named"})
            continue
        year = blank(g["Year_of_Accept/Decline"])
        decided = a_date(g["Date_of_Accept/Decline"], out.notes, "decision date")
        if year is None or not re.fullmatch(r"\d{4}", year):
            out.set_aside.append({"document": sha, "place": place, "stage": "read", "reason": "no year of decision"})
            continue
        if int(year) < WINDOW_FROM:
            out.notes["before the window (ruling 71), not read"] += 1
            out.set_aside.append({"document": sha, "place": place, "stage": "window",
                                  "reason": f"decided in {year}, before {WINDOW_FROM} (ruling 71)"})
            continue
        nz_pub = blank(g["Organisation_NZBN"])
        cc_pub = blank(g["Organisation_Charities_Registration_Number"])
        nz = nzbn_ok(nz_pub) if nz_pub and re.fullmatch(r"\d{13}", nz_pub) else None
        if nz_pub and nz is None:
            out.notes["a business-number field that is not a valid NZBN, kept as published"] += 1
        cc = charity_number(cc_pub) if cc_pub and re.fullmatch(r"(?i)cc\s*\d{5,6}", cc_pub) else None
        if cc_pub and cc is None:
            out.notes["a charity-number field that is not a charity number, kept as published"] += 1
        status = g["Status"].strip()
        granted = amount(g["Amount_Granted"])
        out.grants.append({
            "key": f"grants/dia/{sha[:16]}/{n}",
            "publisher_key": DIA, "grantor_key": soc, "grantor_as_published": g["Society_Name"].strip(),
            "committee": None,
            "recipient_as_published": name, "recipient_final_as_published": blank(g["Final_Organisation_Name"]),
            "recipient_kind": recipient_kind(name, nz, cc),
            "nzbn_as_published": nz_pub, "nzbn": nz, "charity_number_as_published": cc_pub, "charity_number": cc,
            "status": status,
            "amount_requested_as_published": blank(g["Amount_Requested"]),
            "amount_granted_as_published": blank(g["Amount_Granted"]),
            "amount_nzd": granted if status == "Accepted" and granted else None,
            "multi_year": None,
            "purpose_as_published": None,
            "category_1": blank(g["Category_1"]), "category_2": blank(g["Category_2"]),
            "decided_on": decided, "decided_on_as_published": blank(g["Date_of_Accept/Decline"]),
            "period": year, "round": None,
            "is_refund": blank(g["Is_Refund"]), "refunded_on": a_date(g["Date_of_Refund"], out.notes, "refund date"),
            "refunded_on_as_published": blank(g["Date_of_Refund"]),
            "amount_refunded_as_published": blank(g["Amount_Refunded"]),
            "benefits": blank(g["Benefits_Single_Or_Multiple_Territorial_Authorities"]),
            "territorial_authority": blank(g["Territorial_Local_Authority"]),
            "other_territorial_authority": blank(g["Other_Territorial_Local_Authority"]),
            "region": blank(g["Region"]),
            "document": sha, "page": 1, "place": place, "read_from": "text", "reader": READER,
            "profile": DIA_CSV, "profile_version": out.version,
        })
    _reconcile(out)
    return out


# ── the Lottery's record of grants ────────────────────────────────────────────

_YEAR = re.compile(r"\b(?P<a>20\d{2})\s*[/-]?\s*(?P<b>\d{2})\b")
_ROUND = re.compile(r"\bround\s+(?P<r>one|two|three|four|\d)\b", re.I)


def heading_parts(heading: str) -> tuple:
    """(financial year 'yyyy/yy', round as printed or None, the committee or fund as printed) from a heading such as
    '2024/25 round two Lottery Community National record of grants' or 'Lottery Community Sector Research Fund
    2021/22 record of grants'."""
    y = _YEAR.search(heading)
    period = f"{y.group('a')}/{y.group('b')}" if y else None
    r = _ROUND.search(heading)
    rest = heading
    for m in (y, r):
        if m:
            rest = rest.replace(m.group(0), " ")
    rest = re.sub(r"(?i)\brecord of grants\b|\bLottery\b", " ", rest)
    return period, (r.group(0).lower() if r else None), re.sub(r"\s+", " ", rest).strip(" -–")


_MONEY = re.compile(r"^\$\s?(?P<n>\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)\s*(?P<star>\*?)$")


def read_lottery_page(data: bytes, sha: str, only=None) -> Reading:
    p = profile(LOTTERY_PAGE)
    r = p["recognise"]
    out = Reading(LOTTERY_PAGE, int(p["version"]))
    page = data.decode("utf-8", "replace")
    heading = next(h for h in headings(page) if re.search(r["heading_pattern"], h, re.I))
    period, rnd, committee = heading_parts(heading)
    if period is None:
        raise ValueError("the heading names no financial year")
    if int(period[:4]) < WINDOW_FROM:
        out.notes["a record before the window (ruling 71), not read"] += 1
        return out
    table = next(t for t in _TABLE.findall(page)
                 if [text_of(c[1]) for c in _CELL.findall(_ROW.findall(t)[0])] == r["table_head"])
    after = re.match(r"\s*<p\b[^>]*>(.*?)</p>", page[page.find(table) + len(table):], re.S | re.I)
    footnote = text_of(after.group(1)) if after else ""
    multi_year_note = footnote if footnote.startswith("*") else None
    rows = _ROW.findall(table)[1:]
    out.records = len(rows)
    for i, row in enumerate(rows, 1):
        cells = [text_of(c[1]) for c in _CELL.findall(row)]
        place = f"table row {i}"
        if len(cells) != 2:
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": f"{len(cells)} cells, not 2"})
            continue
        name, amt = cells
        if re.fullmatch(r"(?i)total", name):
            out.stated["total"] = amt
            out.notes["the table's own total row"] += 1
            out.records -= 1
            continue
        mm = _MONEY.match(amt)
        if not name or not mm:
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": "no name" if not name else "the amount is not a dollar figure"})
            continue
        if mm.group("star") and not multi_year_note:
            out.notes["an asterisk with no footnote on the page"] += 1
        out.grants.append({
            "key": f"grants/lottery/{sha[:16]}/{i}",
            "publisher_key": DIA, "grantor_key": LOTTERY, "grantor_as_published": f"Lottery {committee}",
            "committee": committee,
            "recipient_as_published": name, "recipient_final_as_published": None,
            "recipient_kind": recipient_kind(name, None, None),
            "nzbn_as_published": None, "nzbn": None, "charity_number_as_published": None, "charity_number": None,
            "status": "Accepted",
            "amount_requested_as_published": None, "amount_granted_as_published": amt,
            "amount_nzd": float(mm.group("n").replace(",", "")),
            "multi_year": (multi_year_note or "asterisk") if mm.group("star") else None,
            "purpose_as_published": None, "category_1": None, "category_2": None,
            "decided_on": None, "decided_on_as_published": None,
            "period": period, "round": rnd,
            "is_refund": None, "refunded_on": None, "refunded_on_as_published": None,
            "amount_refunded_as_published": None, "benefits": None, "territorial_authority": None,
            "other_territorial_authority": None, "region": None,
            "document": sha, "page": 1, "place": place, "read_from": "text", "reader": READER,
            "profile": LOTTERY_PAGE, "profile_version": out.version,
        })
    out.stated["heading"] = heading
    _reconcile(out)
    return out


READERS = {DIA_CSV: read_dia_csv, LOTTERY_PAGE: read_lottery_page}


def _reconcile(out: Reading) -> None:
    if out.records != len(out.grants) + len(out.set_aside):
        raise AssertionError(f"{out.slug}: {out.records} records in, {len(out.grants)} grants and "
                             f"{len(out.set_aside)} set aside out")


def read_document(data: bytes, sha: str, only=None) -> Reading:
    """One document, recognised then read; a document no profile recognises is one catch-log line (a PDF says how
    much text it carries, so a scan is told from a layout no profile knows)."""
    slug = recognise(data)
    if slug is None:
        out = Reading(None, None, [], [{"document": sha, "place": "whole document", "stage": "recognise",
                                        "reason": "no profile recognises its shape; not read"}], 1)
        if data.startswith(b"%PDF"):
            from registers.grants import pdftable
            ws = pdftable.words(data)
            out.stated = {"pages": pdftable.page_count(data), "text_words": len(ws)}
            if len(ws) < SCAN_WORDS:
                out.set_aside[0]["reason"] = "a scan: no text layer to read (no page reader runs in this lane)"
        return out
    if slug in READERS:
        return READERS[slug](data, sha, only)
    from registers.grants import society
    return society.read_file(data, sha, slug)


# ── recipients as published ───────────────────────────────────────────────────

def recipient_key(grantor: str, name: str, nzbn, cc) -> str:
    h = hashlib.sha256("\x1f".join((grantor, name, nzbn or "", cc or "")).encode()).hexdigest()[:20]
    return f"grants/recipient/{grantor}/{h}"


def recipients(grants: list) -> tuple:
    """(recipient rows, {grant key: recipient key}): one per grantor and recipient as published (the name exactly as
    printed, with the business and charity numbers printed beside it). Never joined across grantors or looked up."""
    by = {}
    link = {}
    for g in grants:
        k = recipient_key(g["grantor_key"], g["recipient_as_published"], g["nzbn"], g["charity_number"])
        link[g["key"]] = k
        r = by.get(k)
        if r is None:
            r = by[k] = {"key": k, "grantor_key": g["grantor_key"], "publisher_key": g["publisher_key"],
                         "name_as_published": g["recipient_as_published"], "kind": g["recipient_kind"],
                         "nzbn": g["nzbn"], "charity_number": g["charity_number"], "grants": 0, "accepted": 0,
                         "declined": 0, "amount_nzd": 0.0, "first_period": g["period"], "last_period": g["period"],
                         "document": g["document"], "page": g["page"], "place": g["place"],
                         "read_from": g["read_from"], "reader": g["reader"], "profile": g["profile"],
                         "profile_version": g["profile_version"]}
        r["grants"] += 1
        r["accepted"] += g["status"] == "Accepted"
        r["declined"] += g["status"] == "Declined"
        r["amount_nzd"] += g["amount_nzd"] or 0.0
        r["first_period"] = min(r["first_period"], g["period"])
        r["last_period"] = max(r["last_period"], g["period"])
    for r in by.values():
        r["amount_nzd"] = round(r["amount_nzd"], 2)
    return list(by.values()), link
