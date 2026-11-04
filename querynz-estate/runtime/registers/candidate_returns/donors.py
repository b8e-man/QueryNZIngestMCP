"""Part A: the donors a candidate return names (plan 4.1), from the text
layer. Only Part A names donors in the totals (Part C is anonymous; Part D
names an overseas donor and is not read here; Part B's contributors are
inside Part A's money).

**The page.** "PART A: CANDIDATE DONATIONS OF MORE THAN $1,500", its own
`TOTAL FOR PART A`, a header (name and street address | date or dates |
contributions Yes/No | amount), the rows, and the footer `PART A … Page: 2`;
an inserted continuation sheet carries the same footer. The columns are
taken from the header's own words on that page. The name-and-address cell
runs over two or three lines; a row's amount sits on one of them, and each
line of the cell belongs to the amount nearest it (a tie to the later one,
which is the next row's name line).

**The form's example row.** The blank form prints one row of its own: a
three-line name-and-address cell, two dates, "Yes" and $5,000.00 (the
dates differ by form: 2020, the 2022 by-election, 2023). Every return
carries it; it is never a donation. It is known by its cell, three lines
whose folded text hashes to `EXAMPLE_CELL` (measured: the same on 336 of
336 returns; the hash, not the text, is kept here), with $5,000.00 on one
of them, and its lines and amount are dropped before the rows are grouped,
so the next row's name is never pulled into it (lesson: the form's own
sample address is the tell for an example line left in a return).

**The reconciliation.** The rows are published only when they add to the
page's `TOTAL FOR PART A` and to the declaration's Part A, each to within
ruling 66's tolerance (`reconcile.py`: less than $100); a difference that
is not nil is published as the part's `issue` on every row, naming the
signed difference and which total; a Part A declared nil publishes no
rows. Anything else sets the part aside whole, with both figures.

**The cut** (as the party-returns lane's, copied: a lane never imports
another): the name is the text of the cell's first line before the first
figure or address word (`Level`, `Flat`, `PO Box`, `C/-`, `RD 3`), and
before the comma that opens a part holding a street word; then it ends at
its first comma (`Surname, Given` aside), because what follows a comma in
this cell is as likely a suburb as a name. Everything else in the cell is
the address and goes only to `candidate_returns_private` (hard limit 15).
A name the cut leaves holding a digit or a street word, or none, or a long
name (five words or more, no organisation word) from a cell of one line,
sets the part aside: an address must never reach a published name.

    read(texts, declared_a)     Part(rows, printed, check, problems, examples)
"""
import hashlib
import re
from dataclasses import dataclass, field

from support.docread import rows as R
from registers.candidate_returns import reconcile
from registers.candidate_returns.declaration import MONEY, amount

HEADING = re.compile(r"PART\s*A\s*[:.]?\s*CANDIDATE\s+DONATIONS\s+OF\s+MORE\s+THAN", re.I)
FOOTER = re.compile(r"^\s*PART\s*A\s{2,}.*\bPage\b|^\s*PART\s*A\s*$", re.I)
TOTAL = re.compile(r"TOTAL\s+FOR\s+PART\s+A\b", re.I)
HEADER_END = re.compile(r"If\s+YES\s+complete\s+Part\s+B|Enter\s+YES\s+or\s+NO", re.I)
COL_DATES = re.compile(r"Date\s+donation\s+or|Date\s+of\s+donation|aggregated\s+donations\b(?!\s*\()", re.I)
COL_YN = re.compile(r"Does\s+the\s+donation|contain\s+contributions", re.I)
COL_AMOUNT = re.compile(r"Amount\s+of\s+donation", re.I)
DATE = re.compile(r"\b\d{1,2}\s*[/.]\s*\d{1,2}\s*[/.]\s*\d{2,4}\b")
YES_NO = re.compile(r"\b(YES|NO|Yes|No|yes|no|Y|N)\b")
EXAMPLE_CELL = "464e95017731f665"     # sha256[:16] of the form's example cell, three lines folded (see the note)
#: where the address begins: a figure (not one run into a word: `3Sixty Ltd`, `1st Floor`), or a word that opens an address
ADDRESS_START = re.compile(r"\d(?![a-z]{2})|\bc\s*/\s*[-o](?!\w)|\b(?:care\s+of|(?:late|formerly)\s+of|level|lvl|floor|flat|unit|apt|"
                           r"apartment|suite|shed|building|bldg|p\.?\s*o\.?\s*box|private\s+bag|rd\s*\d)(?![a-z])", re.I)
STREET = re.compile(r"\b(?:street|st|road|rd|avenue|ave|lane|place|pl|terrace|tce|drive|dr|crescent|cres|parade|pde|"
                    r"highway|hwy|quay|way|close|grove|court|esplanade|rise|mews|boulevard|line|valley|heights|park)\b\.?", re.I)
CENT = 0.005


@dataclass
class Part:
    rows: list = field(default_factory=list)       # dicts: name, address, cell, amount, dates, yes_no, page
    printed: float = None                            # TOTAL FOR PART A, as the page prints it
    declared: float = None                           # Part A on the declaration page
    check: str = ""                                  # parts-sum | declared-nil | '' when set aside
    problems: list = field(default_factory=list)
    examples: int = 0                                # the form's example rows dropped
    issue: str = None                                # ruling 66: the rows reconcile within $100 but not to the cent


ORG = re.compile(r"\b(?:ltd|limited|trust|party|inc|incorporated|association|assn|union|council|branch|lec|electorate|"
                 r"committee|society|group|club|company|co|holdings|partnership|foundation|federation|church|campaign)\b", re.I)
SURNAME_GIVEN = re.compile(r"^[A-Z][\w'’\-]+,\s*[A-Z][\w'’.\-]*(?:\s+[A-Z][\w'’.\-]*)?$")
LONG_NAME = 5


def trim(name: str, one_line: bool):
    """(name, cut-off tail, why not): a name ends at its first comma, `Surname, Given` aside (what follows a comma
    in a name-and-address cell is as likely a suburb as a name); a long name from a one-line cell, with no
    organisation word, is not vouched for."""
    if "," in name and not SURNAME_GIVEN.match(name):
        head, tail = name.split(",", 1)
        name, cut = head.strip(" ;:-–("), tail.strip()
    else:
        cut = ""
    if len(R.name_key(name)) < 3:
        return None, cut, "no name before the address"
    if one_line and len(name.split()) >= LONG_NAME and not ORG.search(name):
        return name, cut, "a long name and its address on one line: the cut cannot vouch for it"
    return name, cut, ""


def split(cell: str):
    """(name, address) from one name-and-address cell, the name from its first line only; name None when nothing
    before the address is a name."""
    if "\n" in (cell or "").strip():
        first, rest = cell.strip().split("\n", 1)
        name, address = split(first)
        return (None, " ".join(cell.split())) if name is None else (name, " ".join(f"{address} {rest}".split()))
    cell = " ".join((cell or "").split()).strip(" ,;")
    m = ADDRESS_START.search(cell)
    head, rest = (cell[:m.start()], cell[m.start():]) if m else (cell, "")
    parts = re.split(r"(?<=[,;])", head)
    for i in range(len(parts)):                     # `Name, Main Road, Town`: no figure, still a street
        if STREET.search(parts[i]):
            if i == 0:
                if m:
                    continue
                return None, cell
            head, rest = "".join(parts[:i]), "".join(parts[i:]) + (" " + rest if rest else "")
            break
    name = re.sub(r"[,;]\s*\w{1,2}\W*$", "", head.strip()).strip(" ,;:-–($")
    if len(R.name_key(name)) < 3:
        return None, cell
    return name, rest.strip(" ,;")


def _columns(lines: list):
    """(dates, yes/no, amount) start columns from the page's own header, or None."""
    d = y = a = None
    for line in lines:
        for rx, which in ((COL_DATES, "d"), (COL_YN, "y"), (COL_AMOUNT, "a")):
            m = rx.search(line)
            if m:
                if which == "d" and (d is None or m.start() < d):
                    d = m.start()
                if which == "y" and (y is None or m.start() < y):
                    y = m.start()
                if which == "a" and (a is None or m.start() < a):
                    a = m.start()
    return (d, y, a) if None not in (d, y, a) and d < y < a else None


def _region(text: str):
    """(page lines of the table, printed total, columns) for one Part A page, or None."""
    lines = (text or "").splitlines()
    head = next((i for i, l in enumerate(lines) if HEADING.search(l)), None)
    foot = next((i for i, l in enumerate(lines) if FOOTER.match(l)), None)
    if head is None and foot is None and not any(TOTAL.search(l) for l in lines):
        return None
    printed = None
    for l in lines:
        t = TOTAL.search(l)
        if t:
            ms = [amount(m) for m in MONEY.finditer(l, t.end()) if amount(m) is not None]
            nonzero = [x for x in ms if x]                  # a typed figure over the form's printed 0
            printed = (nonzero[0] if nonzero else ms[0]) if ms else printed
    start = max((i for i, l in enumerate(lines[:foot] if foot else lines) if HEADER_END.search(l)), default=None)
    if start is None:
        return [], printed, None
    cols = _columns(lines[max(0, start - 12):start + 1])
    return lines[start + 1:foot if foot is not None else len(lines)], printed, cols


def _fold_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()[:16]


def _example_lines(lines: list, d: int) -> set:
    """The line numbers of the form's example cell, where its three lines are found together."""
    cells = [l[:d - 2].strip() for l in lines]
    filled = [i for i, c in enumerate(cells) if c]
    for k in range(len(filled) - 2):
        trio = filled[k:k + 3]
        if trio[2] - trio[0] <= 3 and _fold_hash(" ".join(cells[i] for i in trio)) == EXAMPLE_CELL:
            return set(range(trio[0], trio[2] + 1))
    return set()


def _records(lines: list, cols, page: int) -> tuple:
    """(records, examples dropped)."""
    d, y, a = cols
    example = _example_lines(lines, d)
    dropped = 0
    if example:
        ex_amounts = [i for i in example
                      if any(abs(amount(m) - 5000.0) < CENT for m in MONEY.finditer(lines[i][a - 6:]) if amount(m) is not None)]
        if ex_amounts:
            dropped = 1
            lines = [("" if i in example else l) for i, l in enumerate(lines)]
        else:
            example = set()
    anchors, cells = [], []
    for i, line in enumerate(lines):
        right = line[a - 6:] if len(line) > a - 6 else ""
        ms = [m for m in MONEY.finditer(right) if amount(m) is not None and not m.group("nil")]
        if ms:
            anchors.append((i, amount(ms[-1])))
        left = line[:d - 2].rstrip()
        cells.append(left)
    out = []
    for k, (i, amt) in enumerate(anchors):
        out.append({"page": page, "amount": round(amt, 2), "lines": [], "dates": [], "yes_no": None, "at": i})
    if not out:
        return out, dropped
    for i, line in enumerate(lines):
        dist = [(abs(i - r["at"]), -r["at"], n) for n, r in enumerate(out)]
        n = min(dist)[2]
        r = out[n]
        if cells[i].strip():
            r["lines"].append(cells[i].strip())
        mid = line[d - 2:a - 6] if len(line) > d - 2 else ""
        r["dates"] += [m.group(0) for m in DATE.finditer(mid[:max(0, y - d)])]
        yn = YES_NO.search(mid[max(0, y - d):])
        if yn and r["yes_no"] is None:
            r["yes_no"] = yn.group(1)
    return out, dropped


def read(texts: dict, declared) -> Part:
    out = Part(declared=declared)
    found = []
    pages = [p for p in sorted(texts) if HEADING.search(texts[p] or "") or TOTAL.search(texts[p] or "")
             or any(FOOTER.match(l) for l in (texts[p] or "").splitlines())]
    if not pages:
        if declared:
            out.problems.append("no Part A page carries a text layer")
        return _finish(out, found)
    for p in pages:
        region = _region(texts[p])
        if region is None:
            continue
        lines, printed, cols = region
        if printed is not None:
            out.printed = printed if out.printed is None else out.printed
        if not lines:
            continue
        if cols is None:
            if any(l.strip() for l in lines):
                out.problems.append(f"page {p}: the table's columns are not where its header says")
            continue
        recs, dropped = _records(lines, cols, p)
        found += recs
        out.examples += dropped
    return _finish(out, found)


def _finish(out: Part, found: list) -> Part:
    rows = []
    for r in found:
        cell = "\n".join(r["lines"])
        name, address = split(cell)
        why = R.malformed(R.Row(donor=" ".join(cell.split()), part="A"))
        if name is None:
            why = why or "no name before the address"
        else:
            name, cut, why2 = trim(name, len(r["lines"]) == 1)
            address = " ".join(f"{cut} {address}".split())
            why = why or why2
            if name and (re.search(r"\d", name) or STREET.search(name) or ADDRESS_START.search(name)):
                why = why or "the name the cut leaves holds a figure or a street word"
        if why:
            out.problems.append(f"row {len(rows) + 1} (page {r['page']}): {why}")
        rows.append({"name": name, "address": address, "cell": " ".join(cell.split()), "amount": r["amount"],
                     "dates": ", ".join(r["dates"]) or None, "yes_no": r["yes_no"], "page": r["page"]})
    total = round(sum(r["amount"] for r in rows), 2)
    if out.declared == 0.0 and not rows and not out.printed:
        out.check = "declared-nil"
        out.problems = []
        return out
    wants = [(what, x) for what, x in (("the declaration's Part A", out.declared), ("TOTAL FOR PART A", out.printed))
             if x is not None]
    if not wants:
        out.problems.append("nothing to reconcile against")
    for what, x in wants:
        if not reconcile.within(total, x):
            out.problems.append(f"the {len(rows)} rows read add to {total:,.2f}; {what} is {x:,.2f}")
    if out.problems:
        return out
    out.issue = reconcile.join(reconcile.issue(total, x, f"the {len(rows)} Part A rows against {what}") for what, x in wants)
    out.rows = [{**r, "issue": out.issue} for r in rows]
    out.check = "parts-sum" if rows else "declared-nil"
    return out
