"""The reading of one InfoCouncil meeting listing (profile
`infocouncil-meeting-listing` v1): the instance's default page, a grid of
the year's meetings, one row each. No model, no PDF, no minutes: the minutes
are captured and held unread (plan 6.3: no read of attendance or
resolutions; ruling 79: no document reading by a model).

The grid, as measured on 22 instances on 22 October 2026: `<tr
class="bpsGridMenuItem">` or `bpsGridMenuAltItem`, and in each row the cells
`bpsGridDate` (a date such as "22 Oct 2026", then the time in a span),
`bpsGridCommittee` (the body's name, then the venue in a span after a
`<br />`), `bpsGridAgenda`, `bpsGridAttachments`, `bpsGridMinutes` and, on
most instances, `bpsGridMinutesAttachments`. A document is a link
`RedirectToDoc.aspx?URL=Open/<yyyy>/<mm>/<CODE>_<date>_<TYPE>_<n>…<.htm|.PDF>`.
Link ids differ by instance and three instances print none, so a link's kind
is its cell and its format its extension. The venue (an address, and a body
that meets in a member's home would print one there) is kept whole in the
private twin, `council_minutes_private.venues` (ruling 142).

    recognise(body) -> 'listing'            raises NotTheShape
    read_listing(body, sha, base) -> {'year', 'meetings': [...], 'documents': [...]}
"""
import datetime as dt
import html
import re

READER = "registers/council_minutes/read.py read_listing"
PROFILE = "infocouncil-meeting-listing"
PROFILE_VERSION = 1
CELL_KIND = {"bpsGridAgenda": "agenda", "bpsGridAttachments": "agenda attachments", "bpsGridMinutes": "minutes",
             "bpsGridMinutesAttachments": "minutes attachments"}
_ROW = re.compile(r'<tr class="bpsGridMenu(?:Alt)?Item">(.*?)</tr>', re.S)
_CELL = re.compile(r'<td class="(bpsGrid\w+)">(.*?)</td>', re.S)
_LINK = re.compile(r'(<a\b[^>]*href="(RedirectToDoc\.aspx\?URL=Open/(\d{4})/(\d{2})/([^"]+))"[^>]*>)(.*?)</a>', re.S | re.I)
_FILE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)_(\d{8})_([A-Za-z]+)(?:_(\d+))?([A-Za-z0-9_]*)\.(htm|pdf)$", re.I)
_SIZE = re.compile(r"\(([\d.]+\s*[KMG]B)\)", re.I)
_DATE = re.compile(r"^\s*(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})")
_DMY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})")      # Dunedin prints 22/10/2026
_TIME = re.compile(r"(\d{1,2}:\d{2}\s*[ap]m)", re.I)
_YEAR = re.compile(r'<select[^>]*ddlYear.*?<option selected="selected" value="(\d{4})"', re.S)
_TAGS = re.compile(r"<[^>]+>")
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                      "Dec"), 1)}


class NotTheShape(ValueError):
    """The page is not an InfoCouncil meeting listing."""


def recognise(body: bytes) -> str:
    page = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    if 'class="bpsGridDate"' not in page or "ddlYear" not in page or "BusinessPapers.css" not in page:
        raise NotTheShape("not an InfoCouncil meeting listing: no bpsGridDate cell, year selector or BusinessPapers style")
    return "listing"


def text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def meeting_date(cell: str):
    t = text(cell)
    m = _DATE.match(t)
    if m and m.group(2) in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    m = _DMY.match(t)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def body_name(cell: str) -> str:
    """The committee cell's text before its first `<br`: the venue after it is `venue_of`'s."""
    return text(re.split(r"<br\s*/?>", cell, maxsplit=1, flags=re.I)[0])


def venue_of(cell: str):
    """The committee cell's text after its first `<br` (the venue, as printed), or None. Kept whole in the private twin
    (ruling 142, 4 November 2026)."""
    parts = re.split(r"<br\s*/?>", cell, maxsplit=1, flags=re.I)
    return text(parts[1]) if len(parts) > 1 else None


def file_parts(name: str):
    """(code, date digits, type, number, format) of a document's file name, or None."""
    m = _FILE.match(name)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3).upper(), m.group(4), m.group(6).lower()


def stem(fname: str) -> str:
    """A document's name without its format: `CO_20261022_AGN_3602_AT.PDF` and `…_AT_WEB.htm` are one stem."""
    return re.sub(r"(_WEB)?\.(htm|pdf)$", "", fname, flags=re.I)


def read_listing(body: bytes, sha: str, base: str) -> dict:
    """Every row of the grid, in page order. A row's key is the instance's host and its first document's stem
    (a supplementary agenda is its own row, with its own stem); a row with no document, or a stem met before on
    the page, is keyed by its date, body and place."""
    recognise(body)
    page = body.decode("utf-8", "replace")
    host = base.split("//", 1)[-1].strip("/")
    y = _YEAR.search(page)
    meetings, documents, seen = [], [], set()
    for place, row in enumerate(_ROW.findall(page), 1):
        cells = {c: v for c, v in _CELL.findall(row)}
        if "bpsGridDate" not in cells or "bpsGridCommittee" not in cells:
            raise NotTheShape(f"row {place}: no date or committee cell")
        date = meeting_date(cells["bpsGridDate"])
        tm = _TIME.search(text(cells["bpsGridDate"]))
        docs = []
        for cell, kind in CELL_KIND.items():
            for tag, href, yyyy, mm, fname, label in _LINK.findall(cells.get(cell, "")):
                parts = file_parts(fname)
                title = re.search(r'title="([^"]*)"', tag)
                size = _SIZE.search((title.group(1) if title else "") + " " + text(label))
                docs.append({"kind": kind, "format": "pdf" if fname.lower().endswith(".pdf") else "html",
                             "url": f"{base.rstrip('/')}/{href}", "file": fname, "folder": f"{yyyy}/{mm}",
                             "code": parts[0] if parts else None, "doc_type": parts[2] if parts else None,
                             "number": parts[3] if parts else None, "size_as_printed": size.group(1) if size else None})
        first = docs[0] if docs else None
        key = f"{host}/{stem(first['file'])}" if first else ""
        if not key or key in seen:
            key = f"{host}/{date}/{body_name(cells['bpsGridCommittee'])}/row {place}"
        seen.add(key)
        meetings.append({"key": key, "host": host, "body": body_name(cells["bpsGridCommittee"]),
                         "venue": venue_of(cells["bpsGridCommittee"]), "meeting_date": date,
                         "meeting_time": tm.group(1).lower() if tm else None, "code": first["code"] if first else None,
                         "documents": len(docs), "has_minutes": any(d["kind"] == "minutes" for d in docs),
                         "document": sha, "page": 1, "place": f"row {place}"})
        for d in docs:
            documents.append(dict(d, meeting_key=key, key=f"{host}/{d['file']}", document=sha, page=1,
                                  place=f"row {place}"))
    return {"year": int(y.group(1)) if y else None, "meetings": meetings, "documents": documents}
