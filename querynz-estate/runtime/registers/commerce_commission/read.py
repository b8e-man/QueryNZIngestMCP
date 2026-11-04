"""The lane's reading of the Commerce Commission's case register, from the
profiles `comcom-case-register-listing` and `comcom-case-register-entry`
(version 1, proposed in `profile-proposed.jsonl`; the integrator appends them
at the merge). No model; nothing fetched.

A page is first recognised by its shape. A listing page carries the
register's own count (`:total="N"`) and its cards; an entry carries the
"Case Details" block. A page that is not its shape is set aside whole.

One case row per entry:

  key            `commerce_commission/case/<slug>`: the entry's page address
                 on the Commission's site, which is its one identifier on
                 every entry (the case number is empty on the oldest)
  fields         the case number, the title (the parties as the heading
                 publishes them, or 'Withheld'), category and sub-category
                 (the kind), the Act and section as stated, split into each
                 Act and its sections, industry, status, the outcome as
                 published, the dates opened and closed

One party row per party the Parties field names, as the Commission publishes
it: split on '; ', and on ' and ' only between two names that each carry a
legal ending; otherwise the field is one party. A trading name after 't/a'
is kept beside its party; a company number only where the page prints one
beside the name. A party is withheld on the lane's own tables (the row
stays, the name is empty) where the Commission writes 'Withheld', or where
the page states a suppression and the party carries no organisation word.
Where the page states a suppression the name is printed all the same and is
kept whole (ruling 142, 4 November 2026): the party's name, trading name and
company number, and the case's slug, heading and page address, go to the
lane's private twin (`suppressed_names`, `suppressed_cases`, keyed by the
party's and the case's keys), flagged with what the page states. Where the
Commission writes 'Withheld' it prints no name; the flag is what it gives.

The contact person the entry prints (Commission staff: a name and an
email) is kept whole in the private twin (`contacts`, keyed by the case).
The summary paragraph and the timeline are not read.
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
LISTING_PROFILE = "comcom-case-register-listing"
ENTRY_PROFILE = "comcom-case-register-entry"
PROFILE_VERSION = 2
READER = "registers.commerce_commission.read 2"
KEY_PREFIX = "commerce_commission/case"
BASE = "https://www.comcom.govt.nz"
ENTRY_PATH = "/case-register/case-register-entries/"

_TOTAL = re.compile(r':total="(\d+)"')
_CARD = re.compile(r'<div class="card card--has-link">(.*?)</li>', re.S)
_CARD_LINK = re.compile(r'<a class="card__link" href="(/case-register/case-register-entries/([a-z0-9-]+)/)"\s*>(.*?)</a>', re.S)
_CARD_STATUS = re.compile(r'card__status--([a-z-]+)')
_CARD_INFO = re.compile(r'<span class="card__info-title">([^<]*)</span>\s*<span>(.*?)</span>', re.S)
_CARD_TAG = re.compile(r'<div class="card__tag">(.*?)</div>', re.S)
_DETAILS = re.compile(r'<h2 class="h5">Case Details</h2>\s*<div class="case-details">(.*?)</div>\s*(?:<project-block|<script|</div>\s*</div>|$)', re.S)
_RECORD = re.compile(r'case-details__record-title">\s*(.*?)\s*</div>\s*<div class="case-details__record-value">\s*(.*?)\s*</div>', re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_BLOCK = re.compile(r"<title>\s*(?:Just a moment|Attention Required|Access denied)", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
WITHHELD = re.compile(r"^\s*(?:withheld|\[?name withheld\]?|\[?redacted\]?|suppressed)\s*$", re.I)
SUPPRESSION = re.compile(r"name suppression|suppression order|suppressed|must not be published|not to be published", re.I)
LEGAL_ENDING = re.compile(r"(?:Limited|Ltd\.?|Incorporated|Inc\.?|LLC|Corporation|Corp\.?|PLC|GmbH|Pty|Company|Trust|"
                          r"Council|Board|Authority)(?:\s*\([^)]*\))?\s*$", re.I)
_AND = re.compile(r"\s+(?:and|&)\s+")
_TA = re.compile(r"\s+(?:t/a|trading as)\s+", re.I)
_ACT = re.compile(r"([A-Z][\w'’()&-]*\s+(?:(?:[A-Z(][\w'’()&-]*|and|at|of|the|for|on|in|to|&)\s+)*?"
                  r"(?:Act|Regulations|Code|Rules|Order)(?:\s+\d{4})?)")
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


# ── the listing ───────────────────────────────────────────────────────────────

def recognise_listing(body: bytes) -> str:
    """'' when the page is a listing page of the case register, else why not."""
    t = body.decode("utf-8", "replace")
    if _BLOCK.search(t[:4096]):
        return "a block page, not a listing"
    if not _TOTAL.search(t):
        return "no :total on the page (not the case register listing)"
    return ""


def read_listing(body: bytes) -> dict:
    """{'stated': N, 'items': [{'slug', 'url', 'card'}]}: the cards in page order.
    `card` is the fingerprint: status, outcome, date closed and tag as listed."""
    why = recognise_listing(body)
    if why:
        raise ValueError(why)
    t = body.decode("utf-8", "replace")
    items, seen = [], set()
    for c in _CARD.findall(t):
        link = _CARD_LINK.search(c)
        if not link:
            continue
        path, slug = link.group(1), link.group(2)
        if slug in seen:
            continue
        seen.add(slug)
        status = _CARD_STATUS.search(c)
        info = {clean(k).rstrip(":").lower(): clean(v) for k, v in _CARD_INFO.findall(c)}
        tag = "; ".join(clean(x) for x in _CARD_TAG.findall(c))
        card = "|".join((status.group(1) if status else "", info.get("outcome", ""), info.get("date closed", ""), tag))
        items.append({"slug": slug, "url": BASE + path, "card": card})
    return {"stated": int(_TOTAL.search(t).group(1)), "items": items}


# ── an entry ──────────────────────────────────────────────────────────────────

def recognise_entry(body: bytes) -> str:
    t = body.decode("utf-8", "replace")
    if _BLOCK.search(t[:4096]):
        return "a block page, not an entry"
    if not _DETAILS.search(t):
        return "no Case Details block (not a case register entry)"
    return ""


def acts_and_sections(stated: str):
    """'Commerce Act 1986 ss 30, 80(1); Fair Trading Act 1986 s 9' →
    (['Commerce Act 1986', 'Fair Trading Act 1986'], ['ss 30, 80(1)', 's 9']).
    Only what the field states: an Act's title and the words after it."""
    acts, sections = [], []
    text = (stated or "").strip()
    found = list(_ACT.finditer(text))
    for i, m in enumerate(found):
        acts.append(m.group(1).strip())
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        sections.append(text[m.end():end].strip(" ;,") or None)
    return acts, sections


def split_parties(field: str):
    """[(name, split_from)]: the Commission's own separators only."""
    field = (field or "").strip()
    if not field:
        return []
    parts = [p.strip() for p in field.split(";") if p.strip()]
    how = "semicolon" if len(parts) > 1 else "as published"
    out = []
    for p in parts:
        bits = _AND.split(p)
        if len(bits) == 2 and all(LEGAL_ENDING.search(b) for b in bits) and not _TA.search(p):
            out += [(b.strip(), "and between two legal names") for b in bits]
        else:
            out.append((p, how))
    return out


def read_entry(body: bytes, sha: str, slug: str, url: str = None) -> dict:
    """{'case': row, 'parties': [rows], 'set_aside': [lines]} for one entry."""
    why = recognise_entry(body)
    if why:
        return {"case": None, "parties": [], "set_aside": [{"document": sha, "place": f"entry={slug}", "stage": "recognise",
                                                             "reason": why}]}
    t = body.decode("utf-8", "replace")
    rec = {clean(k).lower(): clean(v) for k, v in _RECORD.findall(_DETAILS.search(t).group(0))}
    h1 = _H1.search(t)
    title = clean(h1.group(1)) if h1 else rec.get("parties", "")
    cite = {"document": sha, "page": 1, "read_from": "text", "reader": READER, "profile": ENTRY_PROFILE,
            "profile_version": PROFILE_VERSION}
    details = _DETAILS.search(t)
    states_suppression = bool(SUPPRESSION.search(clean(t[h1.start() if h1 else 0:details.end()])))
    parties, private = [], []
    for i, (name, how) in enumerate(split_parties(rec.get("parties", "")), 1):
        name, trading = (_TA.split(name, maxsplit=1) + [""])[:2]
        printed = re.search(_NUMBER_BESIDE + r"\s*$", name)
        if printed:
            name = name[:printed.start()]
        org = is_organisation(name)
        withheld_by = ("the Commission withholds the name" if WITHHELD.match(name)
                       else "the page states a suppression" if states_suppression and not (org and not _AND.search(name))
                       else None)
        number = (printed or re.search(re.escape(name.strip()) + _NUMBER_BESIDE, t)) if not withheld_by else None
        if withheld_by == "the page states a suppression":
            kept = re.search(re.escape(name.strip()) + _NUMBER_BESIDE, t) if not printed else printed
            private.append({"ordinal": i, "name": name.strip(), "trading_as": trading.strip() or None,
                            "company_number": kept.group(1) if kept else None, "suppressed_by": withheld_by,
                            "place": f"parties[{i}]", **cite})
        parties.append({"ordinal": i, "name": None if withheld_by else name.strip(),
                        "trading_as": None if withheld_by else (trading.strip() or None),
                        "withheld": bool(withheld_by), "withheld_by": withheld_by,
                        "organisation": org and not withheld_by, "company_number": number.group(1) if number else None,
                        "split_from": how, "place": f"parties[{i}]", **cite})
    # a name withheld for a suppression is in the heading, the page address and the slug too: on the lane's own tables
    # none of them is shown, and the key is made from the slug's hash, which is stable across re-reads and names nobody;
    # all three are kept in the private twin under that key (ruling 142)
    suppressed = any(p["withheld_by"] == "the page states a suppression" for p in parties)
    key = f"{KEY_PREFIX}/withheld-{hashlib.sha256(slug.encode()).hexdigest()[:16]}" if suppressed else f"{KEY_PREFIX}/{slug}"
    for p in parties + private:
        p.update(key=f"{key}/party/{p['ordinal']}", case_key=key)
    acts, sections = acts_and_sections(rec.get("act/section/part"))
    opened, closed = date_of(rec.get("date opened", "")), date_of(rec.get("date closed", ""))
    title_withheld = bool(WITHHELD.match(title)) or suppressed
    case = {"key": key, "slug": None if suppressed else slug, "case_number": rec.get("case number") or None,
            "title": None if title_withheld else title, "title_withheld": title_withheld,
            "category": rec.get("category") or None, "sub_category": rec.get("sub-category") or None,
            "act_section": rec.get("act/section/part") or None, "acts": acts, "sections": sections,
            "industry": rec.get("industry") or None, "status": rec.get("status") or None,
            "outcome": rec.get("outcome") or None, "opened_on": opened, "closed_on": closed,
            "action_on": closed or opened, "url": None if suppressed else (url or f"{BASE}{ENTRY_PATH}{slug}/"),
            "place": "case-details", **cite}
    asides = [] if parties else [{"document": sha, "place": f"entry={case['slug'] or key}", "stage": "parties",
                                  "reason": "the Parties field is empty"}]
    kept_case = {"key": key, "slug": slug, "title": title, "url": url or f"{BASE}{ENTRY_PATH}{slug}/",
                 "suppressed_by": "the page states a suppression", "place": "case-details", **cite} if suppressed else None
    contact = ({"key": key, "contact": rec["contact person"], "place": "case-details/contact person", **cite}
               if rec.get("contact person") else None)
    return {"case": case, "parties": parties, "set_aside": asides, "suppressed_names": private,
            "suppressed_case": kept_case, "contact": contact}
