"""Identifying details a court document prints, gathered privately (Arthur,
3 November 2026: "we actually want to gather all that stuff too. any
identifying information"). Two sources, one table, `courts_private.identifiers`,
rebuilt at every load beside `withheld_names`; never in a `courts.` table a
view reads, never in a `pub.` view, never exported (hard limits 11, 15, 16).

Tranche 1, here: the details with a fixed shape, found in the text the lane
already holds (the text layer, the stored page readings, a case page's
text), no model. Tranche 2 adds the text reader's details per person
(model_read.py), the same table, `person` set to the `people` row's key.

A detail is kept once per document, kind and value as printed, at the first
page that prints it; `person` is NULL for a detail found by its shape (the
shape says what it is, not whose).

    find(texts)                    [(kind, value, page)]
    rows(sha, texts, doc, profile, version, now)   the table's rows for one document

Nothing here prints a value: the counts by kind are the only output.
"""
import re

READER = "registers.courts.identifiers 1"
#: the closed vocabulary of kinds, both sources; a model's kind outside it is `other`
KINDS = ("address", "po_box", "place_of_residence", "age", "date_of_birth", "occupation", "employer", "law_firm",
         "email", "phone", "company_number", "nzbn", "ird_number", "driver_licence", "vehicle_registration",
         "file_number", "relationship", "other")
#: the shape-found kinds (tranche 1)
SHAPE_KINDS = ("address", "po_box", "age", "date_of_birth", "email", "phone", "company_number", "nzbn", "ird_number",
               "driver_licence", "vehicle_registration")

_MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)"
_DATE = rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-](?:19|20)\d{{2}}|{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}})"
_STREET = (r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Place|Pl|Lane|Crescent|Cres|Terrace|Tce|Grove|Close|"
           r"Parade|Highway|Hwy|Boulevard|Way|Quay|Square|Esplanade|Rise|Heights|Mews|Glade|Track)")
#: each kind's patterns; the value is group 1 where the pattern has one, else the whole match
PATTERNS = {
    "email": [re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")],
    "phone": [
        re.compile(r"(?<![\w+/-])(\+64[ -]?\(?0?\)?[ -]?[2-9]\d?[ -]?\d{3,4}[ -]?\d{3,4})(?![\w/-])"),
        re.compile(r"(?<![\w/-])(\(0[3-9]\)[ -]?\d{3}[ -]?\d{4})(?![\w/-])"),
        re.compile(r"(?<![\w$/.,-])(0[3-9][ -]\d{3}[ -]\d{4})(?![\w/.,-]|,\d)"),
        re.compile(r"(?<![\w$/.,-])(02[0-9][ -]?\d{3,4}[ -]?\d{3,4})(?![\w/.,-])"),
        re.compile(r"(?<![\w$/.,-])(0(?:800|508)[ -]?\d{3}[ -]?\d{3,4})(?![\w/.,-])"),
        re.compile(r"\b(?:Ph|Phone|Tel|Telephone|Mobile|Mob|Cell)\.?\s*:?\s*(\+?\(?\d[\d ()-]{6,16}\d)", re.I),
    ],
    "nzbn": [re.compile(r"(?<!\d)(9429\d{9})(?!\d)")],
    "company_number": [re.compile(r"\b(?:company|co\.?)\s+(?:number|no\.?|#)\s*:?\s*(\d{4,8})(?!\d)", re.I)],
    "ird_number": [re.compile(r"\b(?:IRD|GST|tax file)\s+(?:number|no\.?)\s*:?\s*(\d{2,3}[- ]?\d{3}[- ]?\d{3})(?!\d)", re.I)],
    "date_of_birth": [re.compile(rf"\b(?:date of birth|D\.?O\.?B\.?|born on|born)\s*:?\s*(?:on\s+)?({_DATE})", re.I)],
    "age": [re.compile(r"\baged\s+(\d{1,3})\b(?!\s*(?:per\s*cent|%|percent))", re.I),
            re.compile(r"\b(\d{1,3})[- ]years?[- ]old\b", re.I),
            re.compile(r"\b(?:at|then|now)\s+(?:the\s+)?age\s+(?:of\s+)?(\d{1,3})\b", re.I)],
    "driver_licence": [re.compile(r"\bdriver'?s?\W{0,2}\s*licen[cs]e\s+(?:number|no\.?)\s*:?\s*([A-Z]{2}\d{6})\b", re.I)],
    "vehicle_registration": [re.compile(r"\b(?i:registration|reg\.?)[ ](?i:number|no\.?|plate)[ ]?:?[ ]?"
                                        r"((?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,6})\b")],
    "po_box": [re.compile(r"\b((?:P\.?[ ]?O\.?|Private|Freepost)[ ]+Box[ ]+\d{1,6}(?:[ ]*,[ ]*[A-Z][a-z]+(?:[ ][A-Z][a-z]+)?)?(?:[ ]*\d{4})?)")],
    "address": [re.compile(rf"(?<![\w/$.,-])((?:(?:Flat|Unit|Apartment|Level)[ ]\w{{1,4}},?[ ])?\d{{1,5}}[A-Za-z]?(?:/\d{{1,5}}[A-Za-z]?)?"
                           rf"[ ](?:[A-Z][a-zāēīōū'’]+[ ]){{1,3}}{_STREET}\b\.?(?:,[ ]?[A-Z][a-zāēīōū]+(?:[ ][A-Z][a-zāēīōū]+){{0,2}})?)")],
}


def _value(m) -> str:
    v = m.group(1) if m.re.groups else m.group(0)
    return re.sub(r"\s+", " ", v).strip(" ,.;:")


def _plausible(kind: str, value: str) -> bool:
    """The shape alone is not enough for a few kinds: an age a person can be, a phone number of NZ's lengths."""
    if kind == "age":
        return 0 < int(value) <= 120
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        return 8 <= len(digits) <= 12
    if kind == "address":
        # the paragraph number before a capitalised sentence ("12 The Court Road …" is still an address; "1990 Act" is not)
        return not re.match(r"^(?:1[89]|20)\d\d\s", value)
    return True


def find(texts: dict) -> list:
    """[(kind, value as printed, first page)]: each kind and value once per
    document, in page order. `texts` is {page: text}."""
    seen, out = set(), []
    for page in sorted(texts):
        text = texts[page] or ""
        for kind, pats in PATTERNS.items():
            for pat in pats:
                for m in pat.finditer(text):
                    v = _value(m)
                    if not v or not _plausible(kind, v):
                        continue
                    k = (kind, v.upper())
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append((kind, v, page))
    return out


COLUMNS = ("key", "person", "document", "kind", "value", "page", "place", "read_from", "reader", "model", "profile",
           "profile_version", "loaded_at")


def rows(sha256: str, texts: dict, profile: str, version: int, read_from: str, now: str) -> list:
    """The table's rows for one document's shape-found details, keyed
    `<sha256>/identifier/<n>`."""
    return [{"key": f"{sha256}/identifier/{n}", "person": None, "document": sha256, "kind": kind, "value": value,
             "page": page, "place": f"by shape, page {page}", "read_from": read_from or "text", "reader": READER,
             "model": None, "profile": profile, "profile_version": version, "loaded_at": now}
            for n, (kind, value, page) in enumerate(find(texts), 1)]
