"""The Commission's own table of large declarations, read (contract: the
reader; profile `ec-disclosure-listing`).

Two pages, three regimes, one shape: every table has three cells a row.

  donations-exceeding-20000          2023 onward, over $20,000: one row is one
                                     donation, with a link to the scanned
                                     declaration. Cells: party and the date the
                                     Commission received the return | donor
                                     name and address | amount and the date
                                     the party received it, and the link.
  …/donations-exceeding-30000        2011 to 2022, over $30,000, and 2008 to
                                     2010, over $20,000: one row is one
                                     declaration of one donor's gifts that
                                     together passed the threshold. Cells:
                                     party, the declared total and the
                                     Commission's date | donor | each gift
                                     with its date. No links.

The table is the source for the fields it carries (Arthur, 29 September
2026: "we can just take these off the EC website. the critical information
is there"); the scan is the declaration's evidence and is cited beside it.

The Commission states what happened to a declaration in brackets after its
date. That statement is read, never inferred (facts and traps: Electoral
Commission forms). "amended return received <date>" means this row carries
the amended figures; "amended on <date> and amendment withdrawn on <date>"
means the original stands; a shape not seen before is kept verbatim and
marked `unread`, and acts on nothing.

The donor cell's lines after the first are an address. They are returned
apart (`address`) so the lane can keep them in its private schema: no
published row carries one (hard limit 15).

Deterministic: a regex over captured HTML, no model.

    read(html_bytes) -> Reading(sections, rows, skipped)
"""
import html as _html
import re
from dataclasses import dataclass, field

from keys.dates import filed_date

REGIMES = (
    # (regime, threshold, heading pattern)
    ("over-20000-from-2023", 20000, re.compile(r"exceeding \$20,000 since 1 January (2023|2026)", re.I)),
    ("over-30000-2011-2022", 30000, re.compile(r"exceeding \$30,000 from 1 January 2011", re.I)),
    ("over-20000-2008-2010", 20000, re.compile(r"exceeding \$20,000 from 2008", re.I)),
)
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
_ANCHOR = re.compile(r'<a\b[^>]*href="([^"]+\.(?:pdf|jpe?g|png))"[^>]*>(.*?)</a>', re.S | re.I)
_PAREN = re.compile(r"\(([^)]*)\)")
_DATE_TEXT = re.compile(r"\d{1,2}\s+[A-Za-z]+\.?\s+\d{4}")
_AMENDED_RECEIVED = re.compile(r"amend\w*\s+(?:return\s+)?received\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_AMENDED_ON = re.compile(r"amended\s+(?:on\s+)?(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_WITHDRAWN = re.compile(r"withdrawn\s+on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_RETURNED = re.compile(r"returned to the donor by the party on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_SIZE = re.compile(r"^\((?:PDF|JPG|JPEG|PNG)[,\s\xa0]", re.I)


@dataclass
class Item:
    """One gift inside a declaration, as the Commission itemises it."""
    ordinal: int
    amount: float = None          # the first figure on the line ("$500 each received on …" is $500)
    first_date: str = None        # ISO: the first full date on the line; None where it gives none
    text: str = ""                # the line as printed: the whole statement, multiples and ranges included
    contributor: str = None       # a name line printed above this gift (a joint declaration)


@dataclass
class Row:
    regime: str
    threshold: int
    section: str                  # the heading the table sits under, as printed
    table: int                    # the table's number on the page, from 1
    row: int                      # the row's number in its table, from 1, header excluded
    party_label: str
    donor_name: str
    address: list                 # the donor cell's other lines; private, never published
    amount: float                 # the declared total, as printed (after an amendment the Commission prints)
    received_on: str              # ISO: the day the Commission received the declaration (the original)
    given_on: str = None          # ISO: the day the party received the gift (one-gift rows)
    commission_note: str = ""     # the bracketed statement after the Commission's date, verbatim
    amendment: str = "none"       # none | amended | amendment withdrawn | unread
    amended_on: str = None        # ISO: the day the amended return was received or made
    withdrawn_on: str = None
    returned_on: str = None       # ISO: the day the party returned the gift, where stated
    amount_note: str = ""         # what follows the amount and date, verbatim (NewZeal 2023)
    href: str = None              # the Commission's link to the scanned declaration
    amount_original: float = None  # the total before an amendment, where the Commission prints both
    items: list = field(default_factory=list)


@dataclass
class Reading:
    sections: list = field(default_factory=list)  # [(heading, regime, tables)]
    rows: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # [(table, row, reason)]: the catch log's lines


def lines(cell: str) -> list:
    cell = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", cell, flags=re.I)
    cell = re.sub(r"<[^>]+>", "", cell)
    return [" ".join(x.replace("\xa0", " ").split()) for x in _html.unescape(cell).split("\n") if x.strip()]


def money(text: str):
    m = _MONEY.search(text or "")
    return float(m.group(1).replace(",", "")) if m else None


def iso(text: str):
    d = filed_date(text)
    return d.isoformat() if d else None


def link(cell: str):
    """The declaration's link: the anchor that carries text. A cell can hold
    a stray empty anchor to another declaration in front of its own (IEF
    Limited, 2023, behind one to the Maritime Union's): the first href is
    not the row's."""
    anchors = _ANCHOR.findall(cell)
    with_text = [h for h, inner in anchors if lines(inner)]
    return (with_text or [h for h, _ in anchors] or [None])[0]


def amendment(note: str) -> tuple:
    """(state, amended_on, withdrawn_on, returned_on) from the Commission's
    bracketed note. Read, never inferred: a shape not seen is `unread`."""
    if not note:
        return "none", None, None, None
    returned = _RETURNED.search(note)
    if returned and "amend" not in note.lower():
        return "none", None, None, iso(returned.group(1))
    withdrawn = _WITHDRAWN.search(note)
    got = _AMENDED_RECEIVED.search(note) or _AMENDED_ON.search(note)
    if withdrawn and got:
        return "amendment withdrawn", iso(got.group(1)), iso(withdrawn.group(1)), None
    if got and not withdrawn and "withdraw" not in note.lower():
        return "amended", iso(got.group(1)), None, None
    return "unread", None, None, None


def _regime(heading: str):
    for regime, threshold, pat in REGIMES:
        if pat.search(heading):
            return regime, threshold
    return None, None


def _items(cell_lines: list) -> list:
    """The itemised gifts of a 2008–2022 declaration. A line naming no
    amount is a contributor's name for the lines below it (a joint
    declaration); a line whose date has no year keeps its text and no date."""
    out, who = [], None
    for ln in cell_lines:
        amt = money(ln)
        if amt is None:
            who = ln
            continue
        dm = _DATE_TEXT.search(ln)
        out.append(Item(len(out) + 1, amt, iso(dm.group(0)) if dm else None, ln, who))
    return out


def _read_new(cells, section, threshold, t, r):
    c0, c1, c2 = (lines(c) for c in cells)
    head = " ".join(c0[1:])
    note = " ".join(m.group(1) for m in _PAREN.finditer(head))
    received = iso(_PAREN.sub("", head))
    first = c2[0] if c2 else ""
    amt = money(first)
    dm = _DATE_TEXT.search(first)
    rest = first[dm.end():].strip(" -–,.") if dm else ""
    href = link(cells[2])
    state, amended_on, withdrawn_on, returned_on = amendment(note)
    row = Row("over-20000-from-2023", threshold, section, t, r, c0[0], c1[0] if c1 else "", c1[1:], amt, received,
              given_on=iso(dm.group(0)) if dm else None, commission_note=note, amendment=state,
              amended_on=amended_on, withdrawn_on=withdrawn_on, returned_on=returned_on, amount_note=rest,
              href=href)
    row.items = [Item(1, amt, row.given_on, first)]
    return row


_AMENDED_TO = re.compile(r"amended to\s+\$\s?([\d,]+(?:\.\d+)?)\*?\s*(.*?)\s*amended filed\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
_AMENDED_FROM = re.compile(r"^(.*?)\(\s*return amended from\s+\$\s?([\d,]+(?:\.\d+)?)\s*-?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*\)", re.I)


def _read_old(cells, regime, section, threshold, t, r):
    c0, c1, c2 = (lines(c) for c in cells)
    # the party may wrap onto two lines; the total is the first line with a $
    at = next((i for i, ln in enumerate(c0) if money(ln) is not None), None)
    if at is None:
        return None
    party = " ".join(c0[:at])
    total = money(c0[at])
    statement = " ".join(c0[at:])[len(c0[at]):].strip()
    rest = c0[at][_MONEY.search(c0[at]).end():]           # "$44,496.65 - 23 June 2008": a date on the total's line
    original = None
    to, frm = _AMENDED_TO.search(statement), _AMENDED_FROM.search(" ".join(c0[at:]))
    if to:
        # 2008: "$39,775.00 / amended to $41,037.00* / 7 January 2009 / amended filed 22 April 2009*"
        original, total = total, money("$" + to.group(1))
        received, note, state, amended_on = iso(to.group(2)), to.group(0), "amended", iso(to.group(3))
        withdrawn_on = returned_on = None
    elif frm:
        # 2008: "$44,496.65 - 23 June 2008 / (return amended from $44,571.65 - 16 June 2008)"
        original = money("$" + frm.group(2))
        received, note, state, amended_on = iso(frm.group(3)), frm.group(0)[len(frm.group(1)):], "amended", iso(rest)
        withdrawn_on = returned_on = None
    else:
        after = (rest + " " + statement).strip()
        note = " ".join(m.group(1) for m in _PAREN.finditer(after))
        plain = _PAREN.sub("", after)
        # "13 December 2018, amended 2 May 2019": the statement may be unbracketed
        if not note and re.search(r"amend", plain, re.I):
            note = plain[plain.lower().index("amend"):].strip(" ,")
            plain = plain[:plain.lower().index("amend")]
        received = iso(plain)
        state, amended_on, withdrawn_on, returned_on = amendment(note)
    row = Row(regime, threshold, section, t, r, party, c1[0] if c1 else "", c1[1:], total, received,
              commission_note=" ".join(note.split()), amendment=state, amended_on=amended_on,
              withdrawn_on=withdrawn_on, returned_on=returned_on, items=_items(c2))
    row.amount_original = original
    if len(row.items) == 1 and row.items[0].amount == total:
        row.given_on = row.items[0].first_date
    return row


def read(data: bytes) -> Reading:
    text = data.decode("utf-8", errors="replace")
    out = Reading()
    # each table belongs to the nearest heading above it that names a regime
    marks = [(m.start(), " ".join(lines(m.group(1)))) for m in re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", text, re.S | re.I)]
    t = 0
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", text, re.S | re.I):
        t += 1
        heading = next((h for at, h in reversed(marks) if at < m.start() and _regime(h)[0]), None)
        regime, threshold = _regime(heading or "")
        if regime is None:
            out.skipped.append((t, 0, "a table under no heading that names a regime"))
            continue
        if not out.sections or out.sections[-1][0] != heading:
            out.sections.append([heading, regime, 0])
        out.sections[-1][2] += 1
        r = 0
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)
            if len(cells) != 3:
                out.skipped.append((t, r, f"{len(cells)} cells, not 3"))
                continue
            first = lines(cells[0])
            if first and first[0].lower().startswith("party,"):
                continue                      # the header row
            r += 1
            row = (_read_new(cells, heading, threshold, t, r) if regime == "over-20000-from-2023"
                   else _read_old(cells, regime, heading, threshold, t, r))
            why = _why_not(row)
            if why:
                out.skipped.append((t, r, why))
                continue
            out.rows.append(row)
    return out


def _why_not(row) -> str:
    if row is None:
        return "no declared total in the first cell"
    if not row.party_label:
        return "no party"
    if not row.donor_name:
        return "no donor name"
    if row.amount is None:
        return "no amount"
    if not row.received_on:
        return "no date the Commission received it"
    return ""
