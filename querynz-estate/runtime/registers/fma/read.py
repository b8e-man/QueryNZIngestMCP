"""The lane's reading of the Financial Markets Authority's warnings and
enforcement cases, from the profiles `fma-listing-page`,
`fma-warning-page` and `fma-enforcement-case-page` (version 1, proposed in
`profile-proposed.jsonl`; the integrator appends them at the merge). No
model; nothing fetched.

A page is first recognised by its shape. A listing page states its count
("726 results found") and lists its items; a warning or a case is the FMA's
registry-item page: a heading, a published date and a body. A page that is
not its shape is set aside whole.

One action row per item:

  key            `fma/warning/<slug>` or `fma/enforcement/<slug>`: the item's
                 page address on the FMA's site, its one identifier
  fields         the kind (warning, enforcement case), the heading, the date
                 published, the FMA's own one-line summary (the page's
                 description), each Act the body names by title, each
                 section the body states as "section N of the <Act>", and
                 for a case its latest timeline entry (the outcome as
                 published), its date as published ('17 June 2026' or
                 'March 2026') and the day where one is given

One party row per party the FMA names: on a warning, each value of an
"Entity Name", "Entity", "Name", "Company" or "Individual" field, split on
';'; where there is none, the heading's part before its dash ("Baliex
Limited – Suspected investment scam…"); where there is no dash, the heading
itself when it ends in a legal ending (the older warnings: "9999 Gold Mining
Corporation"); otherwise the warning names nobody the reading can see (a
topic alert: "Romance scam leads victims to fake banks"), and is counted. On a case,
the heading, split on ' and ' only between two names that each carry a
legal ending. A company number only where the page prints one beside the
name. A party is withheld (the row stays, the name is empty) where the FMA
writes it withheld, or where the page states a suppression and the party
carries no organisation word; then the heading, summary, outcome, address
and slug are left off the lane's own tables too. Where the page states a
suppression it prints the name all the same, and the name, and the heading,
summary, outcome, slug and address, are kept whole in the private twin
(`suppressed_names`, `suppressed_actions`, keyed by the rows' keys; ruling
142, 4 November 2026).

Every other labelled field a warning prints (Address, Website, Email(s),
Phone, Bank Name, Account Number and the rest) is kept whole in the private
twin (`warning_fields`: the label and the value as printed, keyed by the
action), never on the lane's own tables.
"""
import datetime as dt
import hashlib
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from keys.names import is_organisation  # noqa: E402

PROPOSED = os.path.join(HERE, "profile-proposed.jsonl")
LISTING_PROFILE = "fma-listing-page"
PAGE_PROFILE = {"warnings": "fma-warning-page", "enforcement": "fma-enforcement-case-page"}
PROFILE_VERSION = 2
READER = "registers.fma.read 2"
BASE = "https://www.fma.govt.nz"
PATHS = {"warnings": "/library/warnings-and-alerts/", "enforcement": "/about-us/enforcement/cases/"}
KINDS = {"warnings": "warning", "enforcement": "enforcement case"}
KEY_PART = {"warnings": "warning", "enforcement": "enforcement"}
PER_PAGE = 15

_COUNT = re.compile(r'<span class="results-list__count">\s*(\d+)\s*</span>\s*results found')
_ITEM = re.compile(r'<li class="search-results-semantic__result-item">(.*?)</li>', re.S)
_ITEM_DATE = re.compile(r'<span class="search-results-semantic__date">(.*?)</span>', re.S)
_H1 = re.compile(r'<h1 class="registry-item-page__heading-wrap--title-item">(.*?)</h1>', re.S)
_PUBLISHED = re.compile(r'<span class="published__text">(.*?)</span>', re.S)
_DESCRIPTION = re.compile(r'<meta name="description" content="([^"]*)"')
_BODY_START = 'registry-item-page__body-wrap-main"'
_BODY_END = "<!--/Elemental Area Main Ends-->"
_BLOCK = re.compile(r"<title>\s*(?:Just a moment|Attention Required|Access denied)", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_FIELD = re.compile(r"<strong>\s*([^<:]{1,40}?)\s*:?\s*(?:&nbsp;|\s)*</strong>\s*:?\s*(.*?)(?=<br|<strong|</p>|</li>|$)", re.S)
PARTY_FIELDS = ("entity name", "entity names", "entity", "entities", "name", "company", "company name", "individual")
_DASH = re.compile(r"\s+[–—-]\s+")
_TIMELINE = re.compile(r"<h2[^>]*>\s*Timeline\s*</h2>(.*?)(?=<h2|$)", re.S)
_WHEN = r"(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}"
_TL_MARK = re.compile(rf"<h3[^>]*>\s*({_WHEN})\s*</h3>|<p>\s*<strong>\s*({_WHEN})\s*</strong>\s*</p>")
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_ACT = re.compile(r"((?:[A-Z][\w'’()&-]*\s+){1,}(?:(?:and|at|of|the|for|on|in|to|&)\s+(?:[A-Z(][\w'’()&-]*\s+)+)*"
                  r"(?:Act|Regulations)(?:\s+\d{4})?)")
_SECTION = re.compile(r"\b(?:sections?|ss?)\.?\s+\d+[A-Z]*(?:\(\w+\))*(?:\s*(?:,|and|or)\s*\d+[A-Z]*(?:\(\w+\))*)*"
                      r"\s+of\s+the\s+((?:[A-Z][\w'’()&-]*\s+)(?:(?:[A-Z(][\w'’()&-]*|and|at|of|the|for|on|in|to|&)\s+)*?"
                      r"(?:Act|Regulations)(?:\s+\d{4})?)")
WITHHELD = re.compile(r"^\s*(?:withheld|\[?name withheld\]?|\[?redacted\]?|suppressed|\[?name suppressed\]?)\s*$", re.I)
SUPPRESSION = re.compile(r"name suppression|suppression order|suppressed|must not be published|not to be published", re.I)
LEGAL_ENDING = re.compile(r"\b(?:Limited|Ltd\.?|Incorporated|Inc\.?|LLC|LP|Corporation|Corp\.?|PLC|GmbH|Pty|Company|Trust|"
                          r"Council|Board|Authority)(?:\s*\([^)]*\))?\s*$", re.I)
_AND = re.compile(r"\s+(?:and|&)\s+")
_NUMBER_BESIDE = r"\s*\(\s*(?:NZBN|company number|company no\.?)\s*:?\s*(\d{6,13})\s*\)"


def clean(s: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", s or ""))).strip()


def date_of(s: str):
    s = clean(s)
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def list_url(name: str, n: int) -> str:
    return BASE + PATHS[name] + ("" if n <= 1 else f"?start={PER_PAGE * (int(n) - 1)}")


# ── the listing ───────────────────────────────────────────────────────────────

def recognise_listing(body: bytes) -> str:
    t = body.decode("utf-8", "replace")
    if _BLOCK.search(t[:4096]):
        return "a block page, not a listing"
    if not _COUNT.search(t):
        return "no 'N results found' on the page (not an FMA listing)"
    return ""


def read_listing(body: bytes, name: str) -> dict:
    """{'stated': N, 'items': [{'slug', 'url', 'card'}]}: the items in page order.
    `card` is the fingerprint: the date and the title as listed."""
    why = recognise_listing(body)
    if why:
        raise ValueError(why)
    t = body.decode("utf-8", "replace")
    link = re.compile(r'<h3>\s*<a href="(' + re.escape(PATHS[name]) + r'([^"/?#]+)/)"[^>]*>(.*?)</a>', re.S)
    items, seen = [], set()
    for it in _ITEM.findall(t):
        m = link.search(it)
        if not m or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        d = _ITEM_DATE.search(it)
        items.append({"slug": m.group(2), "url": BASE + m.group(1),
                      "card": f"{clean(d.group(1)) if d else ''}|{clean(m.group(3))}"})
    return {"stated": int(_COUNT.search(t).group(1)), "items": items}


# ── a warning or a case ───────────────────────────────────────────────────────

def recognise_page(body: bytes) -> str:
    t = body.decode("utf-8", "replace")
    if _BLOCK.search(t[:4096]):
        return "a block page, not an FMA item"
    if not _H1.search(t) or _BODY_START not in t or _BODY_END not in t:
        return "no registry-item heading and body (not an FMA warning or case)"
    return ""


def acts_named(text: str) -> list:
    """Each Act or set of Regulations the text names by title, in order; a
    title without its year is dropped where the same title is named with one."""
    out = []
    for m in _ACT.finditer(text):
        a = m.group(1).strip()
        if (re.search(r"\d{4}$", a) or len(a.split()) >= 3) and a not in out:
            out.append(a)
    return [a for a in out if re.search(r"\d{4}$", a) or not any(b.startswith(a + " ") for b in out)]


def sections_stated(text: str) -> list:
    out = []
    for m in _SECTION.finditer(text):
        s = _SPACE.sub(" ", m.group(0)).strip()
        if s not in out:
            out.append(s)
    return out


def split_and(name: str):
    bits = _AND.split(name)
    if len(bits) == 2 and all(LEGAL_ENDING.search(b) for b in bits):
        return [(b.strip(), "and between two legal names") for b in bits]
    return [(name.strip(), "as published")]


def party_names(body_html: str, title: str, list_name: str):
    """[(name, named_in, split_from)] as the FMA names them."""
    if list_name == "enforcement":
        return [(n, "heading", how) for n, how in split_and(title)]
    out = []
    for label, value in _FIELD.findall(body_html):
        if clean(label).lower() not in PARTY_FIELDS:
            continue
        values = [v.strip() for v in clean(value).split(";") if v.strip()]
        for v in values:
            out.append((v, f"field: {clean(label)}", "semicolon" if len(values) > 1 else "as published"))
    if out:
        return out
    parts = _DASH.split(title, maxsplit=1)
    if len(parts) == 2 and parts[0].strip():
        return [(n, "heading, before its dash", how) for n, how in split_and(parts[0])]
    if LEGAL_ENDING.search(title):
        return [(n, "heading", how) for n, how in split_and(title)]
    return []


def timeline_latest(body_html: str):
    """(text, when as published, the day where a day is given) of a case's
    latest timeline entry: its paragraphs, without the 'Related …' lines.
    A month alone ('March 2026') orders the entries and is never made a day."""
    tl = _TIMELINE.search(body_html)
    if not tl:
        return None, None, None
    marks = list(_TL_MARK.finditer(tl.group(1)))
    best = None
    for i, m in enumerate(marks):
        when = _SPACE.sub(" ", m.group(1) or m.group(2)).strip()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tl.group(1))
        chunk = re.split(r"<hr", tl.group(1)[m.end():end])[0]
        text = " ".join(x for x in (clean(p) for p in _P.findall(chunk)) if x and not x.lower().startswith("related"))
        if not text:
            continue
        day = date_of(when)
        try:
            order = (day.year, day.month, day.day) if day else (*dt.datetime.strptime(when, "%B %Y").timetuple()[:2], 0)
        except ValueError:
            continue
        if best is None or order > best[0]:
            best = (order, text, when, day)
    return (best[1], best[2], best[3]) if best else (None, None, None)


def read_page(body: bytes, sha: str, list_name: str, slug: str, url: str = None) -> dict:
    """{'action': row, 'parties': [rows], 'set_aside': [lines]} for one warning or case."""
    why = recognise_page(body)
    if why:
        return {"action": None, "parties": [], "set_aside": [{"document": sha, "place": f"{list_name}={slug}",
                                                               "stage": "recognise", "reason": why}]}
    t = body.decode("utf-8", "replace")
    title = clean(_H1.search(t).group(1))
    a, b = t.index(_BODY_START), t.index(_BODY_END)
    body_html = t[a:b]
    text = clean(body_html)
    cite = {"document": sha, "page": 1, "read_from": "text", "reader": READER, "profile": PAGE_PROFILE[list_name],
            "profile_version": PROFILE_VERSION}
    states_suppression = bool(SUPPRESSION.search(text))
    parties, private = [], []
    for i, (name, named_in, how) in enumerate(party_names(body_html, title, list_name), 1):
        printed = re.search(_NUMBER_BESIDE + r"\s*$", name)
        if printed:
            name = name[:printed.start()].strip()
        org = is_organisation(name)
        withheld_by = ("the FMA withholds the name" if WITHHELD.match(name)
                       else "the page states a suppression" if states_suppression and not (org and not _AND.search(name))
                       else None)
        number = (printed or re.search(re.escape(name) + _NUMBER_BESIDE, text)) if not withheld_by else None
        if withheld_by == "the page states a suppression":
            kept = printed or re.search(re.escape(name) + _NUMBER_BESIDE, text)
            private.append({"ordinal": i, "name": name, "company_number": kept.group(1) if kept else None,
                            "named_in": named_in, "suppressed_by": withheld_by, "place": f"parties[{i}]", **cite})
        parties.append({"ordinal": i, "name": None if withheld_by else name, "withheld": bool(withheld_by),
                        "withheld_by": withheld_by, "organisation": org and not withheld_by,
                        "company_number": number.group(1) if number else None, "named_in": named_in,
                        "split_from": how, "place": f"parties[{i}]", **cite})
    suppressed = any(p["withheld_by"] == "the page states a suppression" for p in parties)
    key_slug = f"withheld-{hashlib.sha256(slug.encode()).hexdigest()[:16]}" if suppressed else slug
    key = f"fma/{KEY_PART[list_name]}/{key_slug}"
    for p in parties + private:
        p.update(key=f"{key}/party/{p['ordinal']}", action_key=key)
    outcome, outcome_when, outcome_on = timeline_latest(body_html)
    desc = _DESCRIPTION.search(t)
    pub = _PUBLISHED.search(t)
    title_withheld = bool(WITHHELD.match(title)) or suppressed
    action = {"key": key, "kind": KINDS[list_name], "slug": None if suppressed else slug,
              "title": None if title_withheld else title, "title_withheld": title_withheld,
              "summary": None if suppressed or not desc else (html.unescape(desc.group(1)).strip() or None),
              "published_on": date_of(pub.group(1)) if pub else None,
              "acts": acts_named(text), "sections": sections_stated(text),
              "outcome": None if suppressed else outcome, "outcome_when": outcome_when, "outcome_on": outcome_on,
              "names_nobody": not parties,
              "url": None if suppressed else (url or BASE + PATHS[list_name] + slug + "/"),
              "place": "registry-item", **cite}
    kept_action = {"key": key, "slug": slug, "title": title,
                   "summary": (html.unescape(desc.group(1)).strip() or None) if desc else None, "outcome": outcome,
                   "url": url or BASE + PATHS[list_name] + slug + "/", "suppressed_by": "the page states a suppression",
                   "place": "registry-item", **cite} if suppressed else None
    fields = [] if list_name != "warnings" else [
        {"key": key, "ordinal": n, "label": clean(label), "value": clean(value), "place": f"field[{n}]", **cite}
        for n, (label, value) in enumerate(_FIELD.findall(body_html), 1)
        if clean(label).lower() not in PARTY_FIELDS and clean(value)]
    return {"action": action, "parties": parties, "set_aside": [], "suppressed_names": private,
            "suppressed_action": kept_action, "warning_fields": fields}
