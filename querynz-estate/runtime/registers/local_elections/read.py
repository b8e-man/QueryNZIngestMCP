"""The reading of a council's returns listing (tranche c): structured pages
only. No return is opened: the PDFs, Word files and scans are landed by hash
and held for the reading ruling 79 waits on.

A listing page is the council's own HTML page that links its candidates'
returns of electoral donations and expenses (Local Electoral Act 2001,
s 112A; s 112F has the electoral officer publish them for seven years). The
page is read in document order: every heading, accordion title, summary,
table caption or bold line is context; every link to a file is an item. An
item is a return when its words or its address say so, or when it sits under
a heading that does; a form, a guide, a results notice, a nomination list is
counted by its kind and not a row. For each return:

  candidate_as_listed  the link's words with the return's own words (and the
                       file's size) taken off; failing that, the file's name
                       with its year, council prefix and the position's words
                       taken off. Kept as printed: never matched to a person
  position             the nearest context naming a seat: a ward, a
                       constituency, a mayoralty, a community or local board,
                       a subdivision, a licensing trust; else the link's own
                       words or the file's address; else ''
  election_year        the item's own words or address, else the one year
                       the seed lists for the page (a council that calls its
                       2025 election '2026' is corrected there), else the
                       nearest context, else the page's title or address; a year outside the window is
                       counted and set aside (ruling 71: 2017 onward)
  by_election          context or words that say by-election
  covers               'one candidate', or 'several candidates' where the link
                       names a seat, an election or a range and no person
                       (a combined file: its candidates wait on the reading)
  return_kind          'donations and expenses' unless the listing says only
                       one; 'nil' where it says nil (the statutory form is one
                       return of both: s 112A(3))

A page whose items are other listing pages (a folder, a year) yields those
pages for the capture to follow, never rows. Pure: bytes in, rows out.
"""
import html
import re
import urllib.parse

FILE = re.compile(r"\.(pdf|docx?|xlsx?|rtf|tiff?|jpe?g|png)(?:$|[?#])", re.I)
#: an address a council's content system serves a file from without an extension
FILE_ROUTES = re.compile(r"/(?:__data/assets/(?:pdf|word_doc|file)_file/|-/media/|media/[a-z0-9]{6,10}/|assets/documents/|"
                         r"documents/[^?]*download|download(?:file|document)?/|api/assets/|ArticleFile|DocumentCentre/View|"
                         r"files/assets/)", re.I)
TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>", re.S)
HREF = re.compile(r"""\bhref\s*=\s*(["'])(.*?)\1""", re.I | re.S)
CONTEXT_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "summary", "caption", "button", "dt", "th", "strong", "b", "legend")
HEAD_RANK = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_BLOCKS = re.compile(r"<(script|style|noscript|template|svg|nav|footer|header)\b.*?</\1\s*>", re.I | re.S)
YEAR = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
WINDOW_FROM = 2017   # ruling 71
RETURN_WORDS = re.compile(r"\b(returns?|donations?|expenses?|expenditure|electoral\s+(?:donations?|expenses?)|nil)\b", re.I)
#: an item that is not a candidate's return, by its words (counted, not a row)
NOT_A_RETURN = re.compile(
    r"\b(form|guide|guidance|handbook|instructions?|template|blank|nomination|nominations|candidate\s+profiles?|"
    r"profile\s+booklet|results?|declaration\s+of\s+(?:the\s+)?result|progress|pre-?election|report|policy|"
    r"timetable|calendar|notice|map|brochure|booklet|statistics|turnout|code\s+of\s+conduct|"
    r"representation|order\s+paper|minutes|agenda|special\s*votes|voting\s+document|info\s+sheet)\b", re.I)
#: words that make an item a blank form or advice whatever else it says
BLANK_FORM = re.compile(r"\b(form|blank|template|guide|guidance|handbook|instructions?)\b", re.I)
SEAT = re.compile(
    r"\b(mayor(?:alty|al)?|ward|wards|constituency|constituencies|community\s+board|local\s+board|subdivision|"
    r"licensing\s+trust|district\s+council|regional\s+council|city\s+council|at[\s-]large|general\s+roll|"
    r"m[aā]ori\s+(?:ward|constituency)|councillors?|board|trust|regional|general)\b", re.I)
#: context that names nothing (a council's repeated subheading under each seat)
EMPTY_CONTEXT = re.compile(r"^(candidate\s+declarations?|returns?|documents?|downloads?|files?|attachments?|"
                           r"related\s+documents?|candidates?|electoral\s+donations\s+and\s+expenses(?:\s+returns?)?|"
                           r"show\s+all|hide\s+all|expand\s+all|collapse\s+all|toggle.*|menu|search)$", re.I)
BY_ELECTION = re.compile(r"\bby[\s-]?elections?\b", re.I)
SIZE = re.compile(r"[\(\[]\s*(?:pdf|docx?|word|xlsx?)?[\s,:-]*\d[\d.,]*\s*(?:kb|mb|bytes?)\s*[\)\]]|[\(\[]\s*(?:pdf|docx?|word)\s*[\)\]]",
                  re.I)
NAME_NOISE = re.compile(
    r"\b(?:electoral|donations?|and|&|expenses?|expenditure|returns?|of|for|the|candidate'?s?|nil|declaration|"
    r"pdf|docx?|download|view|file|amended|updated|revised|form)\b|\b[a-z]+_[a-z_]+\b", re.I)


#: link words that name nothing: the name is in the row before the link
GENERIC_WORDS = re.compile(r"(?i)(?:page\s*\d+\s*)?(?:view|download|open|see|read)?\s*(?:now|file)?\s*(?:the\s+)?(?:return|returns|pdf|here|click here|link|"
                           r"file|document|expenses?|donations?(?:\s+and\s+expenses?)?|declaration|form)?\s*"
                           r"(?:\(?\s*pdf[^)]*\)?)?\s*(?:get_app|file_download|picture_as_pdf|download)?")


#: a result's status beside a candidate's name in a results table (dropped from the name)
STATUS_WORDS = re.compile(r"(?i)\b(?:not\s+)?(?:elected|excluded|withdrawn|retired|unsuccessful|successful|"
                          r"pdf|kb|mb|open\s+file)\b")


class NotTheShape(ValueError):
    """The page is not a listing this reader knows: set aside whole."""


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def safe_url(url: str) -> str:
    """An address as a request can carry it: spaces and other unsafe characters percent-encoded, nothing else
    changed (an address already encoded stays as it is)."""
    p = urllib.parse.urlsplit(url.strip())
    q = lambda s, safe: urllib.parse.quote(s, safe=safe + "%")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, q(p.path, "/:@!$&'()*+,;=-._~"),
                                    q(p.query, "/:@!$&'()*+,;=?-._~"), ""))


def is_file(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path
    return bool(FILE.search(path) or FILE_ROUTES.search(path))


def years_in(s: str) -> list:
    return [int(y) for y in YEAR.findall(s or "")]


def year_of(*texts: str):
    """The first text that names exactly one plausible election year gives it; a text naming several gives none."""
    for t in texts:
        ys = sorted(set(y for y in years_in(t) if 2001 <= y <= 2030))
        if len(ys) == 1:
            return ys[0]
    return None


def seat_of(*texts: str) -> str:
    for t in texts:
        if t and SEAT.search(t) and not EMPTY_CONTEXT.match(t.strip()):
            return t.strip()[:200]
    return ""


def clean_position(text: str) -> str:
    """Drop the year, the return's own words and a trailing size from a context line naming a seat."""
    t = SIZE.sub(" ", text or "")
    t = re.sub(r"\b(19|20)\d\d\b", " ", t)
    t = re.sub(r"\s[-–—:|]\s*(results?|candidates?|returns?)\s*$", " ", t, flags=re.I)
    t = re.sub(r"\b(electoral\s+)?donations?\s+and\s+expenses?(\s+returns?)?\b|\breturns?\b|\bcandidates?\b", " ", t, flags=re.I)
    t = re.sub(r"\s*[-–—:|]\s*$|^\s*[-–—:|]\s*", "", re.sub(r"\s+", " ", t)).strip(" -–—:|,")
    return t


SEAT_END = re.compile(r"(?i)^(.*\b(?:ward|constituency|community\s+board|local\s+board|subdivision|mayor(?:alty)?|"
                      r"licensing\s+trust|council))\b[\s,:–—-]+(.+)$")


def split_seat(words: str):
    """'KCDC Ōtaki General Ward KOFOED, Rob' → ('KCDC Ōtaki General Ward', 'KOFOED, Rob'); 'X stood for the Y Board'
    → ('the Y Board', 'X'); otherwise ('', words)."""
    w = SIZE.sub(" ", words or "").strip()
    m = re.match(r"(?i)^(.+?)\s+stood\s+for\s+(.+)$", w)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = SEAT_END.match(w)
    if m and re.search(r"[A-Za-zĀĒĪŌŪāēīōū]{2}", NAME_NOISE.sub(" ", m.group(2))):
        return m.group(1).strip(), m.group(2).strip()
    return "", w


NAME_LIKE = re.compile(r"^(?:[A-ZĀĒĪŌŪ][A-Za-zĀĒĪŌŪāēīōū'’.-]+|[A-ZĀĒĪŌŪ]{2,}|\([^)]{1,30}\)|,|&|and|van|de|der|du|te|ki|o)"
                       r"(?:\s+(?:[A-ZĀĒĪŌŪ][A-Za-zĀĒĪŌŪāēīōū'’.-]+|[A-ZĀĒĪŌŪ]{2,}|\([^)]{1,30}\)|,|&|and|van|de|der|du|te|ki|o)){1,5}$")
NOT_NAME = re.compile(r"(?i)\b(voting|votes?|results?|summary|document|declarations?|progress|daily|turnout|statistics|"
                      r"report|notice|preliminary|final|official|count|sheet|here|click|download|view|information|"
                      r"published|updated|date_range|page|"
                      r"jan|feb|mar|apr|jul|aug|sep|sept|oct|nov|dec|september|october|november|december)\b")


def looks_like_a_name(words: str) -> bool:
    w = re.sub(r"\s*,\s*", " , ", SIZE.sub(" ", words or "")).strip()
    return bool(NAME_LIKE.match(w)) and not NOT_NAME.search(w) and not SEAT.search(w)


MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
MONTH_DATE = re.compile(rf"(?i)\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}\.?(?:\s+\d{{4}})?|{MONTH}\.?\s+\d{{4}})\b|\b(?:december|november|october)\b")


def name_from_words(words: str) -> str:
    t = MONTH_DATE.sub(" ", SIZE.sub(" ", words or ""))
    t = re.sub(r"\d[\d,.%]*", " ", t)
    t = re.split(r"\s[-–—:|]\s|\s[-–—]|[-–—]\s", t, maxsplit=1)[0] if re.search(r"\s[-–—:|]\s|\s[-–—]|[-–—]\s", t) else t
    t = NAME_NOISE.sub(" ", t)
    t = re.sub(r"\(\s*\)|\[\s*\]|\([^)]*$|^[^(]*\)", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -–—:|,._")


def name_from_address(url: str, council_words: tuple = ()) -> str:
    stem = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    stem = re.sub(r"\.[a-z0-9]{2,4}$", "", stem, flags=re.I)
    t = re.sub(r"[_+%]|(?<=[a-z])-(?=[a-z])", " ", stem, flags=re.I)
    t = re.sub(r"\d+", " ", t)
    t = NAME_NOISE.sub(" ", t)
    for w in council_words:
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -_.")
    return split_seat(t)[1]


def kind_of(words: str) -> str:
    w = (words or "").lower()
    if re.search(r"\bnil\b", w):
        return "nil"
    d, e = bool(re.search(r"donation", w)), bool(re.search(r"expens|expenditure", w))
    if d and not e:
        return "donations"
    if e and not d:
        return "expenses"
    return "donations and expenses"


def outline(page: bytes):
    """The page's main text in order: ('context', tag, text) and ('link', href, words) events."""
    s = page.decode("utf-8", "replace")
    m = re.search(r"<main\b|<article\b|id=[\"'](?:main|content|main-content|maincontent)[\"']", s, re.I)
    body = s[m.start():] if m else s
    body = SKIP_BLOCKS.sub(" ", body)
    events, open_ctx, open_a, row_start = [], None, None, 0
    for t in TAG.finditer(body):
        closing, tag, attrs = t.group(1) == "/", t.group(2).lower(), t.group(3)
        if tag in ("tr", "li", "p") and not closing:
            row_start = t.end()
        if tag == "a" and not closing:
            h = HREF.search(attrs)
            open_a = (html.unescape(h.group(2)).strip() if h else "", t.end(), t.start())
        elif tag == "a" and closing and open_a:
            href, start, a_at = open_a
            words = _text(body[start:t.start()])
            if href:
                # the words before the link in its own row, list item or paragraph: a results table's name cell
                events.append(("link", href, words, _text(body[row_start:a_at])[-200:] if row_start < a_at else ""))
            open_a = None
        elif tag in CONTEXT_TAGS and not closing and open_a is None:
            open_ctx = (tag, t.end())
        elif tag in CONTEXT_TAGS and closing and open_ctx and open_ctx[0] == tag:
            txt = _text(body[open_ctx[1]:t.start()])
            if txt and len(txt) <= 200:
                events.append(("context", tag, txt))
            open_ctx = None
    return events


def title_of(page: bytes) -> str:
    m = re.search(r"<title\b[^>]*>(.*?)</title>", page.decode("utf-8", "replace"), re.I | re.S)
    return _text(m.group(1)) if m else ""


def base_of(page: bytes, url: str) -> str:
    """The address a page's relative links are read against: its own `<base href>` where its head carries one
    (Kaipara's does: `uploads/…` under it is the site root's, not the page's folder's), else the page's address."""
    head = page[:65536].decode("utf-8", "replace")
    head = head[:m.start()] if (m := re.search(r"<body\b", head, re.I)) else head
    b = re.search(r"<base\b[^>]*\bhref\s*=\s*([\"'])(.*?)\1", head, re.I | re.S)
    return urllib.parse.urljoin(url, html.unescape(b.group(2)).strip()) if b and b.group(2).strip() else url


def read_listing(page: bytes, url: str, council: str, seed_year: int = None, council_words: tuple = ()) -> dict:
    """Rows, the files met that are not returns (by kind), and the listing pages it links (to follow)."""
    events = outline(page)
    base = base_of(page, url)
    title = title_of(page)
    h1 = next((e[2] for e in events if e[0] == "context" and e[1] == "h1"), "")
    host = urllib.parse.urlsplit(url).hostname or ""
    page_year = year_of(h1, title, urllib.parse.unquote(urllib.parse.urlsplit(url).path))
    stack = {}          # heading rank → text; a minor context (strong, button, …) at rank 7
    rows, not_returns, follow = [], {}, []
    for ev in events:
        if ev[0] == "context":
            tag, txt = ev[1], ev[2]
            rank = HEAD_RANK.get(tag, 7)
            if EMPTY_CONTEXT.match(txt):
                continue
            for r in [k for k in stack if k >= rank]:
                del stack[r]
            stack[rank] = txt
            continue
        href, words, before = ev[1], ev[2], ev[3]
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absu = safe_url(urllib.parse.urljoin(base, href))
        if not is_file(absu):
            if (urllib.parse.urlsplit(absu).hostname or "") == host and absu.split("#")[0] != url.split("#")[0]:
                if re.search(r"donation|expense", words, re.I) or (
                        RETURN_WORDS.search(words) and re.search(r"donation|expense|return", absu, re.I)
                        and not NOT_A_RETURN.search(words)):
                    follow.append(absu)
                elif "?path=" in absu and absu.startswith(url.split("?")[0]):
                    follow.append(absu)
            continue
        ctx = [stack[k] for k in sorted(stack, reverse=True)]       # nearest first
        addr = urllib.parse.unquote(urllib.parse.urlsplit(absu).path)
        under_returns = any(re.search(r"donation|expense|return", c, re.I) for c in ctx + [h1, title])
        says_return = bool(re.search(r"donation|expense|\breturn", words + " " + addr, re.I))
        nr = NOT_A_RETURN.search(words)
        if nr and (BLANK_FORM.search(words) or not re.search(r"\b(nil\s+)?return\b.*\b(donation|expense)", words, re.I)):
            kind = nr.group(1).lower()
            not_returns[kind] = not_returns.get(kind, 0) + 1
            continue
        if not (says_return or under_returns):
            not_returns["unrelated file"] = not_returns.get("unrelated file", 0) + 1
            continue
        year = year_of(words, addr) or seed_year or year_of(*ctx) or page_year
        file_words = re.search(r"\.(?:pdf|docx?|xlsx?)\b", words or "", re.I) is not None      # the link's words are the file's own name
        if file_words:
            words_for_name = re.sub(r"[_+]|(?<=[A-Za-zāēīōū])-(?=[A-Za-zāēīōū])", " ",
                                    re.split(r"\.(?:pdf|docx?|xlsx?)\b", words, flags=re.I)[0])
            words_for_name = re.sub(r"(?i)^\s*" + "|".join(map(re.escape, council_words or ("@@",))) + r"\b", " ", words_for_name)
        else:
            words_for_name = words
        seat_words, name_words = split_seat(words_for_name)
        addr_words = re.sub(r"[_+]|(?<=[a-zāēīōū])-(?=[a-zāēīōū])", " ", addr.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        position_line = seat_of(*ctx) or seat_words or seat_of(words) or split_seat(addr_words)[0]
        position = clean_position(position_line) if position_line else ""
        generic = not words or bool(GENERIC_WORDS.fullmatch(words.strip()))
        if generic:
            b_seat, b_name = split_seat(STATUS_WORDS.sub(" ", before))
            name = name_from_words(b_name)
            position = position or clean_position(b_seat)
            if not looks_like_a_name(name):
                name = next((c for c in ctx[:1] if looks_like_a_name(c)), "")
        else:
            name = name_from_words(name_words)
        if not name or len(name) < 3 or not re.search(r"[A-Za-zĀĒĪŌŪāēīōū]{2}", name):
            name = name_from_address(absu, council_words)
        name = re.sub(r"\s+", " ", STATUS_WORDS.sub(" ", name)).strip(" ,-")
        if not says_return and not looks_like_a_name(name):
            not_returns["unrelated file"] = not_returns.get("unrelated file", 0) + 1
            continue
        words_named_nobody = not generic and len(name_from_words(name_words)) < 3
        several = bool(words_named_nobody or not name or SEAT.search(name) or re.search(r"(?i)\b(all|candidates|returns|elections?|"
                                                                 r"results|wards?|\d)\b", name)
                       or name.lower() == position.lower())
        rows.append({
            "council": council, "election_year": year, "covers": "several candidates" if several else "one candidate",
            "by_election": bool(BY_ELECTION.search(" ".join([words] + ctx + [h1]))),
            "candidate_as_listed": "" if several else name, "position": position, "return_kind": kind_of(words or addr),
            "link_words": words[:300], "file_url": absu, "listing_url": url, "context": " › ".join(reversed(ctx))[:400],
        })
    return {"rows": rows, "not_returns": not_returns, "follow": sorted(set(follow)), "title": h1 or title}
