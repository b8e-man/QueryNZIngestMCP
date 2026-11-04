"""The lane's reading of the Building Practitioners Board's decisions list,
from profile `lbp-board-decisions-list-page` (proposed in
`profile-proposed.jsonl`; the integrator appends it at the merge). No model;
nothing fetched. The register of practitioners itself is held and has no
reading (capture.py says why).

A page is first recognised by its shape (`recognise`): the list's heading
"Displaying N of M results" and N `article.listing-item` blocks, each with a
`process-title` and a "Complaint number". A page that is not that shape is
set aside whole.

One decision row per item:

  key            `building_practitioners/decision/<complaint number>/<kind>`:
                 the Board's own complaint number and the decision's kind
                 from its title (`final`, `finalised-draft`, `not-upheld`, …),
                 never the practitioner's name
  practitioner   the name as the title publishes it and the LBP number, both
                 left off the lane's tables when the Board withholds them
                 ("[OMITTED]") or the item's summary records a suppression or
                 anonymisation direction: the row stays flagged `suppressed`,
                 and the name, number and addresses as printed are kept whole
                 in the private twin (`suppressed`, ruling 142)
  fields         region (the area the list publishes and nothing finer),
                 licence classes, decision date, penalties (s 318 orders),
                 disciplinary grounds (s 317), whether any ground was upheld,
                 the decision's page and PDF address (withheld with the name,
                 because both carry it)

The summary is read for the suppression flag, and kept whole in the private
twin (`summaries`, keyed by the decision; ruling 142): it can name a
property or a complainant.

Every line this module prints is a count.
"""
import datetime as dt
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profile-proposed.jsonl")
PROFILE = "lbp-board-decisions-list-page"
READER = "registers.building_practitioners.read 2"
KEY_PREFIX = "building_practitioners/decision"
BASE = "https://www.lbp.govt.nz"

_ITEM = re.compile(rb'<article class="listing-item processlist-item".*?</article>', re.S)
_TOTAL = re.compile(r"Displaying\s*<span[^>]*>\s*(\d+)\s*</span>\s*of\s*(\d+)\s*results", re.I)
_TITLE = re.compile(r'<a class="process-link" href="([^"]+)">\s*<h3 class="process-title">(.*?)</h3>', re.S)
_LI = re.compile(r'<li class="process-item[^"]*">(.*?)</li>', re.S)
_TERM = re.compile(r'<span class="process-term">(.*?)</span>', re.S)
_VALUE = re.compile(r'<span class="process-value[^"]*">(.*?)</span>', re.S)
_PDF = re.compile(r'<a class="process-pdf" href="([^"]+)"')
_HEAD = re.compile(r"^(?P<name>.*?)\s*\[(?P<year>\d{4})\]\s*BPB\s*(?:[A-Z]{1,3})?(?P<number>\d+)(?:\s*[–—-]\s*(?P<kind>.+?))?\s*$", re.I)
OMITTED = re.compile(r"\[\s*omitted\s*\]|^omitted$", re.I)
SUPPRESSION = re.compile(r"suppress|must not be published|anonymis|anonymiz|not to be published|name.{0,20}withheld", re.I)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}


def profile_version() -> int:
    from support import profiles
    p = profiles.profile(PROFILE) or profiles.profile(PROFILE, path=PROPOSED)
    if p is None:
        raise LookupError(f"no profile {PROFILE}: a reading is made from a profile (profiles before readers)")
    return int(p["version"])


def clean(s):
    if s is None:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def count_items(body: bytes) -> int:
    return len(_ITEM.findall(body))


def recognise(body: bytes):
    """(stated (shown, total), '') when the page is the profile's shape, else (None, why)."""
    try:
        t = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not UTF-8 text"
    m = _TOTAL.search(t)
    if not m:
        return None, "no 'Displaying N of M results' heading"
    shown, total = int(m.group(1)), int(m.group(2))
    items = _ITEM.findall(body)
    if len(items) != shown:
        return None, f"the heading says {shown} shown and the page holds {len(items)} items"
    for it in items:
        s = it.decode("utf-8")
        if not _TITLE.search(s) or "Complaint number" not in s:
            return None, "an item with no title or no complaint number"
    return (shown, total), ""


def day(v):
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", v or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def kind_slug(kind: str) -> str:
    k = re.sub(r"\bdecision\b", "", kind.lower())
    return re.sub(r"[^a-z0-9]+", "-", k).strip("-") or "decision"


def read_item(raw: bytes, sha: str, version: int):
    """(row, '') or (None, why). `why` names what is missing."""
    s = raw.decode("utf-8")
    m = _TITLE.search(s)
    title = clean(m.group(2)) if m else None
    href = m.group(1) if m else None
    fields = {}
    for li in _LI.findall(s):
        t = _TERM.search(li)
        if t:
            fields[clean(t.group(1)).rstrip(":").strip().lower()] = [clean(v) for v in _VALUE.findall(li) if clean(v)]
    one = lambda k: (fields.get(k) or [None])[0]
    number = one("complaint number")
    if not number:
        return None, "no complaint number"
    head = _HEAD.match(title or "")
    if not head:
        return None, "a title not of the form '<name> [YYYY] BPB <number>[ – <kind>]'"
    decided = day(one("decision date"))
    if one("decision date") and decided is None:
        return None, "a decision date that is not a day"
    name = head.group("name").strip() or None
    lbp = one("lbp number")
    summary = " ".join(fields.get("summary") or [])
    suppressed = bool((name and OMITTED.search(name)) or (lbp and OMITTED.search(lbp)) or SUPPRESSION.search(summary)
                      or not name)
    grounds = fields.get("disciplinary grounds") or []
    pdf = _PDF.search(s)
    kind = head.group("kind") or "decision"          # a title may give no kind ("<name> [2025] BPB 26862"), and older
    #                                                  ones write the number with its complaint prefix ("BPB CB26720")
    return {
        "key": f"{KEY_PREFIX}/{number}/{kind_slug(kind)}", "complaint_number": number,
        "citation": f"[{head.group('year')}] BPB {head.group('number')}", "decision_kind": kind,
        "name": None if suppressed else name, "lbp_number": None if suppressed or (lbp and OMITTED.search(lbp)) else lbp,
        "suppressed": suppressed, "region": None if (one("region") or "").lower() == "omitted" else one("region"),
        "licence_classes": [c.strip(" ,") for c in fields.get("licence class") or [] if c.strip(" ,")], "decided_on": decided,
        "penalties": fields.get("penalty") or [], "grounds": grounds,
        "upheld": any(not g.lower().endswith("not upheld") for g in grounds) if grounds else None,
        "decision_url": BASE + href if href else None, "pdf_url": (BASE + pdf.group(1)) if pdf else None,
        "document": sha, "page": 1, "place": f"complaint={number}", "read_from": "text", "reader": READER,
        "profile": PROFILE, "profile_version": version,
        "private": {"name": name, "lbp_number": lbp, "region": one("region"), "summary": summary or None,
                    "decision_url": BASE + href if href else None, "pdf_url": (BASE + pdf.group(1)) if pdf else None}}, ""


def read_page(body: bytes, sha: str, version: int) -> dict:
    """{'stated', 'rows', 'set_aside', 'items'}: every item a row or a catch-log line."""
    stated, why = recognise(body)
    if stated is None:
        return {"stated": None, "rows": [], "items": 0,
                "set_aside": [{"document": sha, "place": "page", "stage": "recognise", "reason": why}]}
    rows, asides = [], []
    items = _ITEM.findall(body)
    for i, it in enumerate(items):
        row, why = read_item(it, sha, version)
        if row is None:
            asides.append({"document": sha, "place": f"item[{i}]", "stage": "read", "reason": why})
        else:
            rows.append(row)
    return {"stated": stated, "rows": rows, "set_aside": asides, "items": len(items)}


def main(argv=None) -> int:
    from support.docstore.landing import read_bytes
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m registers.building_practitioners.read <sha256>")
        return 2
    out = read_page(read_bytes(argv[0]), argv[0], profile_version())
    print(f"building_practitioners: {argv[0][:12]}: stated {out['stated']}, items {out['items']}, rows "
          f"{len(out['rows'])}, suppressed {sum(r['suppressed'] for r in out['rows'])}, set aside {len(out['set_aside'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
