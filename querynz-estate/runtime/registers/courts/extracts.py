"""What the courts lane's code produces, profile by profile, and what each document has had extracted (Arthur, 3
November 2026: "the lane asks for something and the profile provides something. we need to ensure that these
somethings are aligned").

The fields come from the code that makes them, never a second list: the caption grammar's are `caption.FIELDS` (its
Judgment dataclass, the diagnostics apart); the case page grammar's `read.CASE_FIELDS`; a sheet's the keys `read.sheet`
returns; the text reader's `model_read.FIELDS` (pinned to `parse_answer`); the pattern pass's one field,
`identifiers`, whose kinds are `identifiers.SHAPE_KINDS`; the page reader's `page_text`. The tables are the load's
column lists (`load.COLUMNS` and the rest). `support/profiles/align.py` holds them to each profile's extract list.

    produces(slug)             {field: (by, kinds)}
    LANE                       the lane as align.py reads it
    problems()                 align.problems for the lane
    where(schema, shared)      a lane table → (schema, table) in that database
    extracted(documents)       the docs.extractions rows for a load's documents rows
"""
from support import profiles as pr
from support.profiles import align
from registers.courts import caption, identifiers, model_read
from registers.courts import load as L
from registers.courts import read as R

#: every profile the lane reads: the text reader's and the page reader's
SLUGS = tuple(sorted(R.TEXT_READ_SLUGS | {R.SCANNED}))
TABLES = {**dict(L.COLUMNS), "paragraphs": L.PARAGRAPH_COLUMNS, "set_aside": L.SET_ASIDE_COLUMNS,
          f"{L.PRIVATE}.withheld_names": L.WITHHELD_COLUMNS, f"{L.PRIVATE}.identifiers": identifiers.COLUMNS}
#: the lane's own housekeeping: what a row says about the record, the reading or its place, never a field of the document
HOUSEKEEPING = frozenset({
    "documents.record", "documents.seq", "documents.kind", "documents.case_slug", "documents.url", "documents.content_type",
    "documents.fetched_at", "documents.state", "documents.outcome", "documents.pages", "documents.text_chars",
    "documents.pieces", "documents.mcp_citation", "documents.mcp_doc_date",
    "documents.mcp_court", "documents.mcp_court_reclassified_at", "cases.case_slug", "cases.url", "case_links.case", "judgments.status", "judgments.missing",
    "judgments.unrecognised", "judgments.notes", "judgments.case_slug", "judgments.source", "judgments.source_url",
    "judgments.source_note", "judgment_parties.judgment", "paragraphs.judgment", "people.case_slug", "people.document_kind",
    "set_aside.item", "set_aside.stage", "set_aside.reason", f"{L.PRIVATE}.identifiers.person",
    f"{L.PRIVATE}.withheld_names.held_in", f"{L.PRIVATE}.withheld_names.citation"})
PAGE_TEXT = "page_text"


def produces(slug: str) -> dict:
    """{field: (by, kinds or None)}: what the lane's code makes of a document of the profile."""
    if slug == R.SCANNED:
        return {PAGE_TEXT: ("model", None)}
    if slug in R.JUDGMENT_SLUGS:
        out = {f: ("rules", None) for f in caption.FIELDS}
    elif slug == R.CASE_PAGE:
        out = {f: ("rules", None) for f in R.CASE_FIELDS}
    else:
        out = {f: ("rules", None) for f in R.sheet_fields()}
    out.update({f: ("model", None) for f in model_read.FIELDS})
    out["details"] = ("model", tuple(model_read.DETAIL_KINDS))      # ruling 142: each person's details, private
    out["identifiers"] = ("pattern", tuple(identifiers.SHAPE_KINDS))
    return out


LANE = align.Lane("courts", TABLES, {s: produces(s) for s in SLUGS}, HOUSEKEEPING)


def problems(profiles: dict = None) -> list:
    return align.problems(LANE, profiles)


def where(schema: str = L.SCHEMA, shared: bool = False):
    """A lane table's name ("judgments", "courts_private.identifiers") → (schema, table) in the database."""
    def at(t: str) -> tuple:
        if t.startswith(L.PRIVATE + "."):
            return tuple(L.table(L.private_of(schema), t.split(".", 1)[1], shared).split(".", 1))
        return tuple(L.table(schema, t, shared).split(".", 1))
    return at


def _readers(slug: str, doc: dict) -> dict:
    """by → (reader, model) for a document of the profile."""
    rules = caption.VERSION if slug in R.JUDGMENT_SLUGS else R.READER
    return {"rules": (rules, None), "pattern": (identifiers.READER, None),
            "model": (doc.get("model_reader"), doc.get("model"))}


def extracted(documents: list, profiles: dict = None) -> list:
    """The docs.extractions rows for a load's `documents` rows: (sha256, profile, field, iteration, reader, model).
    A file is its bytes: one set of rows per file, however many records point at it. A document recognised by its
    shape has had the rules and the pattern pass; the text reader's fields only where its stored reading was
    replayed (the row carries the model); a page the page reader read records `page_text` under the scanned profile.
    A document waiting on the page reader, set aside unrecognised, or caught, has had nothing. Each field is recorded
    at its current item's iteration."""
    profiles = pr.current() if profiles is None else profiles
    out, seen = [], set()
    for doc in documents:
        sha, slug = doc.get("document"), doc.get("profile")
        if not sha or not slug or sha in seen or doc.get("outcome") in ("caught", R.WAIT_PAGES):
            continue
        seen.add(sha)
        items = pr.latest((profiles.get(slug) or {}).get("extract"))
        readers = _readers(slug, doc)
        for f, (by, _) in produces(slug).items():
            if f not in items or (by == "model" and not doc.get("model")):
                continue
            reader, model = readers[by]
            out.append((sha, slug, f, items[f]["iteration"], reader, model))
        if doc.get("read_from") in ("pixels", "mixed"):
            page = pr.latest((profiles.get(R.SCANNED) or {}).get("extract")).get(PAGE_TEXT)
            if page:
                out.append((sha, R.SCANNED, PAGE_TEXT, page["iteration"], R.READER, R._page_model()))
    return out


def expected(slug: str, outcome: str, read_from: str = None, profiles: dict = None) -> set:
    """The fields a document of the profile and outcome has had, by the rule `extracted` records them."""
    profiles = pr.current() if profiles is None else profiles
    items = pr.latest((profiles.get(slug) or {}).get("extract"))
    if slug == R.SCANNED or outcome not in ("read", R.WAIT_TEXT):
        return set()
    return {f for f, (by, _) in produces(slug).items() if f in items and (by != "model" or outcome == "read")}
