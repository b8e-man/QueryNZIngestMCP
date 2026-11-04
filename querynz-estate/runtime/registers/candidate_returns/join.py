"""Which candidate each held return belongs to, which return is current, and
which spreadsheet row states its totals (plan 4.1: "joined on year,
electorate and surname"). Pure: it takes the held files' names, the
listing rows and the spreadsheet rows, and returns the join with every
item it could not place named.

**A document's candidate**, in this order, and the first that answers is
recorded as `how`:

1. `listing link`: a listing row links the file (by the name the
   Commission published it under);
2. `listing name`: the file's own name carries one listing row's surname
   and electorate (of the file's year, where the path gives one), and no
   other row's;
3. `spreadsheet name`: likewise against the spreadsheet's rows (a listing
   page the browser kept on another day can miss rows: pages shift);
4. `file name`: the 2022 Tauranga by-election, `<Surname>-<Given>-Return`,
   under a folder named for the electorate; there is no Commission table
   held for it.

Two rows answering is an abstention, never a guess: attaching the wrong
return to a candidate puts another person's donors under their name.

**Which return is current.** The Commission: "If we receive an amended
return from a candidate, we will publish the amended version". So a held
file placed (by name) on a listing row that links a different file is
replaced by that file: `replaced` when it is held, `replaced, not held`
when it is not. Nothing else replaces a return: a file name saying
"amended" does not, and a file the listing pages do not show is `unlisted`,
current by default.

**The spreadsheet row** for a candidate is the one row of the same year
whose folded electorate and surname are the candidate's; where two are,
the given name decides, and otherwise it abstains.

    join(held, listing, sheet)  -> Join
      held     {sha256: [name the file was published under, ...]} with each document's year where its path states one
      listing  [ListingRow] for every year
      sheet    {year: [SheetRow]}
"""
import posixpath
import re
from dataclasses import dataclass, field

from registers.candidate_returns.commission import fold

TAURANGA_2022 = re.compile(r"^(?P<surname>.+)-(?P<given>[^-]+)-Return\.pdf$", re.I)


@dataclass
class Placed:
    document: str
    year: int = None
    surname: str = None
    given: str = None
    electorate: str = None
    party: str = None
    how: str = None                 # listing link | listing name | spreadsheet name | file name
    listing: object = None          # the ListingRow, where one answers
    sheet: object = None            # the SheetRow, where one answers
    status: str = "current"         # current | replaced | replaced, not held | unlisted
    replaced_by: str = None
    stated: str = None              # the Commission's link that replaces it, as written
    problems: list = field(default_factory=list)


@dataclass
class Join:
    placed: dict = field(default_factory=dict)              # sha256 → Placed
    unplaced: list = field(default_factory=list)            # (sha256, why)
    listing_not_held: list = field(default_factory=list)    # ListingRow whose link names no held file
    listing_no_link: list = field(default_factory=list)     # ListingRow with no link
    sheet_no_document: list = field(default_factory=list)   # SheetRow no current held document answers


def tokens(text: str) -> list:
    return fold(re.sub(r"\.pdf$", "", text, flags=re.I)).split()


def _contains(hay: list, needle: list) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def _names_row(name_tokens: list, surname: str, electorate: str) -> bool:
    return _contains(name_tokens, tokens(surname)) and _contains(name_tokens, tokens(electorate))


def _one(rows: list):
    return rows[0] if len(rows) == 1 else None


def sheet_row(sheet: dict, year: int, electorate: str, surname: str, given: str = ""):
    """(row | None, why)."""
    rows = [r for r in sheet.get(year, []) if fold(r.electorate) == fold(electorate) and fold(r.surname) == fold(surname)]
    if len(rows) > 1 and given:
        rows = [r for r in rows if fold(r.given).split()[:1] == fold(given).split()[:1]] or rows
    if not rows:
        return None, "no spreadsheet row of that year, electorate and surname"
    if len(rows) > 1:
        return None, f"{len(rows)} spreadsheet rows of that year, electorate and surname"
    return rows[0], ""


def join(held: dict, listing: list, sheet: dict, years: dict = None) -> Join:
    years = years or {}
    out = Join()
    by_name = {}
    for sha, names in held.items():
        for n in names:
            by_name.setdefault(n.lower(), set()).add(sha)
    linked = {}                                                         # sha → [ListingRow]
    for r in listing:
        if not r.href:
            out.listing_no_link.append(r)
            continue
        shas = by_name.get(posixpath.basename(r.href).lower())
        if not shas:
            out.listing_not_held.append(r)
            continue
        for s in shas:
            linked.setdefault(s, []).append(r)

    for sha, names in sorted(held.items()):
        p = Placed(sha)
        year = years.get(sha)
        name_toks = [tokens(n) for n in names]
        rows = linked.get(sha, [])
        if rows:
            keys = {(r.year, fold(r.surname), fold(r.electorate)) for r in rows}
            if len(keys) > 1:
                out.unplaced.append((sha, f"linked by {len(keys)} listing rows naming different candidates"))
                continue
            r, p.how = rows[0], "listing link"
        else:
            r = _one([x for x in listing if (year is None or x.year == year)
                      and any(_names_row(t, x.surname, x.electorate) for t in name_toks)])
            p.how = "listing name" if r else None
            if r is not None and year is None:
                # a file whose path states no year: a spreadsheet row of another year answering too is a second answer
                others = {(x.year, fold(x.surname), fold(x.electorate)) for y, rs in sheet.items() for x in rs
                          if y != r.year and any(_names_row(t, x.surname, x.electorate) for t in name_toks)}
                if others:
                    out.unplaced.append((sha, f"no year in the path, and candidates of {len(others) + 1} elections answer "
                                              f"to the file's name"))
                    continue
        if r is not None:
            p.listing = r
            p.year, p.surname, p.given, p.electorate, p.party = r.year, r.surname, r.given, r.electorate, r.party
            if p.how == "listing name":
                if r.href and by_name.get(posixpath.basename(r.href).lower()):
                    p.status, p.replaced_by = "replaced", sorted(by_name[posixpath.basename(r.href).lower()])[-1]
                    p.stated = r.href
                elif r.href:
                    p.status, p.stated = "replaced, not held", r.href
        else:
            cand = [x for y, rs in sheet.items() if year is None or y == year for x in rs
                    if any(_names_row(t, x.surname, x.electorate) for t in name_toks)]
            s = _one(cand)
            if s is not None:
                p.how, p.status, p.sheet = "spreadsheet name", "unlisted", s
                p.year, p.surname, p.given, p.electorate, p.party = s.year, s.surname, s.given, s.electorate, s.party
            elif year == 2022 and any(TAURANGA_2022.match(n) for n in names):
                m = next(TAURANGA_2022.match(n) for n in names if TAURANGA_2022.match(n))
                p.how, p.status = "file name", "unlisted"
                p.year, p.surname, p.given, p.electorate = 2022, m.group("surname").replace("-", " "), m.group("given"), "Tauranga"
            else:
                out.unplaced.append((sha, f"{len(cand)} spreadsheet rows and no single listing row answer to the file's name"
                                    if cand else "no listing or spreadsheet row answers to the file's name"))
                continue
        if p.sheet is None and p.year in sheet:
            p.sheet, why = sheet_row(sheet, p.year, p.electorate, p.surname, p.given)
            if why:
                p.problems.append(why)
        out.placed[sha] = p

    answered = {id(p.sheet) for p in out.placed.values() if p.sheet is not None and p.status in ("current", "unlisted")}
    out.sheet_no_document = [r for rs in sheet.values() for r in rs if id(r) not in answered]
    return out
