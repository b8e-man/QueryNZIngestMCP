"""The Commission's own statements about candidate returns (plan 4.1): its
per-election listing and its summary spreadsheet. Pure parsing; the files
are found and landed by `capture.py`.

**The listing** ("Candidate expenses and donations for the 2020 general
election"; "… donations and loans" for 2023), twenty rows a page: the
return's link, the year, the candidate (`SURNAME`, given names), the
electorate, the party, and the donations and expenses as the Commission
states them. Its own words on amendments: "If we receive an amended
return from a candidate, we will publish the amended version and if
applicable adjust the summary table. Previous versions are available on
request." So the file a row links is that candidate's current return, and
a held file for the same row that the row no longer links is one it
replaced (`join.py`). A row's link is the anchor that carries text (lesson:
the first link in a Commission table cell is not always the row's own).
A page with no table (a challenge page the browser kept) gives no rows and
is named by `pages_without_rows`.

**The spreadsheet**, one row a candidate: year, electorate, last name,
first name, party, donations, expenses and (2023) total loans. "NIL" is
0.00; a blank cell is no figure. The Commission's own typing is read as
printed where it is unambiguous (`$4,250,00` is 4250.00, a comma typed for
the point) and named otherwise. A file that is not a table (the 22 August
2024 "csv" is a challenge page the archive kept) is refused, never read as
an empty spreadsheet.

    listing_rows(html)          [ListingRow]
    spreadsheet_rows(data, name)  [SheetRow]; raises NotATable for a file that is not one
    money(text)                 (amount | None, problem | '')
    fold(text)                  the comparison form of a name or an electorate
"""
import csv
import html as H
import io
import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


class NotATable(ValueError):
    pass


@dataclass(frozen=True)
class ListingRow:
    year: int
    surname: str
    given: str
    electorate: str
    party: str
    donations: object          # float | None
    expenses: object
    href: str                  # the link as the Commission wrote it ('' when the row links nothing)
    problems: tuple = ()


@dataclass(frozen=True)
class SheetRow:
    year: int
    electorate: str
    surname: str
    given: str
    party: str
    donations: object
    expenses: object
    loans: object
    line: int                  # the row's place in the file, from 1 (the header is 1)
    problems: tuple = ()
    received: bool = True      # False where the Commission writes "Return not received"
    sheet: str = ""            # the workbook's tab the row was read from, as named there ('' for a csv)


MONEY = re.compile(r"^\$?\s*(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?$")
POINTS_FOR_COMMAS = re.compile(r"^\$?\s*(\d{1,3}(?:\.\d{3})+)\.(\d{2})$")
COMMA_FOR_POINT = re.compile(r"^\$?\s*(\d{1,3}(?:,\d{3})*),(\d{2})$")


def money(text):
    """(amount, '') or (None, '') for a blank cell, (None, why) when it is not money."""
    t = (text or "").strip().replace(" ", " ")
    if not t:
        return None, ""
    if t.lower() in ("nil", "$0", "0", "-", "$-"):
        return 0.0, ""
    t = t.replace(" ", "")
    m = MONEY.match(t)
    if m:
        return float(f"{m.group(1).replace(',', '')}.{(m.group(2) or '').ljust(2, '0')}"), ""
    m = COMMA_FOR_POINT.match(t)
    if m:
        return float(f"{m.group(1).replace(',', '')}.{m.group(2)}"), ""
    m = POINTS_FOR_COMMAS.match(t)                    # `$20.895.09`: points typed for the commas
    if m:
        return float(f"{m.group(1).replace('.', '')}.{m.group(2)}"), ""
    return None, f"not a figure: {text.strip()!r}"


def fold(text: str) -> str:
    """Macrons, case, hyphens, apostrophes and spacing aside (the Commission
    writes `Ōtaki` in the spreadsheet and `Otaki` in a file name)."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[’'`]", "", t)
    return re.sub(r"[\s\-_]+", " ", t).strip()


# ---------------------------------------------------------------- the listing

TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S | re.I)
CELL = re.compile(r'<h4 class="key">\s*([^<]+?)\s*</h4>\s*<div class="value">(.*?)</div>', re.S | re.I)
ANCHOR = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
SURNAME = re.compile(r'<span[^>]*uppercase[^>]*>(.*?)</span>\s*,?\s*(?:<br\s*/?>)?(.*)$', re.S | re.I)
TAGS = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(TAGS.sub(" ", s or ""))).strip()


def _row_link(cell: str) -> str:
    links = [(href, _text(body)) for href, body in ANCHOR.findall(cell or "")]
    own = [h for h, t in links if t] or [h for h, _ in links]
    return H.unescape(own[0]) if own else ""


def listing_rows(page: str) -> list:
    out = []
    for body in TBODY.findall(page or ""):
        cells = {k.strip().lower(): v for k, v in CELL.findall(body)}
        if "candidate" not in cells:
            continue
        problems = []
        m = SURNAME.search(cells["candidate"])
        surname, given = (_text(m.group(1)), _text(m.group(2))) if m else (_text(cells["candidate"]), "")
        figures = {}
        for k in ("donations", "expenses"):
            figures[k], why = money(_text(cells.get(k, "")))
            if why:
                problems.append(f"{k}: {why}")
        year = _text(cells.get("year", ""))
        out.append(ListingRow(int(year) if year.isdigit() else 0, surname, given, _text(cells.get("electorate", "")),
                              _text(cells.get("party", "")), figures["donations"], figures["expenses"],
                              _row_link(cells.get("download", "")), tuple(problems)))
    return out


# ---------------------------------------------------------------- the spreadsheet

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = {"year": "year", "electorate": "electorate", "lastname": "surname", "firstname": "given", "party": "party",
           "donations": "donations", "expenses": "expenses", "totalloans": "loans", "loans": "loans",
           "surname": "surname", "givenname": "given", "givennames": "given", "candidatesurname": "surname",
           "candidatefirstname": "given", "totaldonations": "donations", "totalexpenses": "expenses", "firstnames": "given"}
NOT_RECEIVED = re.compile(r"^\s*(?:return\s+)?not\s+received\s*$", re.I)


def _xlsx_cells(data: bytes) -> tuple:
    """(rows, the tab's name) of the workbook's first worksheet part."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise NotATable(f"not a workbook: {e}")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    sheet = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheet:
        raise NotATable("a workbook with no sheet")
    rows = []
    for r in ET.fromstring(z.read(sheet[0])).iter(f"{{{NS['m']}}}row"):
        vals = {}
        for c in r.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
            v = c.find("m:v", NS)
            text = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t")) if c.get("t") == "inlineStr" else \
                (v.text if v is not None else "")
            if c.get("t") == "s" and text:
                text = shared[int(text)]
            vals[col] = text or ""
        width = max((_col(k) for k in vals), default=0)
        rows.append([vals.get(_name(i), "") for i in range(1, width + 1)])
    return rows, _tab(z, sheet[0])


REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _tab(z, part: str) -> str:
    """The name the workbook gives the worksheet part (`xl/worksheets/sheet1.xml`), through its relationships;
    the part's own name where the workbook does not say."""
    try:
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target", "").lstrip("/").removeprefix("xl/") for r in rels}
        for s in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{{{NS['m']}}}sheet"):
            if "xl/" + target.get(s.get(REL), "") == part:
                return s.get("name") or ""
    except (KeyError, ET.ParseError):
        pass
    return os.path.splitext(os.path.basename(part))[0]


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _name(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _csv_cells(data: bytes) -> list:
    text = data.decode("utf-8-sig", "replace")
    if re.search(r"<html|<script|Incapsula", text[:2000], re.I):
        raise NotATable("an HTML page, not a table (a challenge page the archive kept)")
    return list(csv.reader(io.StringIO(text)))


def _number_cell(v: str) -> str:
    """A workbook stores money as a number (`4710.16`, or `4710.1599999`); write it as printed."""
    try:
        return f"{float(v):.2f}" if re.match(r"^-?\d+(\.\d+)?(E-?\d+)?$", v.strip(), re.I) else v
    except ValueError:
        return v


def spreadsheet_rows(data: bytes, name: str, year: int = None) -> list:
    """`year` for a spreadsheet with no year column (2020's)."""
    cells, tab = _xlsx_cells(data) if name.lower().endswith(".xlsx") else (_csv_cells(data), "")
    head_at = next((i for i, r in enumerate(cells[:10])
                    if sum(1 for c in r if re.sub(r"[^a-z]", "", c.lower()) in HEADERS) >= 4), None)
    if head_at is None:
        raise NotATable("no header row naming year, electorate, last name and donations")
    cols = {}
    for j, c in enumerate(cells[head_at]):
        k = HEADERS.get(re.sub(r"[^a-z]", "", c.lower()))
        if k and k not in cols:
            cols[k] = j
    out = []
    for i, r in enumerate(cells[head_at + 1:], head_at + 2):
        get = lambda k: (r[cols[k]] if k in cols and cols[k] < len(r) else "").strip()
        if not any(x.strip() for x in r):
            continue
        problems, figs, received = [], {}, True
        for k in ("donations", "expenses", "loans"):
            raw = _number_cell(get(k)) if name.lower().endswith(".xlsx") else get(k)
            if NOT_RECEIVED.match(raw):
                figs[k], received = None, False
                continue
            figs[k], why = money(raw)
            if why:
                problems.append(f"{k}: {why}")
        y = get("year")
        y = int(float(y)) if re.match(r"^\d{4}(\.0)?$", y) else (year or 0)
        out.append(SheetRow(y, get("electorate"), get("surname"), get("given"), get("party"), figs["donations"],
                            figs["expenses"], figs["loans"] if "loans" in cols else None, i, tuple(problems), received, tab))
    return out
