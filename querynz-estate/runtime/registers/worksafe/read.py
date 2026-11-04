"""The lane's reading of WorkSafe New Zealand's court summaries and accepted
enforceable undertakings, from the profiles `worksafe-listing-page`,
`worksafe-court-summary` and `worksafe-enforceable-undertaking` (version 1,
proposed in `profile-proposed.jsonl`; the integrator appends them at the
merge). No model; nothing fetched; nothing inferred.

A page is first recognised by its shape. A listing page states its count
("Found 608 results") and lists its items; a court summary carries the
"Court Summary - at a glance" block and its label/value rows; an undertaking
carries its status, its date and an intro naming the duty holder. A page
that is not its shape is set aside whole.

One action row per item, the facts as the page states them:

  key            `worksafe/prosecution/<slug>` or `worksafe/undertaking/<slug>`:
                 the page's address on WorkSafe's site, its one identifier
  prosecution    the duty holder (the defendant), industry, the date of the
                 offence as stated (and the day where it is one day), the
                 section charged as stated with each Act it names, the date
                 charged, court, plea, the decision and its date, the fine
                 imposed as stated (and the figure only where the field
                 states one figure), the reparation as stated
  undertaking    the duty holder, status, the date published and the date
                 accepted, each section the alleged contravention states,
                 and each Act it names

One party row per duty holder as WorkSafe names it: the "Defendant name"
field, else the heading; split on ' and ' only between two names that each
carry a legal ending. A party is withheld (the row stays, the name is
empty) where WorkSafe writes the name withheld or suppressed, or publishes a
code in its place ('2019-A'), or where the page states a suppression and
the party is not one organisation alone; then the heading, slug and address
are left off the lane's own tables too. What the page prints in the name's
place (the name a stated suppression covers, the code, or the word
withheld) and the heading, slug and address are kept whole in the private
twin (`suppressed_names`, `suppressed_actions`, keyed by the rows' keys;
ruling 142, 4 November 2026).

Every labelled row the lane's tables do not read and every section the page
prints under its own heading (the facts in brief, the incident, the safety
lessons, the highlights and the rest, which describe the victims and the
place) is kept whole in the private twin (`page_sections`: heading and
text, keyed by the action).
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
LISTING_PROFILE = "worksafe-listing-page"
PAGE_PROFILE = {"prosecutions": "worksafe-court-summary", "undertakings": "worksafe-enforceable-undertaking"}
PROFILE_VERSION = 2
READER = "registers.worksafe.read 2"
BASE = "https://www.worksafe.govt.nz"
PATHS = {"prosecutions": "/laws-and-regulations/prosecutions/court-summaries/",
         "undertakings": "/laws-and-regulations/enforceable-undertakings/accepted-enforceable-undertakings/"}
KINDS = {"prosecutions": "prosecution", "undertakings": "enforceable undertaking"}
KEY_PART = {"prosecutions": "prosecution", "undertakings": "undertaking"}
PER_PAGE = 20

_COUNT = re.compile(r'<p class="result-summary[^"]*">\s*Found\s*<strong>\s*(\d+)\s*</strong>\s*results', re.S)
_ARTICLE = re.compile(r"<article\b(.*?)</article>", re.S)
_ITEM_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
_ITEM_STATUS = re.compile(r'<p class="status-tag"[^>]*>(.*?)</p>', re.S)
_MAIN = re.compile(r'id="main-page-content"[^>]*>(.*?)(?:<!-- // end main-page-content|<div id="page-utilities")', re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_ROW = re.compile(r'<div class="row">\s*<div class="label">(.*?)</div>\s*<div>(.*?)</div>\s*</div>', re.S)
_STATUS = re.compile(r'<p class="status-tag"[^>]*>(.*?)</p>', re.S)
_PUBLISHED = re.compile(r'<p class="publication-info">\s*<time datetime="([^"]+)"')
_INTRO = re.compile(r'<p class="intro">(.*?)</p>', re.S)
_SECTION_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|$)", re.S)
_GLANCE = "Court Summary - at a glance"
_BLOCK = re.compile(r"<title>\s*(?:Just a moment|Attention Required|Access denied)", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_ACT = re.compile(r"([A-Z][\w'’()&-]*\s+(?:(?:[A-Z(][\w'’()&-]*|and|at|of|the|for|on|in|to|&)\s+)*?"
                  r"(?:Act|Regulations)(?:\s+\d{4})?)")
_SECTIONS = re.compile(r"\b(?:sections?|ss?)\.?\s+\d+[A-Z]*(?:\(\w+\))*(?:\s*(?:,|and|or)\s*\d+[A-Z]*(?:\(\w+\))*)*"
                       r"(?:\s+(?:of\s+the\s+)?(?:[A-Z][\w'’()&-]*\s+)(?:(?:[A-Z(][\w'’()&-]*|and|at|of|the|for|on|in|to|&)\s+)*?"
                       r"(?:Act|Regulations)(?:\s+\d{4})?)?")
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|m)\b)?", re.I)
_ONE_DATE = re.compile(r"^\s*(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\s*$")
WITHHELD = re.compile(r"^\s*\[?\s*(?:name\s+)?(?:withheld|suppressed|redacted)\s*\]?\s*$|name suppress", re.I)
#: WorkSafe publishes a code in place of a defendant's name it does not publish ('2019-A')
CODE = re.compile(r"^\s*(?:19|20)\d{2}\s*-\s*[A-Z]{1,3}\s*$")
#: an Act the field names by its abbreviation only, as stated ('Sections 36(1)(a), 48(1) and 48(2)(c) of HSWA')
ABBREVIATIONS = re.compile(r"\b(HSWA|HSEA|HSE Act|HSNO Act|EA 1992)\b")
SUPPRESSION = re.compile(r"name suppression|suppression order|suppressed|must not be published|not to be published", re.I)
LEGAL_ENDING = re.compile(r"\b(?:Limited|Ltd\.?|Incorporated|Inc\.?|LLC|LP|Corporation|Corp\.?|PLC|GmbH|Pty|Company|Trust|"
                          r"Council|Board|Authority)(?:\s*\([^)]*\))?\s*$", re.I)
_AND = re.compile(r"\s+(?:and|&)\s+")
_NUMBER_BESIDE = r"\s*\(\s*(?:NZBN|company number|company no\.?)\s*:?\s*(\d{6,13})\s*\)"


def clean(s: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", s or ""))).strip()


def lines(s: str) -> str:
    """A field's text with its line breaks kept as '; ' (an offence section lists one defendant a line)."""
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "", flags=re.I)
    return "; ".join(x for x in (clean(l) for l in s.split("\n")) if x)


def date_of(s: str):
    s = clean(s)
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d"):
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
        return "no 'Found N results' on the page (not a WorkSafe listing)"
    return ""


def read_listing(body: bytes, name: str) -> dict:
    """{'stated': N, 'items': [{'slug', 'url', 'card'}]}: the items in page order.
    `card` is the fingerprint: the date, the title and the status as listed."""
    why = recognise_listing(body)
    if why:
        raise ValueError(why)
    t = body.decode("utf-8", "replace")
    link = re.compile(r'<a href="(' + re.escape(PATHS[name]) + r'([^"/?#]+)/)"[^>]*itemprop="url"[^>]*>(.*?)</a>', re.S)
    items, seen = [], set()
    for art in _ARTICLE.findall(t):
        m = link.search(art)
        if not m or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        when, status = _ITEM_TIME.search(art), _ITEM_STATUS.search(art)
        items.append({"slug": m.group(2), "url": BASE + m.group(1),
                      "card": "|".join((when.group(1) if when else "", clean(m.group(3)), clean(status.group(1)) if status else ""))})
    return {"stated": int(_COUNT.search(t).group(1)), "items": items}


# ── a court summary or an undertaking ─────────────────────────────────────────

def recognise_page(body: bytes, name: str = None) -> str:
    t = body.decode("utf-8", "replace")
    if _BLOCK.search(t[:4096]):
        return "a block page, not a WorkSafe item"
    main = _MAIN.search(t)
    if not main or not _H1.search(t):
        return "no main page content and heading (not a WorkSafe item)"
    glance = _GLANCE in main.group(1)
    if name == "prosecutions" and not glance:
        return "no 'Court Summary - at a glance' block (not a court summary)"
    if name == "undertakings" and not (_PUBLISHED.search(main.group(1)) and _INTRO.search(main.group(1))):
        return "no date and intro (not an enforceable undertaking)"
    if name is None and not glance and not _INTRO.search(main.group(1)):
        return "neither a court summary nor an enforceable undertaking"
    return ""


def acts_named(text: str) -> list:
    """Each Act the text names by title, in order; where it names none, each
    abbreviation it uses for one, as stated ('HSWA'), never expanded."""
    out = []
    for m in _ACT.finditer(text or ""):
        a = m.group(1).strip()
        if a not in out:
            out.append(a)
    out = [a for a in out if re.search(r"\d{4}$", a) or not any(b.startswith(a + " ") for b in out)]
    if not out:
        for m in ABBREVIATIONS.finditer(text or ""):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out


def sections_stated(text: str) -> list:
    out = []
    for m in _SECTIONS.finditer(text or ""):
        s = _SPACE.sub(" ", m.group(0)).strip()
        if s not in out:
            out.append(s)
    return out


def split_and(name: str):
    bits = _AND.split(name)
    if len(bits) == 2 and all(LEGAL_ENDING.search(b) for b in bits):
        return [(b.strip(), "and between two legal names") for b in bits]
    return [(name.strip(), "as published")]


#: the label/value rows the lane's own tables read; every other row is kept whole in the private twin (ruling 142)
READ_LABELS = frozenset({"defendant name", "industry", "date of offence", "offence section", "date(s) charged", "court",
                         "plea", "final decision date", "decision", "fine imposed", "reparation"})


def fields(main_html: str) -> dict:
    """The label/value rows, lower-cased labels, first occurrence wins (the
    at-a-glance block repeats the long form's values)."""
    out = {}
    for label, value in _ROW.findall(main_html):
        k = clean(label).rstrip(":").strip().lower()
        if k and k not in out:
            out[k] = value
    return out


def h2_sections(main_html: str) -> dict:
    return {clean(h).lower(): body for h, body in _SECTION_H2.findall(main_html)}


def one_figure(text: str):
    """The figure only where the field states exactly one ('$60,000'); a field
    with a starting point, a split or instalments states several, and none is chosen."""
    found = _MONEY.findall(text or "")
    if len(found) != 1 or re.search(r"million|\bm\b", found[0], re.I):
        return None
    return float(re.sub(r"[^\d.]", "", found[0]))


def read_page(body: bytes, sha: str, list_name: str, slug: str, url: str = None) -> dict:
    """{'action': row, 'parties': [rows], 'set_aside': [lines]} for one court summary or undertaking."""
    why = recognise_page(body, list_name)
    if why:
        return {"action": None, "parties": [], "set_aside": [{"document": sha, "place": f"{list_name}={slug}",
                                                               "stage": "recognise", "reason": why}]}
    t = body.decode("utf-8", "replace")
    main = _MAIN.search(t).group(1)
    title = clean(_H1.search(t).group(1))
    cite = {"document": sha, "page": 1, "read_from": "text", "reader": READER, "profile": PAGE_PROFILE[list_name],
            "profile_version": PROFILE_VERSION}
    f = fields(main)
    sec = h2_sections(main)
    states_suppression = bool(SUPPRESSION.search(clean(main)))
    named = clean(f.get("defendant name", ""))
    parties, private = [], []
    for i, (name, how) in enumerate(split_and(named or title), 1):
        printed = re.search(_NUMBER_BESIDE + r"\s*$", name)
        if printed:
            name = name[:printed.start()].strip()
        org = is_organisation(name)
        withheld_by = ("WorkSafe withholds the name" if WITHHELD.search(name)
                       else "WorkSafe publishes a code in place of the name" if CODE.match(name)
                       else "the page states a suppression" if states_suppression and not (org and not _AND.search(name))
                       else None)
        number = (printed or re.search(re.escape(name) + _NUMBER_BESIDE, clean(main))) if not withheld_by else None
        if withheld_by:
            kept = printed or re.search(re.escape(name) + _NUMBER_BESIDE, clean(main))
            private.append({"ordinal": i, "name": name, "company_number": kept.group(1) if kept else None,
                            "named_in": "field: Defendant name" if named else "heading", "suppressed_by": withheld_by,
                            "place": f"parties[{i}]", **cite})
        parties.append({"ordinal": i, "name": None if withheld_by else name, "withheld": bool(withheld_by),
                        "withheld_by": withheld_by, "organisation": org and not withheld_by,
                        "company_number": number.group(1) if number else None,
                        "named_in": "field: Defendant name" if named else "heading", "split_from": how,
                        "place": f"parties[{i}]", **cite})
    suppressed = any(p["withheld"] for p in parties) or bool(WITHHELD.search(title) or CODE.match(title))
    key_slug = f"withheld-{hashlib.sha256(slug.encode()).hexdigest()[:16]}" if suppressed else slug
    key = f"worksafe/{KEY_PART[list_name]}/{key_slug}"
    for p in parties + private:
        p.update(key=f"{key}/party/{p['ordinal']}", action_key=key)
    offence_when = lines(f.get("date of offence", "")) or None
    charged = lines(f.get("date(s) charged", "")) or None
    decided = f.get("final decision date", "")
    decided_iso = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', decided)
    section = lines(f.get("offence section", "")) or None
    published = _PUBLISHED.search(main)
    accepted = clean(sec.get("date accepted", "")) or None
    status = _STATUS.search(main)
    fine = lines(f.get("fine imposed", "")) or None
    contravention = clean(sec.get("alleged contravention", ""))
    action = {"key": key, "kind": KINDS[list_name], "slug": None if suppressed else slug,
              "title": None if suppressed else title, "title_withheld": suppressed,
              "industry": clean(f.get("industry", "")) or None,
              "offence_when": offence_when,
              "offence_on": date_of(_ONE_DATE.match(offence_when).group(1)) if offence_when and _ONE_DATE.match(offence_when) else None,
              "section_charged": section, "acts": acts_named(section if list_name == "prosecutions" else contravention),
              "sections": sections_stated(contravention) if list_name == "undertakings" else [],
              "charged_when": charged,
              "charged_on": date_of(_ONE_DATE.match(charged).group(1)) if charged and _ONE_DATE.match(charged) else None,
              "court": clean(f.get("court", "")) or None, "plea": clean(f.get("plea", "")) or None,
              "decision": clean(f.get("decision", "")) or None,
              "decided_on": date_of(decided_iso.group(1)) if decided_iso else date_of(decided),
              "fine_text": fine, "fine_amount": one_figure(fine),
              "reparation_text": lines(f.get("reparation", "")) or None,
              "status": clean(status.group(1)) if status else None,
              "published_on": date_of(published.group(1)[:10]) if published else None,
              "accepted_on": date_of(accepted) if accepted else None,
              "url": None if suppressed else (url or BASE + PATHS[list_name] + slug + "/"),
              "place": "court-summary" if list_name == "prosecutions" else "undertaking", **cite}
    action["action_on"] = action["decided_on"] or action["accepted_on"] or action["published_on"]
    kept_action = {"key": key, "slug": slug, "title": title, "url": url or BASE + PATHS[list_name] + slug + "/",
                   "suppressed_by": "; ".join(sorted({p["suppressed_by"] for p in private})) or "WorkSafe withholds the heading",
                   "place": action["place"], **cite} if suppressed else None
    unread = [(k, v, "row") for k, v in f.items() if k not in READ_LABELS]
    unread += [(h, b, "h2") for h, b in _SECTION_H2.findall(main)]
    sections = [{"key": key, "ordinal": n, "heading": clean(h), "text": clean(b), "place": f"{where}[{n}]", **cite}
                for n, (h, b, where) in enumerate(unread, 1) if clean(b)]
    return {"action": action, "parties": parties, "set_aside": [], "suppressed_names": private,
            "suppressed_action": kept_action, "page_sections": sections}
