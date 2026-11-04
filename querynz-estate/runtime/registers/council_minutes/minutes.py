"""The reading of a council's minutes PDF (Arthur, 2 November 2026: "we want to gather and ingest all of this"; "do it";
ruling 128 lifted ruling 79's hold on document reading for node2 alone): who was present, in attendance, apologised or
absent; the declarations of interest made at the meeting; every resolution with its item, mover, seconder, outcome and
votes where recorded.

Two profiles, recognised by the text layer's own landmarks, measured on the 616 landed minutes PDFs (2 November 2026):

  council-minutes-standard   InfoCouncil's standard minutes template: a line `RESOLUTION` (optionally `COMMITTEE` or
                             `COUNCIL` before it and the council's number after it), then `Moved:` and `Seconded:` lines,
                             the text as moved, and a line `CARRIED` or `LOST` on its own (Central Otago, Far North,
                             Western Bay of Plenty, Carterton, Horowhenua, Waimate, Wairoa, Waitaki, Taupō ...). Read
                             here, deterministically, no model.
  council-minutes-text       any other minutes with a text layer (Bay of Plenty Regional, Napier, Hastings, Palmerston
                             North ...): read by the text reader through model_read.py.

A PDF with no usable text layer is recognised by its shape, never by a phrase (a scan has no text for a phrase to
match): profile council-minutes-scanned (scan_shape: the bytes are a PDF, support.docread.pages.read_from says pixels,
and at least half its pages carry an image as wide as half the page, by pdfimages; nothing is read to decide it). Its
every page goes through the page reader (scans.py, qv4-council-minutes-pages, in the page reader's night window,
ruling 129); the stored page texts, tidied by from_pages (the page reader's markup taken off, an item heading put back
in the shape item_heading knows), are then recognised and read exactly as a text layer is: the same two skips first,
then the standard template's reading or the text reader. A mixed PDF's thin pages are named unread (measured
2 November 2026: 7 mixed PDFs of 616, 12 thin pages, none of them an image).

Two parts of a minutes document are flagged, never cut (ruling 142, 4 November 2026; they were skipped before):
  - a public-excluded part: from an item, or a banner line, that excludes the public (a resolution to exclude the
    public, an exclusion of the public, a public excluded section) to the line that readmits the public or the end; an
    item whose heading names public-excluded minutes or business, to the next item.
  - a public forum or deputation item: its speakers are members of the public.
Every line of both is kept whole (`parts`; council_minutes_private.part_lines), and the standard template's reading
reads their resolutions and declarations too, each row flagged with its `part`. The text reader reads the open
meeting's lines (`sections`); its stored readings cover those only.

    recognise(texts) -> (profile or '', why)
    sections(texts) -> ([(page, line)], skipped counts)       the lines left after the two skips
    read_standard(texts) -> {'attendance', 'declarations', 'resolutions', 'skipped'}
"""
import re
from collections import Counter

READER = "registers.council_minutes.minutes 1"
STANDARD = "council-minutes-standard"
TEXT = "council-minutes-text"
SCANNED = "council-minutes-scanned"
WAIT_PAGES = "waiting: page reader"
NOT_MINUTES = "not minutes: its text has no attendance and no resolution or motion"

_RES = re.compile(r"^\s*(?:(?:COMMITTEE|COUNCIL|BOARD|COMMUNITY BOARD|JOINT COMMITTEE)\s+)?RESOLUTION(?:\s+(?:NO\.?\s*)?"
                  r"([A-Z0-9][\w./-]*))?\s*$")
_MOVED = re.compile(r"^\s*Moved(?:\s+by)?\s*:\s*(\S.*?)\s*$", re.I)
_SECONDED = re.compile(r"^\s*Seconded(?:\s+by)?\s*:\s*(\S.*?)\s*$", re.I)
_OUTCOME = re.compile(r"^\s*\.?\s*(CARRIED UNANIMOUSLY|CARRIED BY DIVISION|CARRIED|LOST BY DIVISION|LOST|DEFEATED|"
                      r"LAPSED|WITHDRAWN|Carried unanimously|Carried|Lost|Defeated|Lapsed|Withdrawn)\.?\s*$")
_VOTES = re.compile(r"^\s*(For|Against|Abstained|Abstain|Abstentions)\s*:\s*(.*\S)\s*$", re.I)
#: an item heading: its number, then (two or more spaces) a title mostly in capitals
_ITEM = re.compile(r"^\s{0,14}(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s{2,}(\S.{2,}?)\s*$")
_PAGE = re.compile(r"^\s*(Page\s+\d+(\s+of\s+\d+)?|\d+\s*\|\s*P\s*a\s*g\s*e)\s*$", re.I)
#: the attendance labels, at the start of a line, with what follows them on the line
_LABEL = re.compile(r"^\s*(?:\d{1,2}\.?\s+)?(?:(?:OTHERS|ELECTED MEMBERS|OFFICERS|Others|Elected Members|Officers)\s+(?=IN ATTENDANCE|In Attendance))?(MEMBERS PRESENT|Members Present|PRESENT|Present|ALSO IN ATTENDANCE|Also in Attendance|"
                    r"Also In Attendance|IN ATTENDANCE|In Attendance|ALSO PRESENT|Also Present|STAFF PRESENT|Staff Present|"
                    r"APOLOGIES|Apologies|ABSENT|Absent)\b\s*(?:[:\-–]\s*|\s{2,}|$)(.*)$")
_KIND = {"members present": "present", "present": "present", "also in attendance": "in attendance",
         "in attendance": "in attendance", "also present": "in attendance", "staff present": "in attendance",
         "apologies": "apology", "absent": "absent"}

# ── the two skips ────────────────────────────────────────────────────────────────────────────────────────────
#: an item or banner that excludes the public: skipped to the readmission or the end
EXCLUDE = re.compile(r"exclu(?:de|sion of)\s+(?:the\s+)?public|public[\s-]+excluded\s+(?:section|session|business|part|"
                     r"meeting)|^\s*public[\s-]+excluded\s*$|resolution\s+to\s+exclude|in\s+committee\s*$", re.I)
#: an item whose heading names public-excluded minutes or business: that item only
EXCLUDED_ITEM = re.compile(r"public[\s-]+excluded", re.I)
READMIT = re.compile(r"(re-?admitted|readmitted|resum(?:ed|ption of)\s+(?:in\s+)?(?:open|public)|open\s+meeting\s+"
                     r"resumed|public\s+(?:were|was)\s+(?:invited\s+)?back|returned\s+to\s+open\s+meeting)", re.I)
#: a line that is only a public-excluded banner, in any case ("Public Excluded", "PUBLIC EXCLUDED SESSION")
BANNER = re.compile(r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?\s+)?public[\s-]+excluded(?:\s+(?:section|session|business|items?|part|"
                    r"meeting))?\s*[:.]?\s*$", re.I)
#: a contents page's line ("Resolution to exclude the public ........ 14"): never a banner
CONTENTS = re.compile(r"\.{4,}|…{2,}|_{4,}")
FORUM = re.compile(r"public\s+forum|public\s+participation|public\s+input|deputations?|presentations?\s+from\s+the\s+public|"
                   r"wāhanga\s+tūmatanui|wahanga\s+tumatanui|speaking\s+rights", re.I)


def _caps(title: str) -> bool:
    letters = [c for c in title if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) >= 0.6 * len(letters)


def item_heading(line: str):
    """(number, title) when the line is an item heading: a number, two or more spaces, a title mostly in capitals."""
    m = _ITEM.match(line)
    if m and _caps(m.group(2)) and not _OUTCOME.match(line):
        return m.group(1), re.sub(r"\s{2,}", " ", m.group(2)).strip()
    return None


#: a running head or foot: a line among a page's first or last EDGE non-blank lines, the same (digits aside) on at
#: least half the pages and on three or more ("CONFIRMED", the council's name and the meeting's date). A line any
#: skip or the reading turns on is never one, so a public-excluded banner repeated on every page still starts its skip.
EDGE = 4


def _form(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split())).lower()


def running_heads(texts: dict) -> set:
    on = Counter()
    for p in texts:
        body = [l for l in (texts[p] or "").splitlines() if l.strip()]
        on.update({_form(l) for l in body[:EDGE] + body[-EDGE:]})
    floor = max(3, (len(texts) + 1) // 2)
    return {f for f, n in on.items() if n >= floor}


def _turns_on(line: str) -> bool:
    return bool(BANNER.match(line) or EXCLUDE.search(line) or READMIT.search(line) or FORUM.search(line)
                or _RES.match(line) or _MOVED.match(line) or _SECONDED.match(line) or _OUTCOME.match(line)
                or _VOTES.match(line) or _LABEL.match(line) or item_heading(line))


def lines_of(texts: dict) -> list:
    """[(page, line)] of every page with text, page-number lines and running heads and feet dropped."""
    heads, out = running_heads(texts), []
    for p in sorted(texts):
        raw = (texts[p] or "").splitlines()
        body = [i for i, l in enumerate(raw) if l.strip()]
        edge = set(body[:EDGE] + body[-EDGE:])
        for i, line in enumerate(raw):
            if _PAGE.match(line) or (i in edge and _form(line) in heads and not _turns_on(line)):
                continue
            out.append((p, line.rstrip()))
    return out


#: the part a line sits in (parts): the open meeting, a public-excluded part, a public forum or deputation item
OPEN, EXCLUDED, FORUM_PART = "open", "public excluded", "public forum"


def parts(texts: dict) -> tuple:
    """([(page, line, part, n)] every line of the minutes, each with the part it sits in and that part's number in the
    document (0 for the open meeting), Counter of the lines and parts outside the open meeting). Every line is kept
    (ruling 142, 4 November 2026): a part is a flag beside its lines, never a cut."""
    out, skipped = [], Counter()
    k = [0]

    def opened(kind):
        k[0] += 1
        return kind

    part = OPEN
    for p, line, mode in _modes(texts, skipped):
        if mode is None:
            part = OPEN
        elif part == OPEN or mode.startswith("new "):
            part = opened(EXCLUDED if "excluded" in mode else FORUM_PART)
        out.append((p, line, part, 0 if part == OPEN else k[0]))
    return out, skipped


def sections(texts: dict) -> tuple:
    """([(page, line)] of the open meeting, Counter of what lies outside it). A public-excluded part runs from an item
    or banner that excludes the public to a readmission or the end; an item heading that names public-excluded
    minutes runs to the next item; a public forum or deputation item runs to the next item. The lines outside the
    open meeting are kept too, by `parts` (ruling 142); the text reader reads the open meeting's."""
    skipped = Counter()
    kept = [(p, line) for p, line, mode in _modes(texts, skipped) if mode is None]
    return kept, skipped


def _modes(texts: dict, skipped: Counter):
    """(page, line, mode) for every line: mode None in the open meeting, else the part it sits in ('new excluded',
    'excluded', 'new excluded item', 'excluded item', 'new forum', 'forum'; 'new' on a part's first line)."""
    mode, depth = None, None                     # None | 'excluded' | 'excluded item' | 'forum'
    for p, line in lines_of(texts):
        head = item_heading(line)
        title = head[1] if head else None
        banner = not head and not CONTENTS.search(line) and (
            BANNER.match(line) or (EXCLUDE.search(line) and len(line.strip()) < 90 and _caps(line)))
        if mode == "excluded":
            if READMIT.search(line):
                mode = None
            skipped["public excluded lines"] += 1
            yield p, line, "excluded"
            continue
        if head and mode in ("excluded item", "forum"):
            mode = None
        if (head and EXCLUDE.search(title)) or banner:
            mode = "excluded"
            skipped["public excluded parts"] += 1
            skipped["public excluded lines"] += 1
            yield p, line, "new excluded"
            continue
        if head and EXCLUDED_ITEM.search(title):
            mode = "excluded item"
            skipped["public excluded parts"] += 1
            skipped["public excluded lines"] += 1
            yield p, line, "new excluded item"
            continue
        if head and FORUM.search(title):
            mode = "forum"
            skipped["public forum items"] += 1
            skipped["public forum lines"] += 1
            yield p, line, "new forum"
            continue
        if mode:
            skipped["public excluded lines" if mode == "excluded item" else "public forum lines"] += 1
            yield p, line, mode
            continue
        yield p, line, None


# ── recognition ──────────────────────────────────────────────────────────────────────────────────────────────
def standard_resolutions(lines: list) -> int:
    """How many RESOLUTION lines are followed, within four lines, by a Moved: and a Seconded: line."""
    n = 0
    for i, (_p, line) in enumerate(lines):
        if _RES.match(line):
            nxt = [l for _q, l in lines[i + 1:i + 6] if l.strip()][:4]
            if any(_MOVED.match(l) for l in nxt) and any(_SECONDED.match(l) for l in nxt):
                n += 1
    return n


MINUTES_MARKS = re.compile(r"\b(present|apolog|in attendance|attendance)\b", re.I)
MOTION_MARKS = re.compile(r"\b(moved|seconded|resolved|resolution|carried|recommendation)\b", re.I)


def recognise(texts: dict, read_from: str) -> tuple:
    """(profile, why): STANDARD when the template's resolution triples are there, TEXT for other minutes with a text
    layer, '' and why not otherwise (a scan waits for the page reader; a document with no minutes landmarks is set
    aside)."""
    if read_from == "pixels":
        return "", WAIT_PAGES
    lines = lines_of(texts)
    whole = "\n".join(l for _p, l in lines)
    if not (MINUTES_MARKS.search(whole) and MOTION_MARKS.search(whole)):
        return "", NOT_MINUTES
    if standard_resolutions(lines) >= 1 and any(_LABEL.match(l) for _p, l in lines[:400]):
        return STANDARD, ""
    return TEXT, ""


# ── a scan: recognised by its shape; the page reader's text tidied for the same rules ───────────────────────────
#: an image at least this share of the page's width makes a page a picture page (the disclosures lane's measure)
PICTURE_SHARE = 0.5
NOT_A_SCAN = "set aside: no text layer and no page image"


def picture_pages(data: bytes) -> set:
    """The pages carrying an image at least PICTURE_SHARE of the page's width (pdfinfo and pdfimages -list: the
    file's structure, never its text)."""
    import subprocess
    try:
        info = subprocess.run(["pdfinfo", "-"], input=data, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        listing = subprocess.run(["pdfimages", "-list", "-"], input=data, capture_output=True, timeout=120).stdout.decode(
            "utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return set()
    m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
    width = float(m.group(1)) / 72 if m else 8.27
    out = set()
    for ln in listing.splitlines()[2:]:
        f = ln.split()
        try:
            if f[2] == "image" and float(f[12]) > 0 and int(f[3]) / float(f[12]) >= PICTURE_SHARE * width:
                out.add(int(f[0]))
        except (IndexError, ValueError):
            continue
    return out


def scan_shape(data: bytes, read_from: str, npages: int, pictures: set) -> tuple:
    """(SCANNED, '') when the document is a scan by its shape alone: a PDF, no usable text layer (read_from is
    pixels), and at least half its pages a picture page; ('', why) otherwise. No phrase is looked for."""
    if not (data or b"")[:5].startswith(b"%PDF"):
        return "", "not a PDF"
    if read_from != "pixels":
        return "", f"it has a text layer ({read_from})"
    if not npages or not pictures or 2 * len(pictures) < npages:
        return "", NOT_A_SCAN
    return SCANNED, ""


_TAG = re.compile(r"<[a-zA-Z/][^<>]{0,200}>")
_MD_HEAD = re.compile(r"^\s{0,3}#{1,6}\s+")
_NUMBERED = re.compile(r"^\s{0,14}(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(\S.{2,}?)\s*$")


def from_pages(text: str) -> str:
    """The page reader's text of one page made the shape the rules read: its markup off (HTML table tags, markdown
    headings, bold marks, table pipes), and a numbered heading mostly in capitals put back as `n  TITLE`, the shape
    item_heading knows (the page reader prints one space where the text layer keeps the column). A numbered line that
    names a public forum or a public-excluded part becomes a heading whatever its case, so neither skip is missed on a
    scan; over-skipping only loses what is kept, never shows what is not."""
    t = re.sub(r"</(?:tr|p|div|h\d|li|table)>|<br\s*/?>", "\n", text or "", flags=re.I)
    t = re.sub(r"</t[dh]>", "   ", t, flags=re.I)
    t = _TAG.sub("", t)
    out = []
    for line in t.splitlines():
        line = _MD_HEAD.sub("", line).replace("**", "").replace("__", "")
        if line.count("|") >= 2:
            line = re.sub(r"\s*\|\s*", "   ", line.strip().strip("|"))
        m = _NUMBERED.match(line)
        if m and not _OUTCOME.match(line) and len(m.group(2)) <= 100:
            num, title = m.group(1), m.group(2).strip()
            if FORUM.search(title) or EXCLUDE.search(title) or EXCLUDED_ITEM.search(title):
                title = title.upper()
            if _caps(title):
                line = f"{num}  {title}"
        out.append(line.rstrip())
    return "\n".join(out)


# ── the deterministic reading ───────────────────────────────────────────────────────────────────────────────
_ROLE = re.compile(r"^(?:the\s+)?(Deputy\s+Mayor|Mayor|Deputy\s+Chair(?:person|man|woman)?|Chair(?:person|man|woman)?|"
                   r"Councillors?|Cr|Crs|Board\s+Member|Member|Hon\.?)\s+", re.I)
_SPLIT = re.compile(r",|;|\s+and\s+(?=(?:Cr|Councillor|Mayor|Deputy|[A-Z]\b))")
#: a title and a name in running text: an apology from, or a declaration by, a member
MEMBER = re.compile(r"\b(Deputy\s+Mayor|Mayor|Deputy\s+Chair(?:person)?|Chair(?:person)?|Councillor|Cr|Member)\s+"
                    r"((?:[A-ZĀĒĪŌŪ][\w'’\-āēīōū]*\.?\s+){0,3}[A-ZĀĒĪŌŪ][\w'’\-āēīōū]+)")
#: a body's name, a heading over a list of its people: never one person
BODY = re.compile(r"\b(Council|Board|Committee|Limited|Ltd|Trust|Ministry|Department|Authority|Agency|Rūnanga|Runanga|"
                  r"Iwi|Hapū|Hapu|Incorporated|Inc|Society|Association)\b")
NOT_A_NAME = re.compile(r"\b(members?\s+of\s+the\s+(public|media|press)|public|media|staff|via|online|audio|visual|"
                        r"zoom|teams|livestream|arrived|left|departed|joined|from\s+\d|\d{1,2}[.:]\d{2})\b", re.I)


def _split_outside(text: str) -> list:
    """Split a list of attendees on commas, semicolons and 'and', never inside brackets."""
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            m = _SPLIT.match(text, i)
            if m and m.end() > i:
                parts.append(cur)
                cur = ""
                i = m.end()
                continue
        cur += c
        i += 1
    parts.append(cur)
    return [" ".join(p.split()) for p in parts if p.strip()]


def attendee(entry: str, kind: str) -> dict | None:
    """One attendee from a list entry: the role a title gives, the name, a title in brackets. None for anything that
    is not one named person (the public, the media, a time, a note)."""
    e = entry.strip(" .:-–")
    if not e or len(e) > 90 or NOT_A_NAME.search(e):
        return None
    title = None
    m = re.search(r"\(([^)]*)\)\s*$", e)
    if m:
        title = " ".join(m.group(1).split()) or None
        e = e[:m.start()].strip()
    if " – " in e or " - " in e:                    # "Name – Title", as some councils print in attendance
        e, t2 = re.split(r"\s+[–-]\s+", e, maxsplit=1)
        title = title or t2.strip() or None
    role = None
    e = re.sub(r"^(?:His|Her|Their)\s+Worship\s+", "", e)
    r = _ROLE.match(e)
    if r:
        role = " ".join(r.group(1).split())
        role = {"Cr": "Councillor", "Crs": "Councillor", "Councillors": "Councillor"}.get(role, role)
        e = e[r.end():].strip()
    if title and re.fullmatch(r"(?i)(deputy\s+)?(chair(person)?|mayor)", title):
        role, title = (role + ", " if role else "") + title, None
    if not re.search(r"[A-Za-zĀĒĪŌŪāēīōū]{2,}", e) or len(e.split()) > 6 or BODY.search(e):
        return None
    return {"name": e, "role": role, "title": title, "attendance": kind}


def attendance(lines: list) -> list:
    """Every attendee the labels list, in order: a label's own line after the label, then its continuation lines up to
    the next label, item, resolution or a blank line after something was read."""
    out, i = [], 0
    while i < len(lines):
        p, line = lines[i]
        m = _LABEL.match(line)
        head = item_heading(line)
        if not m:
            i += 1
            continue
        kind = _KIND[m.group(1).lower()]
        if head and kind == "apology":
            i += 1                                   # an apologies item: its resolution names them (apologies_from_text)
            continue
        # in heading form ("2  PRESENT - NGĀ MANUKURA") the rest of the line is the heading's te reo, not an attendee
        chunk, j = ([] if head else [m.group(2)]), i + 1
        while j < len(lines) and j < i + 40:
            q, nxt = lines[j]
            if not nxt.strip():
                if any(c.strip() for c in chunk):
                    break
                j += 1
                continue
            if _LABEL.match(nxt) or item_heading(nxt) or _RES.match(nxt) or _MOVED.match(nxt):
                break
            chunk.append(nxt)
            j += 1
        # a list printed one person a line has no commas: each such line ends an entry
        text = " ".join(" ".join(c.split()) + ("," if "," not in c and c.count("(") <= c.count(")") else "")
                        for c in chunk if c.strip()).rstrip(",")
        if head and not text:
            i = j
            continue
        for n, e in enumerate(_split_outside(text), 1):
            a = attendee(e, kind)
            if a:
                out.append({**a, "page": p, "place": f"{m.group(1).lower()} {n}"})
        i = j
    return out


def _item_text(lines: list, start: int) -> tuple:
    """The text of the item whose heading is lines[start], up to the next item heading: (text, page)."""
    body = []
    for _p, line in lines[start + 1:]:
        if item_heading(line):
            break
        body.append(line.strip())
    return " ".join(" ".join(body).split()), lines[start][0]


NO_DECLARATION = re.compile(r"\b(no|nil|none)\b[^.]{0,40}\b(declar|conflict|interest)|there\s+were\s+no\b|^\s*nil\.?\s*$|"
                            r"^\s*none\.?\s*$", re.I)
#: a sentence: a full stop ends one only where a space or the end follows it ("item 6.1", "a.m." do not)
SENTENCE = re.compile(r"(?:[^.]|\.(?=\S))+\.?")
DECLARES = re.compile(r"\b(declared|declares)\b.*\b(interest|conflict)\b|\bconflict of interest\b.*\b(declared|noted)\b", re.I)


def declarations(lines: list) -> list:
    """Each declaration of interest the minutes record: a sentence that names a member and declares an interest or a
    conflict, in the declarations item or anywhere else in what is read; the item it names where it names one."""
    out, seen = [], set()
    for i, (p, line) in enumerate(lines):
        head = item_heading(line)
        if head and re.search(r"declar|conflict|interest", head[1], re.I):
            text, _ = _item_text(lines, i)
            for s in SENTENCE.findall(text):
                _take(s, p, out, seen)
    text_all = [(p, l.strip()) for p, l in lines]
    joined, pages = "", []
    for p, l in text_all:
        pages.append((len(joined), p))
        joined += l + " "
    for m in SENTENCE.finditer(joined):
        s = m.group(0)
        if DECLARES.search(s):
            at = max((p for off, p in pages if off <= m.start()), default=1)
            _take(s, at, out, seen)
    return out


def _take(sentence: str, page: int, out: list, seen: set) -> None:
    s = " ".join(sentence.split())
    if NO_DECLARATION.search(s) and not MEMBER.search(s):
        return
    if not re.search(r"interest|conflict", s, re.I):
        return
    for m in MEMBER.finditer(s):
        role = m.group(1)
        role = {"Cr": "Councillor"}.get(role, role)
        name = " ".join(m.group(2).split())
        item = re.search(r"\bitems?\s+(\d{1,3}(?:\.\d{1,3}){0,3})", s, re.I)
        key = (name.lower(), item.group(1) if item else None)
        if key in seen:
            continue
        seen.add(key)
        out.append({"member": name, "role": role, "item": item.group(1) if item else None, "text": s[:600],
                    "page": page})


def apologies_from_text(lines: list) -> list:
    """The members an apologies item's resolution names (an apology from, or for, a member), when no label lists them."""
    out = []
    for i, (p, line) in enumerate(lines):
        head = item_heading(line)
        if head and re.search(r"apolog", head[1], re.I):
            body = []
            for _q, l in lines[i + 1:]:
                if item_heading(l):
                    break
                if not (_MOVED.match(l) or _SECONDED.match(l) or _RES.match(l) or _OUTCOME.match(l) or _VOTES.match(l)):
                    body.append(l.strip())
            sentences = [x for x in SENTENCE.findall(" ".join(" ".join(body).split())) if re.search(r"apolog", x, re.I)]
            for m in MEMBER.finditer(" ".join(sentences)):
                role = {"Cr": "Councillor"}.get(m.group(1), m.group(1))
                out.append({"name": " ".join(m.group(2).split()), "role": role, "title": None, "attendance": "apology",
                            "page": p, "place": f"apologies item {head[0]}"})
    return out


def resolutions(lines: list) -> list:
    """Every resolution in the template's shape: its item (the last item heading before it), the council's number,
    the mover and seconder, the text as moved, the outcome line, and the votes where a division is recorded."""
    out, item = [], (None, None)
    i = 0
    while i < len(lines):
        p, line = lines[i]
        head = item_heading(line)
        if head:
            item = head
            i += 1
            continue
        m = _RES.match(line)
        if not m:
            i += 1
            continue
        number, mover, seconder, body, outcome, votes = m.group(1), None, None, [], None, {}
        j = i + 1
        while j < len(lines):
            _q, nxt = lines[j]
            if _RES.match(nxt) or item_heading(nxt):
                break
            mm, ms, mo, mv = _MOVED.match(nxt), _SECONDED.match(nxt), _OUTCOME.match(nxt), _VOTES.match(nxt)
            if mm and mover is None:
                mover = " ".join(mm.group(1).split())
            elif ms and seconder is None:
                seconder = " ".join(ms.group(1).split())
            elif mv:
                votes[mv.group(1).lower().replace("abstentions", "abstained").replace("abstain", "abstained")
                      .replace("abstaineded", "abstained")] = " ".join(mv.group(2).split())
            elif mo:
                outcome = mo.group(1).upper()
                j += 1
                break
            elif nxt.strip():
                body.append(nxt.strip())
            j += 1
        if mover or seconder or outcome:
            text = " ".join(" ".join(body).split())
            out.append({"item": item[0], "item_title": item[1], "number": number, "mover": mover, "seconder": seconder,
                        "text": text, "outcome": outcome, "votes_for": votes.get("for"),
                        "votes_against": votes.get("against"), "abstained": votes.get("abstained"), "page": p})
        i = j
    return out


def read_standard(texts: dict) -> dict:
    """The deterministic reading of a minutes PDF in the standard template, after the two skips."""
    kept, skipped = sections(texts)
    att = attendance(kept)
    if not any(a["attendance"] == "apology" for a in att):
        att += apologies_from_text(kept)
    seen, uniq = set(), []
    for a in att:
        k = (a["name"].lower(), a["attendance"])
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    # a RESOLUTION line with its mover and seconder but no words before the next (Far North prints one so, then the
    # carried resolution under the next number): nothing as moved to publish, counted
    res = [dict(r, part=OPEN) for r in resolutions(kept)]
    decl = [dict(d, part=OPEN) for d in declarations(kept)]
    # the parts outside the open meeting, read the same way, each row flagged with its part (ruling 142)
    groups = {}
    for p, line, part, n in parts(texts)[0]:
        if part != OPEN:
            groups.setdefault((n, part), []).append((p, line))
    for (_, part), lines in sorted(groups.items()):
        res += [dict(r, part=part) for r in resolutions(lines)]
        decl += [dict(d, part=part) for d in declarations(lines)]
    skipped["resolutions with no text"] = sum(1 for r in res if not r["text"])
    return {"attendance": uniq, "declarations": decl, "resolutions": [r for r in res if r["text"]],
            "skipped": dict(skipped)}


#: a text that names a street address by its shape (ruling 102: the view carries the text whole with this flag beside it)
STREET = re.compile(r"\b\d{1,5}[A-Za-z]?(?:/\d+)?\s+(?:[A-ZĀĒĪŌŪ][\w'’\-āēīōū]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|"
                    r"Drive|Dr|Place|Pl|Terrace|Tce|Crescent|Cres|Lane|Highway|Hwy|Parade|Quay|Way|Grove|Close|Rise|"
                    r"Esplanade|Boulevard)\b", re.I)


def names_address(text: str) -> bool:
    return bool(STREET.search(text or ""))
