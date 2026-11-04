"""Part A from the page reader's stored readings (GLM-OCR, replayed, never
called) of a scanned return (plan 4.1). The rows are cut and reconciled by
`donors._finish`, exactly as the text layer's are: published only when they
add, to the cent, to the declaration's Part A and to the page's printed
`TOTAL FOR PART A` where that was read.

**The shape.** The reader writes the table as lines with no columns: each
row's name-and-address cell (one line or several), its dates, its Yes/No
and its amount in turn, the amount closing the row; sometimes the dates,
Yes/No and amount share a line (`22/07/2020 No $15,000.00`). This is the
party-returns lane's `stacked` route, copied in its rules (a lane never
imports another): every amount closes a row; an amount with no cell before
it, a cell left with no amount, or a cell line after the row's dates or
Yes/No sets the page aside, because the reader then went down the columns
or put an address's tail on the wrong side of a figure, and a name shifted
by one row still adds up (lesson: the sum cannot see a shifted line).

**The page's own furniture.** The table starts after the column headings
(the last of `Amount of donation …`, `(including GST)`, the printed
`$0.00`, `If YES complete Part B`). A cell, a date or an amount before
them, other than the form's example row and the printed total, or a column
heading after the first row, means the reader interleaved the columns with
the headings: the page is refused. `PART A` / `Page: 2` ends it.

**The form's example row** is dropped by the hash of its folded cell
(`donors.EXAMPLE_CELL`), over one to three consecutive lines, with its
dates, its Yes and the $5,000.00 that closes it; an example whose cell the
reader garbled is not known, stays a row, and its part fails to reconcile
(set aside, never published).

    read(texts, declared)     donors.Part (rows carry `page`; `problems` empty only when the part reconciles)
"""
import re

from registers.candidate_returns import donors
from registers.candidate_returns.declaration import MONEY, amount

TAG = re.compile(r"</?\w+[^>]*>")
#: the form's own words inside the table: never a cell
FURNITURE = re.compile(
    r"donor.?s?\s+name|street\s+address|date\s+donation|aggregated\s+donations|dd\s*/\s*mm\s*/\s*yyyy|enter\s+yes\s+or\s+no|"
    r"does\s+the\s+donation|contain\s+contributions|from\s+another\s+person|of\s+more\s+than|including\s+gst|"
    r"amount\s+of\s+donation|if\s+yes\s+complete|write\s+.nil|other\s+than\s+anonymous|^\W*received\W*$", re.I)
HEADER_LAST = re.compile(r"amount\s+of\s+donation|including\s+gst|if\s+yes\s+complete\s+part\s+b|^\W*\$\s*0\.00\W*$", re.I)
FOOT = re.compile(r"^\W*PART\s*A\W*$|^\W*Page\s*:?\s*\d*\W*$|^\W*PART\s*A\W+Page\b", re.I)
END = re.compile(r"PART\s*B\s*[:.]|TOTAL\s+FOR\s+PART\s+B|instructions?\s+for\s+part\s+B", re.I)
DATE = re.compile(r"\b\d{1,2}\s*[/.]\s*\d{1,2}\s*[/.]\s*\d{2,4}\b")
YESNO = re.compile(r"^(yes|no|y|n)$", re.I)
#: a closing line: optional dates, optional Yes/No, then the amount and nothing after it
CLOSE = re.compile(r"^(?P<pre>.*?)\s*(?P<yn>\b(?:yes|no)\b)?\s*(?P<money>\$?\s*\d[\d,\s]*\.\d{2})\s*$", re.I)


def clean(line: str) -> str:
    return " ".join(TAG.sub("  ", line).replace("|", "  ").split())


def _money_of(s: str):
    ms = [m for m in MONEY.finditer(s) if amount(m) is not None and not m.group("nil")]
    return amount(ms[-1]) if ms else None


def _is_date_line(s: str) -> bool:
    return bool(DATE.search(s)) and not re.search(r"[A-Za-z]{3,}", DATE.sub(" ", s))


def _example(lines: list):
    """(first, last) line numbers of the form's example cell among `lines`, or None."""
    for i in range(len(lines)):
        for n in (1, 2, 3):
            if i + n <= len(lines) and donors._fold_hash(" ".join(lines[i:i + n])) == donors.EXAMPLE_CELL:
                return i, i + n - 1
    return None


def _drop_example(lines: list):
    """The lines with the example's cell and its row (dates, Yes, $5,000.00) taken out; (lines, dropped)."""
    ex = _example(lines)
    if ex is None:
        return lines, 0
    a, b = ex
    j = b + 1
    while j < len(lines):                            # its dates and Yes, then its $5,000.00
        s = lines[j]
        m = _money_of(s) if CLOSE.match(s) else None
        if m is not None:
            if abs(m - 5000.0) >= donors.CENT:
                return lines, 0
            pre = CLOSE.match(s).group("pre")
            if pre and not _is_date_line(pre):
                return lines, 0
            keep = [l for l in lines[b + 1:j] if FURNITURE.search(l) or HEADER_LAST.search(l)]
            return lines[:a] + keep + lines[j + 1:], 1
        if not (_is_date_line(s) or YESNO.match(s) or FURNITURE.search(s)):
            return lines, 0                          # the cell meets something else before its figure: the columns again
        j += 1
    return lines, 0


def page_rows(text: str, page: int):
    """(rows, printed total, problem): one Part A page's rows, or a problem saying why the page is refused."""
    lines = [clean(l) for l in (text or "").splitlines()]
    lines = [l for l in lines if l]
    head = next((i for i, l in enumerate(lines) if donors.HEADING.search(l) or donors.TOTAL.search(l)), None)
    if head is None:
        return [], None, None
    body = lines[head:]
    stop = next((i for i, l in enumerate(body) if i and END.search(l)), len(body))
    body = body[:stop]
    printed = None
    kept = []
    for i, l in enumerate(body):
        t = donors.TOTAL.search(l)
        if t:
            got = _money_of(l[t.end():])
            if got is None and i + 1 < len(body) and re.fullmatch(r"\$?\s*[\d,]+\.\d{2}", body[i + 1]):
                got = _money_of(body[i + 1])
                body[i + 1] = ""
            printed = got if printed is None else printed
            continue
        kept.append(l)
    kept = [l for l in kept if l]
    kept, dropped = _drop_example(kept)
    last_head = max((i for i, l in enumerate(kept) if HEADER_LAST.search(l)), default=None)
    if last_head is None:
        return [], printed, f"page {page}: no column headings read"
    before = [l for l in kept[:last_head] if not FURNITURE.search(l) and not donors.HEADING.search(l)]
    if before:
        return [], printed, f"page {page}: the reader put {len(before)} line(s) of the table among its column headings"
    out, cell, mid, problem = [], [], [], None
    for l in kept[last_head + 1:]:
        if FOOT.match(l):
            break
        if FURNITURE.search(l):
            return [], printed, f"page {page}: a column heading read after the table's first row"
        c = CLOSE.match(l)
        money = _money_of(l) if c else None
        if c and money is not None:
            pre, yn = c.group("pre").strip(), c.group("yn")
            if pre and not _is_date_line(pre) and not YESNO.match(pre):
                if cell or mid:
                    return [], printed, f"page {page}: a row's cell and figure on one line after lines waiting for a figure"
                cell = [DATE.sub(" ", pre).strip()]
                pre = " ".join(m.group(0) for m in DATE.finditer(pre))
            if not cell:
                return [], printed, f"page {page}: a figure with no cell before it (the page read column by column)"
            if money:
                dates = [m.group(0) for x in mid + [pre] for m in DATE.finditer(x)]
                yes_no = yn or next((x for x in mid if YESNO.match(x)), None) or (pre if YESNO.match(pre or "") else None)
                out.append({"page": page, "amount": round(money, 2), "lines": cell, "dates": dates, "yes_no": yes_no})
            cell, mid = [], []
            continue
        if _is_date_line(l) or YESNO.match(l):
            mid.append(l)
            continue
        if mid:
            return [], printed, f"page {page}: a cell line after its row's dates or Yes/No"
        cell.append(l)
    if cell or mid:
        problem = f"page {page}: a cell left with no figure (the page read column by column, or the row runs on)"
    return ([] if problem else out), printed, problem


def read(texts: dict, declared) -> donors.Part:
    """Part A over the stored readings `texts` ({page: text}) of the pages after the declaration."""
    out = donors.Part(declared=declared)
    found = []
    for p in sorted(texts):
        rows, printed, problem = page_rows(texts[p], p)
        if printed is not None and out.printed is None:
            out.printed = printed
        if problem:
            out.problems.append(problem)
        found += rows
    out.examples = sum(1 for p in sorted(texts) if _example([clean(l) for l in (texts[p] or "").splitlines() if l.strip()]))
    return donors._finish(out, found)
