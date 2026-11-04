"""The reading of a council's register of members' pecuniary interests where
the council publishes it as a structured HTML page (profile
`interests-register-html-clause-rows` v1). No model, no PDF: a PDF register
is held and never read (ruling 79).

The shape, measured on Invercargill City Council's register (22 October
2026): one `<table>` per member; its first row a single cell with the
member's role and name in bold; each further row a number cell (`1.`) and a
cell whose bold text is the category as published, citing its clause of
the Local Government Act 2002 ("(section 54E(1)(a)"), followed by paragraphs, one
entry each. The category is the bold text; the entries are the plain
paragraphs.

Every category is read and kept (ruling 142; ruling 143: real-property
declarations kept whole, a spouse's or partner's interests read and kept).
Each row carries its flags: `real_property` (the heading names real property,
land, a home, an address or a contact), `of_partner` (the heading or an entry
names a spouse, partner or family member). An entry shaped like a street
address, an email or a phone number is kept in the lane's private schema
(`councillor_interests_private.entries`, by the row's key and the entry's
ordinal), which the session login never reads; the row counts it in
`private_entries`. Each flag is counted by heading in `flagged`.

    recognise(body) -> 'register' | 'page'
    read_register(body, sha, url) -> {'as_at', 'members': [...], 'rows': [...], 'flagged': Counter}
"""
import html
import re
from collections import Counter

READER = "registers/councillor_interests/read.py read_register"
PROFILE = "interests-register-html-clause-rows"
PROFILE_VERSION = 2
#: a heading naming real property, land, a home, an address or a contact: flagged `real_property`, read whole
CLAUSE = re.compile(r"\(\s*(?:s|section)\.?\s*54[A-H]\s*\(\s*\d\s*\)\s*\(?\s*([a-z])\s*\)?\s*\)?", re.I)
REAL_PROPERTY = re.compile(r"real\s+property|\bland\b|\bproperty\b|\bhomes?\b|address|residen|contact|phone|e-?mail", re.I)
#: a spouse's or partner's interests: read and kept, flagged `of_partner` (ruling 143 answered the queue's question)
PRIVATE_PERSON = re.compile(r"\bspouse\b|\bpartner\b|\bwife\b|\bhusband\b|\bfamily members?\b", re.I)
ROLE = re.compile(r"^(Deputy Mayor|Mayor|Deputy Chair|Chairperson|Chair|Councillor|Cr\.?)\s+", re.I)
NIL = re.compile(r"^(nil|none|n/?a|not applicable|-|–)\.?$", re.I)
STREET = re.compile(r"\b\d{1,4}[A-Za-z]?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s+(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|"
                    r"Terrace|Tce|Crescent|Cres|Lane|Way|Highway|Hwy|Parade|Quay)\b|\b(PO Box|P\.O\. Box|RD ?\d)\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(\+64|\b0)\d{1,2}[ -]?\d{3}[ -]?\d{3,4}\b")
#: an entry that names a road or a rural delivery, numbered or not ("State Highway 1, Kaiwaka"): kept privately
ROAD = re.compile(r"\b(Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Terrace|Tce|Crescent|Cres|Lane|Highway|Hwy|"
                  r"Parade|Quay|Boulevard|Grove|Close|Rise|Esplanade)\b\.?(,|\s*$)|\bState\s+Highway\b|\bRD\s?\d|"
                  r"\bLot\s+\d|\bSection\s+\d+\b.*\b(Block|DP|SO)\b|\b(DP|SO)\s?\d{3,}", re.I)
AS_AT = re.compile(r"\bas at\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})", re.I)
_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
_STRONG = re.compile(r"<(strong|b)\b[^>]*>(.*?)</\1>", re.S | re.I)
_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)


class NotTheShape(ValueError):
    """The page is not a register of this shape."""


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _member_tables(page: str) -> list:
    """The tables whose first row is one bold cell and whose other rows cite a clause of ss 54A to 54H."""
    out = []
    for t in _TABLE.findall(page):
        rows = _ROW.findall(t)
        if len(rows) < 2:
            continue
        head = _CELL.findall(rows[0])
        if len(head) != 1 or not _STRONG.search(head[0]):
            continue
        if sum(1 for r in rows[1:] if CLAUSE.search(text(r))) >= 1:
            out.append(rows)
    return out


def recognise(body: bytes) -> str:
    page = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    return "register" if len(_member_tables(page)) >= 2 else "page"


def private_entry(s: str) -> bool:
    """An entry shaped like a street address, a road, a rural delivery, a title, an email or a phone number: kept in
    the private schema."""
    return bool(STREET.search(s) or EMAIL.search(s) or PHONE.search(s) or ROAD.search(s))


def read_register(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    tables = _member_tables(page)
    if len(tables) < 2:
        raise NotTheShape("not a register of member tables citing a clause of ss 54A to 54H")
    m = AS_AT.search(text(page))
    as_at = m.group(1) if m else None
    members, rows, flagged = [], [], Counter()
    for ti, trs in enumerate(tables, 1):
        line = text(_CELL.findall(trs[0])[0])
        r = ROLE.match(line)
        role, name = (r.group(1), line[r.end():].strip()) if r else (None, line)
        members.append({"member": name, "role": role, "place": f"table {ti}"})
        for ri, tr in enumerate(trs[1:], 2):
            cells = _CELL.findall(tr)
            if len(cells) < 2:
                continue
            body_cell = cells[-1]
            label = " ".join(text(s[1]) for s in _STRONG.findall(body_cell))
            label = " ".join(label.split())
            if not label:
                continue
            clause = CLAUSE.search(label)
            category = re.sub(r"\(\s*s(ection)?\.?\s*$", "", CLAUSE.sub("", label)).strip(" :;,-–")
            plain = _STRONG.sub(" ", body_cell)
            entries = [e for e in (text(p) for p in (_P.findall(plain) or [plain])) if e and not NIL.match(e)]
            row = flags({"member": name, "role": role, "category": category,
                         "clause": clause.group(1).lower() if clause else None, "entries": entries,
                         "document": sha, "page": 1, "place": f"table {ti}, row {ri}", "url": url}, private_entry)
            for f in FLAG_WHY:
                if row[f]:
                    flagged[(category, FLAG_WHY[f])] += row[f] if f == "private_entries" else 1
            rows.append(row)
    return {"as_at": as_at, "members": members, "rows": rows, "flagged": flagged}


#: why a row is counted in `flagged`, by its flag
FLAG_WHY = {"real_property": "real property, a home, an address or a contact: read whole, flagged",
            "of_partner": "a spouse's, partner's or family member's interests: read, flagged",
            "private_entries": "an entry shaped like an address, an email or a phone number: kept privately"}


def flags(row: dict, is_private) -> dict:
    """The row with its flags set and its address-shaped entries moved to `private` [(ordinal, entry)]: the entries
    list keeps every other entry in order; nothing is dropped."""
    kept, private = [], []
    for i, e in enumerate(row["entries"], 1):
        (private if is_private(e) else kept).append((i, e))
    cat = row["category"]
    return {**row, "entries": [e for _i, e in kept], "private": private, "private_entries": len(private),
            "real_property": bool(REAL_PROPERTY.search(cat)) or row.get("kind") == "real property",
            "of_partner": bool(PRIVATE_PERSON.search(cat)) or any(PRIVATE_PERSON.search(e) for e in row["entries"])}
