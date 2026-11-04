"""The reading of the MCP's courts corpus (rulings 126 to 128): every record
is a document read, a document waiting on a reader, or a catch-log line.

Profiles before readers. Each landed file is recognised by shape before any
reader runs: a case page by the court's own page template (a `<main>` with
a case title and a Decision, Date of Judgment or Media releases heading); a
PDF by the text layer of its first two pages (a court line with a neutral
citation or case number and a judgment heading; a press summary's own
words; a transcript's citation `[year] NZSC Trans n` or its word; counsel's
SUBMISSIONS; a synopsis's own words), never by its file name or the MCP's
coarse `kind` (one in six "judgment_pdf" files is a media release, a
transcript, a submission or a synopsis). A PDF with no text layer on page 1
is recognised as `courts-scanned-document` and waits for the page reader
(profile page-reader; `python -m registers.courts.read --pages SHA`), as
the disclosures lane's scans do; once its pages are read it is recognised
again from that text.

Two readings per document. The deterministic one here: a judgment's
caption (caption.parse: citation, court, registry, case numbers, date,
judges, parties and roles, numbered paragraphs, outcome), a case page's
court, case name, dates, result and links, a release's or transcript's
citation, case numbers and date. And the text reader's (model_read.py:
every person and body the document names with its role, counsel for each
party, a one-line summary), which the load only replays from the reader
store: a document without a stored model reading is "waiting: text reader",
never read here, so the fast tier calls no model.

Suppression (hard limit 16): a judgment that carries a suppression banner
or an order in its text, or whose citation or document is in the lane's
ledger of orders (suppress.py), has every party's name withheld except the
Crown's and an initial the court itself printed; the same withholding
reaches every model-read name on every document of the citation (and of
the case page that links it), judges, counsel and the Crown apart. Nothing
is lost (ruling 142, 4 November 2026): the row, its role and the flag stay
in the schema the session login reads; the name goes whole to the private
table, keyed by its row, with where it belongs and the source's words
(`_kept`), and the private views put it back in its row for the links.

    recognise(entry, data, texts)          (profile slug, why, document kind)
    read(entries, orders, store, …)        Result
    python -m registers.courts.read --pages SHA    the page-reader piece (qv4-courts-pages)
"""
import datetime as dt
import functools
import html as H
import os
import re
import sys
from dataclasses import dataclass, field

from support import profiles
from support import reader as rd
from support.docread import pages as P
from support.docread.pagereader import page_total
from registers.courts import caption
from registers.courts import capture as CAP
from registers.courts import identifiers
from registers.courts import pieces as PC

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profile-proposed.jsonl")
READER = "registers.courts.read 3"
CAPTION_READER = caption.VERSION

#: the profiles, by the kind of document they read
CASE_PAGE, RELEASE, TRANSCRIPT, SUBMISSION, SYNOPSIS, SCANNED = (
    "courts-case-page", "courts-media-release", "courts-hearing-transcript", "courts-counsel-submission",
    "courts-case-synopsis", "courts-scanned-document")
#: the new kinds of 30 and 31 October 2026 (fix-2; ruling 130): the Employment Relations Authority's determinations
#: (determinations.era.govt.nz), the Human Rights Review Tribunal's decisions, the other tribunals' and authorities'
#: decisions and the District Court's judgments (justice.govt.nz/assets/Documents/Decisions)
ERA, HRRT, TRIBUNAL, NZDC = "courts-era-determination", "courts-hrrt-decision", "courts-tribunal-decision", "courts-nzdc-judgment"
#: the Māori Land Court's and the Māori Appellate Court's judgments (ruling 140's JDO walk; measured 3 November 2026)
MAORI = "courts-maori-court-judgment"
JUDGMENT_PROFILES = {"SUPREME COURT": "courts-nzsc-judgment", "COURT OF APPEAL": "courts-nzca-judgment",
                     "HIGH COURT": None, "DISTRICT COURT": NZDC, "OTHER": "courts-judgment"}
NZHC = {"civil": "courts-nzhc-civil-judgment", "criminal": "courts-nzhc-criminal-judgment"}
JUDGMENT_SLUGS = {"courts-nzsc-judgment", "courts-nzca-judgment", "courts-nzhc-civil-judgment",
                  "courts-nzhc-criminal-judgment", "courts-judgment", ERA, HRRT, TRIBUNAL, NZDC, MAORI}
KIND_OF = {CASE_PAGE: "case page", RELEASE: "media release", TRANSCRIPT: "hearing transcript",
           SUBMISSION: "counsel submission", SYNOPSIS: "case synopsis", SCANNED: "scanned document",
           **{s: "judgment" for s in JUDGMENT_SLUGS}, ERA: "determination", HRRT: "tribunal decision", TRIBUNAL: "tribunal decision"}
#: every profile the text reader reads (every courts profile but the scanned one): each carries a reading rule
TEXT_READ_SLUGS = {CASE_PAGE, RELEASE, TRANSCRIPT, SUBMISSION, SYNOPSIS} | JUDGMENT_SLUGS
COURT_CODES = {"SUPREME COURT": "NZSC", "COURT OF APPEAL": "NZCA", "HIGH COURT": "NZHC", "DISTRICT COURT": "NZDC",
               "EMPLOYMENT COURT": "NZEmpC", "FAMILY COURT": "NZFC", "ENVIRONMENT COURT": "NZEnvC",
               "CORONERS COURT": "NZCorC", "MĀORI LAND COURT": "NZMLC", "MAORI LAND COURT": "NZMLC",
               "EMPLOYMENT RELATIONS AUTHORITY": "NZERA", "HUMAN RIGHTS REVIEW TRIBUNAL": "NZHRRT"}
#: the citation codes of the courts: a citation with any other code on a document with no court line is a tribunal's
COURT_CITE_CODES = {"NZSC", "NZCA", "NZHC", "NZDC", "NZFC", "NZYC", "NZEmpC", "NZEnvC", "NZMLC", "NZMAC", "NZCorC", "NZCMAC"}
WITHHELD_MARKER = "a suppression marker in the judgment"
WAIT_PAGES = "waiting: page reader"
WAIT_TEXT = "waiting: text reader"
#: what a documents row takes from the row of the record its file was read under
SHARED_READING = ("profile", "profile_version", "outcome", "pages", "read_from", "text_chars", "pieces", "citation", "case_numbers",
                  "dated", "summary", "model", "model_reader")

# ── the shapes ────────────────────────────────────────────────────────────────────────────────────────────────
PRESS = re.compile(r"This (?:summary|media release) is provided to assist|^\s*MEDIA RELEASE\s*$|^\s*PRESS SUMMARY\s*$", re.M)
TRANS_CITE = re.compile(r"\[(\d{4})\]\s+NZ[A-Za-z]{2,6}\s+Trans\s+(\d{1,4})\b")
TRANS_WORD = re.compile(r"\bTRANSCRIPT\b")
#: a speaker's line in a transcript: "ELIAS CJ:", "WILLIAM YOUNG J:", "MR HODDER QC:", "MS HARDING:"; never a label ("Hearing:",
#: "Date of Hearing:", "Decision No:"), whose word runs straight into its colon with no judge's or counsel's suffix
SPEAKER = re.compile(r"^\s*(?:(?:MR|MS|MRS|MISS|DR|SIR|DAME|JUSTICE) )?(?:[A-Z][A-Za-zĀĒĪŌŪāēīōū'’\-]+ ){0,2}(?:J|CJ|KC|QC|P|SC|JJ)?:\s", re.M)
SUBMISSIONS = re.compile(r"\bSUBMISSIONS?\b|\bOUTLINE OF (?:ORAL )?ARGUMENT\b|\bSYNOPSIS OF (?:ORAL )?ARGUMENT\b|\bCHRONOLOGY\b|"
                         r"Submissions? (?:of|for|on behalf of) the\b|Outline of (?:Oral )?Argument", re.M | re.I)
SYNOPSIS_WORDS = re.compile(r"This synopsis is provided|CASE SYNOPSIS|CASE SUMMARY|^\s*SYNOPSIS\s*$", re.M | re.I)
JUDGMENT_HEADING = re.compile(r"^\s*(?:\(?ORAL\)?\s+|RESERVED\s+|INTERLOCUTORY\s+|COSTS\s+|SUPPLEMENTARY\s+|FURTHER\s+|RESULT\s+)?"
                              r"(JUDGMENT|SENTENCING NOTES|SENTENCING REMARKS|SENTENCE|DECISION|RULING|REASONS|MINUTE|FINDINGS?|DETERMINATION)\b", re.M)
LABELS = re.compile(r"^\s*(Hearings?|Court|Counsel|Appearances|Judgments?|Appearance|Before|Coram|Date of Hearing|Decision|Witnesses|"
                    r"Member of Authority|Representatives|Representation|Investigation Meeting|Determination|Date of Determination)\s*:", re.M)
#: a court line with or without "OF NEW ZEALAND", and with a case number after it on the same line (older files)
COURT = re.compile(r"^\s*IN THE (SUPREME COURT|COURT OF APPEAL|HIGH COURT|DISTRICT COURT|EMPLOYMENT COURT|FAMILY COURT|"
                   r"ENVIRONMENT COURT|CORONERS COURT|CORONER'S COURT|MĀORI LAND COURT|MAORI LAND COURT|"
                   r"EMPLOYMENT RELATIONS AUTHORITY|HUMAN RIGHTS REVIEW TRIBUNAL|(?!MATTER\b)[A-ZĀĒĪŌŪ' ]+? (?:COURT|TRIBUNAL|AUTHORITY))\b", re.M)
#: the Māori courts' title-case court line under the reo line ("Te Kooti Pīra Māori o Aotearoa", "Te Kooti Whenua Māori o
#: Aotearoa"), their bilingual labels ("Nohoanga:" over Hearing, "Whakataunga:" over Judgment date) and their minute-book
#: citation at every page's head: "2024 Māori Appellate Court MB 84", "[2025] Māori Appellate Court MB 167", "2025 Aotea MB
#: 123", "2025 Chief Judge's MB 45" (measured 3 November 2026 on 8 Appellate and 50 Land Court files)
MAORI_COURT = re.compile(r"^\s*In the\s*(M[āa]ori Appellate Court|M[āa]ori Land Court) of New Zealand\b", re.M)
WHAKATAUNGA = re.compile(r"^\s*Whakataunga:\s+(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|"
                         r"November|December) \d{4})", re.M)
NOHOANGA = re.compile(r"^\s*Nohoanga:", re.M)
#: the Land Court's reference is the book's number, the district and the page ("(2025) 519 Aotea MB 25 (519 AOT 25)"); the
#: Appellate Court's since 2023 the year in the book's place ("2024 Māori Appellate Court MB 84")
MINUTE_BOOK = re.compile(r"(?<![\w\]])(?:[\[(](\d{4})[\])]\s+)?(?:(\d{1,4})\s+)?(M[āa]ori Appellate Court|Chief Judge[’']s|"
                         r"[A-ZĀĒĪŌŪ][a-zāēīōū]+(?: [A-ZĀĒĪŌŪ][a-zāēīōū]+){0,2})\s+MB\s+(\d{1,5})\b")
#: a tribunal's opening with no court line: "BEFORE THE … TRIBUNAL|AUTHORITY", or "IN THE MATTER OF …" lines
TRIBUNAL_OPEN = re.compile(r"^\s*(?:BEFORE THE (?!MATTER\b)[A-ZĀĒĪŌŪ' ]+?(?:TRIBUNAL|AUTHORITY|BOARD|COMMITTEE)\b|(?:AND )?IN THE MATTER\b)", re.M)
#: the Human Rights Review Tribunal's and the tribunals' upper-case labels
UPPER_LABELS = re.compile(r"^\s*(?:BEFORE|REPRESENTATION|DATE OF HEARING|DATE OF DECISION|DATE OF LAST SUBMISSIONS|HEARD AT)\s*:", re.M)
#: a hearing transcript's cover sheet: Appearances (a judgment prints Counsel), no heading, no citation
APPEARANCES = re.compile(r"^\s*Appearances\s*:", re.M)
TRANSCRIPT_PAGES = 20
# the transcripts of 2004–2008 (filed in the case-information folders) print the speaker in a left column with no colon,
# "Elias CJ", "Mr Smith", "Tipping J", three or more spaces before the words; measured on 21 such files: 58 to 2,138 lines
# (at least two a page); on 30 judgments, determinations, decisions or submissions of each profile: 13 at most
SPEAKER_COLUMN = re.compile(r"^(?:(?:Mr|Ms|Mrs|Miss|Dr|Sir|Dame) )?[A-Z][A-Za-zĀĒĪŌŪāēīōū'’\-]+(?: (?:J|CJ|P))?\s{3,}\S", re.M)
SPEAKER_COLUMN_LINES = 50
#: case numbers as every court prints them: SC 6/2004, SC CIV 7/2004, CA94/05, CIV-2026-404-1, CIV2017-091-000902, EMPC 230/2021
CASE_NUMBER = re.compile(r"\b(?:SC|CA|EMPC|SC CIV|SC CRI|CA CIV|CA CRI)\s?\d{1,4}/(?:\d{4}|\d{2})\b|"
                         r"\b(?:CIV|CRI|CRC|CIVP)[- ]?\d{4}-\d{3}-\d{1,6}\b|\bCSU-\d{4}-[A-Z]{3}-\d{6}\b", re.I)
DATE_LINE = re.compile(r"^\s*(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})\s*$", re.M | re.I)
CASE_HREF = re.compile(r"^https?://(?:www\.)?courtsofnz\.govt\.nz(?::80)?/cases/([^/?#]+)/?$")


def _cite_line(text: str) -> bool:
    return any(caption.CITE_LINE.match(ln) for ln in (text or "").splitlines())


@dataclass
class Result:
    documents: list = field(default_factory=list)
    cases: list = field(default_factory=list)
    case_links: list = field(default_factory=list)
    judgments: list = field(default_factory=list)
    parties: list = field(default_factory=list)
    paragraphs: list = field(default_factory=list)     # (judgment key, number, page, document)
    people: list = field(default_factory=list)
    withheld: list = field(default_factory=list)       # a suppressed name whole (load.WITHHELD_COLUMNS): the private table only
    identifiers: list = field(default_factory=list)    # identifying details by shape (identifiers.py): the private table only
    set_aside: list = field(default_factory=list)      # (item, stage, reason)
    counts: dict = field(default_factory=dict)


@functools.lru_cache(maxsize=None)
def profile_of(slug: str) -> dict:
    """The profile's newest line: the ledger's, or the lane's proposed line
    (`profile-proposed.jsonl`) until the integrator appends it at the merge."""
    held = [p for p in (profiles.profile(slug), profiles.profile(slug, path=PROPOSED)) if p]
    if not held:
        raise LookupError(f"no document profile {slug}")
    return max(held, key=lambda p: int(p["version"]))


def profile_version(slug: str, fallback: bool = False) -> int:
    """The version a reading of `slug` is keyed and stamped by (support.profiles.reading_version): a ledger version
    that only adds to the extract list, or only a reading rule's fallback, leaves the stored readings standing; a
    reading the fallback made (`fallback=True`) is stamped with the version that brought the fallback in; a proposed
    line is a new reading."""
    p = profile_of(slug)
    held = profiles.profile(slug)
    if held is not None and int(held["version"]) == int(p["version"]):
        return profiles.reading_version(slug, fallback=fallback)
    return int(p["version"])


def text_reading(slug: str, texts: dict) -> tuple:
    """(pieces or None, why, the version the text reader's reading is keyed by, the split that cut it): one rule for
    the load and the reader's job. A document its profile's own split cuts is keyed as it always was; one only the
    rule's fallback cuts, by the version that brought the fallback in."""
    rule = PC.rule_of(slug)
    parts, why, used = PC.plan_how(texts, rule)
    fallback = used is not None and used != rule["split"]
    return parts, why, profile_version(slug, fallback=fallback), used


# ── the case page ─────────────────────────────────────────────────────────────────────────────────────────────
def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def case_page(data: bytes, url: str) -> dict:
    """The court's own case page, by its template: {title, case_name, citation,
    case_numbers, court, sections: {heading: text}, links: [(section, label, href)]},
    or None when the bytes are not a case page (crawl noise is a resource or
    a form served as HTML, with no `<main>` and no case title)."""
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    m = re.search(r"<main\b.*?</main>", s, re.S | re.I)
    if not m:
        return None
    body = re.sub(r"<(script|style|svg)\b[^>]*>.*?</\1>", " ", m.group(0), flags=re.S | re.I)
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", body, re.S | re.I)
    if not h1:
        return None
    title = _text(h1.group(1))
    crumbs = [_text(x) for x in re.findall(r'<li class="breadcrumb-item[^"]*">(.*?)</li>', body, re.S)]
    court = next((c for c in crumbs if re.search(r"\bCourt\b|Tribunal", c) and c not in ("The courts",)), None)
    # "Name - [2026] NZSC 121" or "Name - SC 23/2022": the name is what stands before the last " - "
    name, tail = title, ""
    mm = re.match(r"^(.*?)\s+[-–—]\s*(\[\d{4}\][^$]*|(?:SC|CA)\s?\d{1,4}/\d{4}.*)$", title)
    if mm:
        name, tail = mm.group(1).strip(), mm.group(2).strip()
    elif title.endswith(("-", "–")):
        name = title.rstrip("-– ").strip()
    cite = caption.CITE.search(tail) or caption.CITE.search(title)
    citation = f"[{cite.group(1)}] {cite.group(2)} {cite.group(3)}" if cite else None
    case_numbers = [c.replace("  ", " ") for c in caption.CASE_NO.findall(tail + " " + title)]
    sections, links, order = {}, [], []
    parts = re.split(r"<h2\b[^>]*>(.*?)</h2>", body[h1.end():], flags=re.S | re.I)
    # parts: [before, heading1, body1, heading2, body2, …]
    for i in range(1, len(parts) - 1, 2):
        heading, sect = _text(parts[i]), parts[i + 1]
        order.append(heading)
        texts = [_text(x) for x in re.findall(r'<(?:div|p) class="case__(?:summary|result|date|judges|related-decision)"[^>]*>(.*?)</(?:div|p)>',
                                              sect, re.S)]
        if texts:
            sections[heading] = " | ".join(t for t in texts if t)
        for href, label in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', sect, re.S | re.I):
            if href.startswith("#") or "sendto_form" in href:
                continue
            label = re.sub(r"\(?\s*PDF[^)]*\)?\s*$", "", _text(label)).strip()
            links.append((heading, label, _absolute(href, url)))
    return {"title": title, "case_name": name, "citation": citation, "case_numbers": sorted(set(case_numbers)),
            "court": court, "sections": sections, "headings": order, "links": links}


def _absolute(href: str, base: str) -> str:
    href = H.unescape(href.strip())
    if href.startswith("http://") or href.startswith("https://"):
        return href
    host = re.match(r"^(https?://[^/]+)", base or "")
    return (host.group(1) if host else "https://www.courtsofnz.govt.nz") + ("/" if not href.startswith("/") else "") + href


def _case_date(text: str):
    m = caption.DATE.search(text or "")
    return caption._date(m.group(0)) if m else None


# ── recognition by shape ──────────────────────────────────────────────────────────────────────────────────────
def recognise(entry: dict, data: bytes, texts: dict = None) -> tuple:
    """(profile slug, why) by shape, or (None, why). `texts` is the page →
    text map for a PDF (the first two pages are enough; measured here)."""
    if data is None:
        return None, "no file landed"
    if not data.startswith(b"%PDF"):
        page = case_page(data, entry.get("url"))
        if page is None:
            return None, "HTML with no case page shape (a resource or a form the crawl took): crawl noise"
        if not any(h in page["headings"] for h in ("Decision", "Date of Judgment", "Media releases", "Date of Hearing",
                                                   "Summary", "Related Documents", "Hearing Transcripts")):
            return None, "a courts page without a case's headings"
        return CASE_PAGE, "the court's case page template: a case title and its headings"
    texts = texts if texts is not None else {p: P.page_text(data, p) for p in (1, 2)}
    p1 = texts.get(1) or ""
    if P.is_thin(p1):
        return SCANNED, "no text layer on page 1: waits for the page reader"
    head = p1 + "\n" + (texts.get(2) or "")
    speakers = len(SPEAKER.findall(head))
    cl = COURT.search(p1)
    court_text = cl.group(1).strip() if cl else None
    cite_codes = {caption.court_code(m.group(2)) for m in caption.CITE.finditer(head)}
    # a citation on its own line or a case number; under a court line, a citation beside a label counts too (the District
    # Court's ACC appeals print "[2024] NZACC 153" against a label and number their files ACR nn/yy)
    numbered = bool(_cite_line(head) or CASE_NUMBER.search(head) or (court_text and cite_codes))
    heading = bool(JUDGMENT_HEADING.search(head))
    labels = bool(LABELS.search(head))
    # the Māori courts' judgments, by their title-case court line and their judgment-date label (or the hearing label
    # with a minute-book citation): before fix 3 November 2026 none matched, 45 of 50 were set aside and 5 taken for
    # counsel's submissions
    if MAORI_COURT.search(p1) and (WHAKATAUNGA.search(head) or (NOHOANGA.search(head) and any(
            m.group(1) or m.group(2) for m in MINUTE_BOOK.finditer(head)))):
        return MAORI, "a Māori court's court line with its judgment-date label (Whakataunga) or its hearing label and minute-book citation"
    # the Employment Relations Authority and the Human Rights Review Tribunal, by their court lines (their labels and
    # 'Submissions received' took them for counsel's submissions before fix-2)
    if court_text == "EMPLOYMENT RELATIONS AUTHORITY" and ("NZERA" in cite_codes or heading or labels):
        return ERA, "the Authority's court line with its citation, its DETERMINATION heading or its labels"
    if court_text == "HUMAN RIGHTS REVIEW TRIBUNAL" and ("NZHRRT" in cite_codes or heading or UPPER_LABELS.search(head)):
        return HRRT, "the Tribunal's court line with its citation, its DECISION heading or its upper-case labels"
    if SYNOPSIS_WORDS.search(p1) and not heading:
        return SYNOPSIS, "a synopsis's own words on page 1"
    if PRESS.search(p1):
        return RELEASE, "a press summary's own words on page 1"
    if TRANS_CITE.search(head) or (TRANS_WORD.search(p1) and speakers >= 1) or (speakers >= 6 and not heading):
        return TRANSCRIPT, "a transcript's citation, its word with speaker lines, or speaker lines under a caption"
    # a transcript's cover sheet (2008–2018): the case number beside the court line, Appearances, no heading, no
    # citation, and the speakers' lines: three within the first six pages, or ten in a long document (17 were filed as
    # Supreme Court judgments; a Court of Appeal judgment with a long caption and no speaker anywhere is not one)
    if court_text and CASE_NUMBER.search(head) and not heading and not _cite_line(head):
        whole = "\n".join(texts[p] or "" for p in sorted(texts))
        if APPEARANCES.search(head):
            early = len(SPEAKER.findall("\n".join(texts.get(p) or "" for p in range(1, 7))))
            everywhere = len(SPEAKER.findall(whole)) if len(texts) >= TRANSCRIPT_PAGES else 0
            if early >= 3 or everywhere >= 10:
                return TRANSCRIPT, "a cover sheet with the case number beside the court line, Appearances, no judgment heading or citation, and speakers' lines: a hearing transcript"
        # the two-column transcripts of 2004–2008: the speaker in the left column, no colon, at least two lines a page
        column = len(SPEAKER_COLUMN.findall(whole))
        if column >= SPEAKER_COLUMN_LINES and column >= 2 * len(texts):
            return TRANSCRIPT, "a cover sheet with the case number beside the court line and the speakers in a left column on every page: a hearing transcript of 2004–2008"
    # a tribunal or authority with no court line, by a citation of its own code
    if ((court_text is None or court_text.endswith(("TRIBUNAL", "AUTHORITY"))) and cite_codes - COURT_CITE_CODES
            and (heading or TRIBUNAL_OPEN.search(p1) or UPPER_LABELS.search(head) or labels)):
        return TRIBUNAL, "a tribunal's or authority's citation code with its opening, heading or labels and no court's court line"
    if SUBMISSIONS.search(head) and not (heading and labels):
        return SUBMISSION, "counsel's submissions, an outline of argument or a chronology: the word with no judgment heading"
    if court_text and numbered and (heading or labels):
        if court_text == "HIGH COURT":
            cn = CASE_NUMBER.search(head)
            criminal = bool(cn and cn.group(0).upper().startswith(("CRI", "CRC")))
            return NZHC["criminal" if criminal else "civil"], "High Court; case number " + ("CRI" if criminal else "CIV")
        slug = JUDGMENT_PROFILES.get(court_text) or JUDGMENT_PROFILES["OTHER"]
        return slug, f"court line {court_text}, a citation or case number, a judgment heading or its labels"
    if not court_text and _cite_line(head) and (heading or labels):
        return JUDGMENT_PROFILES["OTHER"], "a neutral citation and a judgment heading with no court line"
    if court_text and numbered and re.search(r"^\s*(BETWEEN|AND|Between|And)\b", head, re.M):
        return SUBMISSION, "a caption with no judgment heading or labels: a filed document (submissions)"
    return None, "no shape recognised: not a judgment, release, transcript, submission, synopsis or case page"


_URL_DATE = re.compile(r"(?<!\d)((?:18|19|20)\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)")


def _impossible_date(page: str) -> bool:
    """Page 1 prints a date whose year no court document can carry (caption.possible_year)."""
    return any(not caption.possible_year(int(m.group(3))) for m in caption.DATE.finditer(page))


def _url_date(url: str):
    """The ISO date a document's own address carries (environmentcourt.govt.nz names its files by it), or None."""
    m = _URL_DATE.search(url.rsplit("/", 1)[-1])
    if not m or not caption.possible_year(int(m.group(1))):
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def maori_citation(j, texts: dict) -> None:
    """A Māori court judgment's citation is its minute-book reference and its date the Whakataunga line, where the
    caption reader found no neutral citation or date of its own."""
    head = (texts.get(1) or "") + "\n" + (texts.get(2) or "")
    if not j.citation:
        m = next((x for x in MINUTE_BOOK.finditer(head) if x.group(1) or x.group(2)), None)   # a year or a book number
        if m:
            book = "Chief Judge's" if m.group(3).startswith("Chief Judge") else m.group(3)
            j.citation = (f"[{m.group(1)}] " if m.group(1) and not m.group(2) else f"({m.group(1)}) " if m.group(1) else "") \
                + (f"{m.group(2)} " if m.group(2) else "") + f"{book} MB {m.group(4)}"
    if j.judgment_date is None:
        w = WHAKATAUNGA.search(head)
        if w:
            j.judgment_date = caption._date(w.group(1))


#: the bases the load gives a judgment's date and citation where the document gave none and the MCP's record did
MCP_DATE_BASIS = "mcp doc_date"
MCP_CITATION_BASIS = "mcp citation"


def mcp_date(value):
    """The MCP record's `doc_date` as a date: an ISO day (a time after it is dropped), in a possible year; else None."""
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m or not caption.possible_year(int(m.group(1))):
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def from_mcp(j, mcp: dict) -> None:
    """The judgment's date and citation from the MCP's record where the document gave none (Arthur, 3 November 2026:
    the provider's `doc_date` is the judgment's own date, its `date` the arrival); the basis says so. Where both exist
    the document's reading wins, and the check counts the agreements (check._mcp_dates)."""
    j.citation_basis = "document" if j.citation else None
    if j.judgment_date is None and mcp.get("mcp_doc_date"):
        j.judgment_date, j.date_basis = mcp["mcp_doc_date"], MCP_DATE_BASIS
    if not j.citation and mcp.get("mcp_citation"):
        j.citation, j.citation_basis = mcp["mcp_citation"], MCP_CITATION_BASIS


# ── the deterministic readers of the smaller kinds────────────────────────────────────────────────────────────
def sheet(texts: dict, slug: str) -> dict:
    """What a release, transcript, submission or synopsis prints on its
    face: citation, case numbers, the date it prints, a suppression marker."""
    head = (texts.get(1) or "") + "\n" + (texts.get(2) or "")
    cite = caption.CITE.search(head) if slug != TRANSCRIPT else None
    citation = f"[{cite.group(1)}] {cite.group(2)} {cite.group(3)}" if cite else None
    if slug == TRANSCRIPT:
        t = TRANS_CITE.search(head)
        citation = f"[{t.group(1)}] NZSC Trans {t.group(2)}" if t else None
    nums = []
    for c in caption.CASE_NO.findall(head):
        c = c.replace("  ", " ")
        if c not in nums:
            nums.append(c)
    d = DATE_LINE.search(texts.get(1) or "")
    dated = caption._date(f"{d.group(1)} {d.group(2).title()} {d.group(3)}") if d else None
    if not dated:
        m = caption.DATE.search(texts.get(1) or "")
        dated = caption._date(m.group(0)) if m else None
    return {"citation": citation, "case_numbers": nums, "dated": dated,
            "suppression": bool(caption.SUPPRESS.search(head)) or bool(caption.BODY_SUPPRESS.search(head))}


# ── the reading ───────────────────────────────────────────────────────────────────────────────────────────────
def _texts_of(data: bytes, sha: str, store: rd.Store, scanned_version: int) -> tuple:
    """Every page's text: the text layer, and for a page with none the page
    reader's stored reading under the scanned profile (never made here).
    Returns (texts, read_from, unread pages)."""
    layer = P.text_pages(data)
    thin = set(P.thin_pages(layer))
    texts, unread, pixels = {}, [], 0
    for p in sorted(layer):
        if p not in thin:
            texts[p] = layer[p]
            continue
        key = rd.reading_key(sha, p, _page_model(), _pixel_settings(), SCANNED, scanned_version)
        if store.has(key):
            texts[p] = store.get(key).text
            pixels += 1
        else:
            unread.append(p)
    how = "text" if not thin else ("pixels" if pixels + len(unread) == len(layer) else "mixed")
    return texts, how, unread


def _page_model() -> str:
    from support.docread import pagereader
    return pagereader.MODEL


def _pixel_settings(dpi: int = None) -> dict:
    from support.docread import pagereader
    return {"dpi": dpi or pagereader.DPI, "prompt": pagereader.PROMPT}


def read(entries: list, orders: list = (), store: rd.Store = None, data_of=None, now: str = None) -> Result:
    """entries: the corpus's records (capture.records); orders: the ledger's
    rows ({citation, document, reason}). `data_of(sha)` gives a document's
    bytes (the store's, by default). Every entry becomes one `documents` row;
    every row is read, waiting, set aside or caught, asserted."""
    from support.docread.read import read_document
    from support.docstore.landing import path_for, read_bytes
    from registers.courts import model_read
    data_of = data_of or (lambda sha: read_bytes(sha) if os.path.exists(path_for(sha)) else None)
    store = store or rd.Store()
    res = Result()
    now = now or dt.datetime.now().astimezone().isoformat(timespec="seconds")
    scanned_version = profile_version(SCANNED)
    parsed, sheets, pages_read = [], [], {}
    by_url = {e["url"]: e for e in entries if e.get("url")}
    primary = _primary_entries(entries)     # a document is its bytes: one entry is read per file, however many records point at it
    primary_doc, shared = {}, []            # sha → the documents row of the entry read; the other records' rows, filled after
    mcp_of = {}                             # sha → the MCP's citation and judgment date, from any record of the file
    for e in entries:
        got = mcp_of.setdefault(e.get("capture"), {"mcp_citation": None, "mcp_doc_date": None})
        got["mcp_citation"] = got["mcp_citation"] or e.get("mcp_citation")
        got["mcp_doc_date"] = got["mcp_doc_date"] or mcp_date(e.get("mcp_doc_date"))
    for e in entries:
        doc = {"key": e["record_id"], "record": e["record"], "seq": e.get("seq"), "kind": e.get("kind"),
               "case_slug": e.get("case_slug"), "url": e["url"], "content_type": e.get("content_type"),
               "fetched_at": e.get("fetched_at"), "document": e.get("capture"), "state": e.get("state"),
               "profile": None, "profile_version": None, "outcome": None, "pages": None, "read_from": None,
               "text_chars": None, "pieces": None, "citation": None, "case_numbers": [], "dated": None, "summary": None,
               "model": None, "model_reader": None, "mcp_citation": e.get("mcp_citation"),
               "mcp_doc_date": mcp_date(e.get("mcp_doc_date")), "mcp_court": e.get("mcp_court"),
               "mcp_court_reclassified_at": e.get("mcp_court_reclassified_at"), "loaded_at": now}
        res.documents.append(doc)
        sha = e.get("capture")
        if sha and primary[sha] is not e:
            shared.append(doc)
            continue
        if sha:
            primary_doc[sha] = doc
        data = data_of(sha) if sha else None
        if data is None:
            doc["outcome"] = "caught"
            reason = {"caught": "the pull caught it (its catch line says why): no file landed",
                      "waiting": "the pull has not fetched it yet (its budget): no file landed"}.get(e.get("state"))
            res.set_aside.append((e["record_id"], "pull", reason or f"no file for state {e.get('state')!r}"))
            continue
        if not data.startswith(b"%PDF"):
            slug, why = recognise(e, data)
            if slug is None:
                doc["outcome"] = "set aside"
                res.set_aside.append((e["record_id"], "recognise", why))
                continue
            version = profile_version(slug)
            page = case_page(data, e["url"])
            text = _page_text_for_model(page)
            res.identifiers += identifiers.rows(sha, text, slug, version, "text", now)
            doc.update(profile=slug, profile_version=version, pages=1, read_from="text", text_chars=sum(len(t) for t in text.values()))
            _case_rows(res, e, sha, page, slug, version, by_url, now)
            doc.update(citation=page["citation"], case_numbers=page["case_numbers"],
                       dated=_case_date(page["sections"].get("Date of Judgment")))
            planned = _plan(res, doc, text, slug)
            if planned is None:
                continue
            pages_read[sha] = (slug, planned[0], text, planned[1])
            doc["outcome"] = "read"
            continue
        texts, how, unread = _texts_of(data, sha, store, scanned_version)
        npages = page_total(data)
        slug, why = recognise(e, data, texts)
        doc.update(pages=npages, read_from=how, text_chars=sum(len(t) for t in texts.values()))
        if slug == SCANNED:
            doc.update(profile=SCANNED, profile_version=scanned_version, outcome=WAIT_PAGES)
            res.set_aside.append((e["record_id"], "read", f"{why}; pages {unread[:5]}{'…' if len(unread) > 5 else ''} unread"))
            continue
        if slug is None:
            doc["outcome"] = "set aside"
            res.set_aside.append((e["record_id"], "recognise", why))
            continue
        version = profile_version(slug)
        doc.update(profile=slug, profile_version=version)
        res.identifiers += identifiers.rows(sha, texts, slug, version, "text" if how == "text" else "pixels", now)
        if how == "text":
            # the text-layer pages are stored under the reader contract (replayed by the check's counsel re-read)
            read_document(data, sha, profile=slug, profile_version=version, store=store, texts=texts)
        if unread:
            res.set_aside.append((e["record_id"], "read", f"{len(unread)} page(s) with no text layer not yet read by the page reader"))
        if slug in JUDGMENT_SLUGS:
            j = caption.parse(texts, os.path.basename(e["url"] or ""))
            if unread:
                j.notes.append(f"{len(unread)} pages with no text layer not read")
            parsed.append((e, sha, slug, version, j, how))
            if slug == MAORI:
                maori_citation(j, texts)
            from_mcp(j, mcp_of[sha])
            doc.update(citation=j.citation, case_numbers=j.case_numbers, dated=j.judgment_date)
        else:
            sh = sheet(texts, slug)
            sheets.append((e, sha, slug, sh))
            doc.update(citation=sh["citation"], case_numbers=sh["case_numbers"], dated=sh["dated"])
        if doc.get("dated") is None and _impossible_date(texts.get(1) or ""):
            doc["dated"] = _url_date(e.get("url") or "")       # the face's date is a slip; the address's date stands
        planned = _plan(res, doc, texts, slug)
        if planned is None:
            continue
        pages_read[sha] = (slug, planned[0], texts, planned[1])
        doc["outcome"] = "read"
    rows(res, parsed, orders, now)
    # the text reader's stored readings, replayed: people and the summary; a document without one waits
    suppressed = _suppressed(res, sheets, orders)
    for sha, (slug, version, texts, used) in pages_read.items():
        doc = primary_doc[sha]
        reading = model_read.stored(sha, slug, version, store, used=used)
        if reading is None:
            doc["outcome"] = WAIT_TEXT
            continue
        if reading.get("unusable"):
            # the text reader's answers held no object (model_read.ATTEMPTS of them): the caption's rows stand, the
            # record is set aside at stage read with the reason, and the check accounts for it there
            doc["outcome"] = "set aside"
            res.set_aside.append((doc["key"], "read", reading["unusable"]))
            continue
        doc.update(summary=reading["summary"], model=reading["model"], model_reader=reading["reader"])
        hide = _hidden_for(doc, suppressed, orders)
        words = _words_for(doc, suppressed) if hide else None
        for row in model_read.people_rows(sha, reading, doc, slug, version, now):
            if hide and not model_read.kept_under_suppression(row):
                res.withheld.append(_kept(row["key"], row["name"], None, "people", sha, doc.get("citation"), words,
                                          for_party=row.get("for_party")))
                row["name"], row["withheld"] = None, True
            res.people.append(row)
        # the text reader's identifying details per person (ruling 142): private, tied to the people row
        res.identifiers += model_read.detail_rows(sha, reading, doc, slug, version, now)
    for c in res.cases:
        if c["citation"] in suppressed["citations"] or c["case_slug"] in suppressed["slugs"]:
            c["suppression"] = True
            c["withheld"] = c["withheld"] or WITHHELD_MARKER
            if c["case_name"] is not None:
                res.withheld.append(_kept(c["key"], c["case_name"], None, "cases", c.get("document"), c.get("citation"),
                                          _words_for(c, suppressed)))
                c["case_name"] = None
    # a record whose file another record was read for: its row carries that reading, and its own catch-log line where
    # the file was set aside or caught, so every record is accounted for once and the file's rows are emitted once
    for doc in shared:
        first = primary_doc[doc["document"]]
        doc.update({k: first[k] for k in SHARED_READING})
        for item, stage, reason in [a for a in res.set_aside if a[0] == first["key"]]:
            res.set_aside.append((doc["key"], stage, f"{reason}; the same file as record {first['key']}"))
    _once(res)
    n_in, n_out = len(entries), sum(1 for d in res.documents if d["outcome"] in ("read", WAIT_PAGES, WAIT_TEXT, "set aside", "caught"))
    if n_in != n_out:
        raise AssertionError(f"courts: {n_in} records in, {n_out} accounted for: the reading does not reconcile")
    res.counts = {"records": n_in, **{k: sum(1 for d in res.documents if d["outcome"] == k)
                                   for k in ("read", WAIT_PAGES, WAIT_TEXT, "set aside", "caught")},
                  "shared": len(shared),
                  "judgments": len(res.judgments), "parties": len(res.parties), "cases": len(res.cases),
                  "people": len(res.people), "withheld": len(res.withheld), "identifiers": len(res.identifiers), "set_aside": len(res.set_aside),
                  **{s: sum(1 for x in res.judgments if x["status"] == s) for s in ("parsed", "partial", "unparsed")}}
    return res


def _plan(res: Result, doc: dict, texts: dict, slug: str):
    """The text reader's pieces for the document by its profile's rule
    (ruling 130): the count goes on the row; a document neither the rule's
    split nor its fallback can cut is set aside at stage read, named, and
    never waits on the reader. The deterministic rows (the caption's, the
    case page's) stand. (the version the reading is keyed by, the split
    that cut it), or None when set aside."""
    parts, why, version, used = text_reading(slug, texts)
    if parts is None:
        doc.update(pieces=None, outcome="set aside")
        res.set_aside.append((doc["key"], "read", f"the text reader cannot read it: {why}"))
        return None
    doc["pieces"] = len(parts)
    return version, used


def _primary_entries(entries: list) -> dict:
    """sha256 → the one entry read for that file. The corpus holds the same
    bytes under more than one record (a case page with and without
    `?searchterm=None`; a PDF under two file names), and every row keyed by
    the file's hash (a case, its links, a judgment, its parties and
    paragraphs, a person) is emitted once: the record with the plainest url
    (no query string, then the shortest, then the lowest record id) is read,
    and the others' documents rows take its reading."""
    out = {}
    for e in entries:
        sha = e.get("capture")
        if sha and (sha not in out or _plainness(e) < _plainness(out[sha])):
            out[sha] = e
    return out


def _plainness(e: dict) -> tuple:
    url = e.get("url") or ""
    return ("?" in url, len(url), e.get("record_id") or "")


def _once(res: Result) -> None:
    """Every key once, asserted here rather than at the COPY: the merge gate
    of 30 October died on `cases_pkey` with three files under two records each."""
    import collections
    for name in ("documents", "cases", "case_links", "judgments", "parties", "people", "identifiers"):
        twice = [k for k, n in collections.Counter(r["key"] for r in getattr(res, name)).items() if n > 1]
        if twice:
            raise AssertionError(f"courts: {len(twice)} {name} key(s) emitted more than once ({twice[0][:12]}…): a file is read once")
    twice = [k for k, n in collections.Counter((j, num) for j, num, _, _ in res.paragraphs).items() if n > 1]
    if twice:
        raise AssertionError(f"courts: paragraph {twice[0][1]} of {twice[0][0][:12]}… emitted more than once")
    twice = [k for k, n in collections.Counter(w["key"] for w in res.withheld).items() if n > 1]
    if twice:
        raise AssertionError(f"courts: withheld key {twice[0][:12]}… emitted more than once")


def _page_text_for_model(page: dict) -> dict:
    """A case page as one page of text for the text reader: title, court,
    and each section's text (the links' labels name the documents)."""
    lines = [page["title"], f"Court: {page['court'] or ''}"]
    for h in page["headings"]:
        if h in page["sections"]:
            lines.append(f"{h}: {page['sections'][h]}")
    for sect, label, href in page["links"]:
        lines.append(f"{sect}: {label} <{href}>")
    return {1: "\n".join(lines)}


#: what the case page's grammar reads (`case_page`, `_case_rows`): the case page profile's `by: rules` items.
#: `case_summary` is the page's own Summary (cases.summary), apart from the text reader's `summary` of the document
CASE_FIELDS = ("case_name", "citation", "case_numbers", "court", "case_summary", "result", "judges", "date_of_judgment",
               "date_of_hearing", "links", "suppression")


def sheet_fields() -> tuple:
    """What a release's, transcript's, submission's or synopsis's face is read for: `sheet`'s own keys."""
    return tuple(sheet({}, RELEASE))


def _case_rows(res: Result, e: dict, sha: str, page: dict, slug: str, version: int, by_url: dict, now: str) -> None:
    key = f"{sha}/case"
    secs = page["sections"]
    stamp = {"document": sha, "page": 1, "place": "case page", "read_from": "text", "reader": READER,
             "profile": slug, "profile_version": version, "loaded_at": now}
    res.cases.append({"key": key, "case_slug": e.get("case_slug") or _slug_of(e["url"]), "url": e["url"],
                      "case_name": page["case_name"], "citation": page["citation"], "case_numbers": page["case_numbers"],
                      "court": page["court"], "summary": (secs.get("Summary") or None),
                      "result": (secs.get("Result") or None), "judges": (secs.get("Judges") or None),
                      "date_of_judgment": _case_date(secs.get("Date of Judgment")),
                      "date_of_hearing": _case_date(secs.get("Date of Hearing")),
                      "suppression": False, "withheld": None, "links": len(page["links"]), **stamp})
    for n, (sect, label, href) in enumerate(page["links"], 1):
        linked = by_url.get(href) or by_url.get(href.replace("https://", "http://"))
        res.case_links.append({"key": f"{key}/link/{n}", "case": key, "position": n, "section": sect, "label": label or None,
                               "href": href, "linked_document": (linked or {}).get("capture"),
                               "document": sha, "page": 1, "place": f"case page, {sect}, link {n}"})


def _slug_of(url: str):
    m = CASE_HREF.match(url or "")
    return m.group(1) if m else None


def _ordered(citation: str, document: str, orders: list):
    for o in orders:
        if (o.get("citation") and o["citation"] == citation) or (o.get("document") and o["document"] == document):
            return o
    return None


def _suppressed(res: Result, sheets: list, orders: list) -> dict:
    """The citations, case slugs and documents a suppression reaches: a
    judgment's banner or order, a release's or transcript's banner, the
    ledger. A case page's citation or slug carries it to every document of
    the case."""
    citations, slugs, documents = set(), set(), set()
    words = {}                       # ("document" | "citation" | "slug", value) → the source's words that reach it

    def say(kind, value, text):
        if value and text and text not in words.setdefault((kind, value), []):
            words[(kind, value)].append(text)
    for j in res.judgments:
        if j["suppression"]:
            text = f"{j['withheld'] or WITHHELD_MARKER} ({', '.join(j['suppression_kinds'])}) on {j['citation'] or 'a judgment'}"
            documents.add(j["document"])
            say("document", j["document"], text)
            if j["citation"]:
                citations.add(j["citation"])
                say("citation", j["citation"], text)
            if j.get("case_slug"):
                slugs.add(j["case_slug"])
                say("slug", j["case_slug"], text)
    for e, sha, slug, sh in sheets:
        if sh["suppression"]:
            text = f"a suppression banner on {sh['citation'] or 'a document of the case'}"
            documents.add(sha)
            say("document", sha, text)
            if sh["citation"]:
                citations.add(sh["citation"])
                say("citation", sh["citation"], text)
            if e.get("case_slug"):
                slugs.add(e["case_slug"])
                say("slug", e["case_slug"], text)
    for o in orders:
        text = f"suppression order: {o.get('reason')}"
        if o.get("citation"):
            citations.add(o["citation"])
            say("citation", o["citation"], text)
        if o.get("document"):
            documents.add(o["document"])
            say("document", o["document"], text)
    return {"citations": citations, "slugs": slugs, "documents": documents, "words": words}


def _words_for(doc: dict, suppressed: dict) -> str:
    """The source's words for the suppression that reaches a document: every banner, order or ledger reason that does."""
    w = suppressed.get("words") or {}
    out = []
    for k in (("document", doc.get("document")), ("citation", doc.get("citation")), ("slug", doc.get("case_slug"))):
        for text in w.get(k, ()):
            if text not in out:
                out.append(text)
    return "; ".join(out) or WITHHELD_MARKER


def _kept(key, name, capacity, held_in, document, citation, words, for_party=None) -> dict:
    """A name a suppression covers, kept whole for the private table, flagged with the source's words (ruling 142)."""
    return {"key": key, "name": name, "capacity": capacity, "held_in": held_in, "document": document,
            "citation": citation, "for_party": for_party, "suppressed": True, "suppression_words": words or WITHHELD_MARKER}


def _hidden_for(doc: dict, suppressed: dict, orders: list) -> bool:
    return (doc["document"] in suppressed["documents"] or (doc.get("citation") in suppressed["citations"] if doc.get("citation") else False)
            or (doc.get("case_slug") in suppressed["slugs"] if doc.get("case_slug") else False))


def rows(res: Result, parsed: list, orders: list = (), now: str = "") -> Result:
    """The judgment rows from parsed captions [(entry, sha, slug, version,
    caption.Judgment[, read_from])], the suppression rule applied. Pure."""
    parsed = [tuple(t) + ("text",) * (6 - len(t)) for t in parsed]      # a caller may leave read_from out: text
    marked = {j.citation for _, _, _, _, j, _ in parsed if j.suppression and j.citation}
    for entry, sha, slug, version, j, how in parsed:
        order = _ordered(j.citation, sha, orders)
        kinds = list(j.suppression_kinds) + (["ledger"] if order else [])
        if not j.suppression and j.citation in marked:
            kinds.append("another document of the citation")
        withheld = (f"suppression order: {order['reason']}" if order else WITHHELD_MARKER if kinds else None)
        stamp = {"document": sha, "read_from": how if how != "mixed" else "text",
                 "reader": CAPTION_READER, "profile": slug, "profile_version": version, "loaded_at": now}
        key = f"{sha}/judgment"
        court = j.court or COURT_CODES.get(j.court_name or "")
        res.judgments.append({
            "key": key, "citation": j.citation, "court": court, "court_name": j.court_name, "registry": j.registry,
            "case_numbers": j.case_numbers, "judgment_date": j.judgment_date, "date_basis": j.date_basis,
            "citation_basis": j.citation_basis,
            "hearing": j.hearing, "judges": j.judges, "heading": j.heading, "caption_shape": j.caption_shape,
            "outcome": j.outcome, "counsel_roles": list(j.counsel_roles), "paragraphs": len(j.paragraphs), "parties": len(j.parties),
            "suppression": bool(kinds), "suppression_kinds": kinds, "withheld": withheld, "status": j.status,
            "missing": j.missing, "unrecognised": len(j.unrecognised), "notes": j.notes, "case_slug": entry.get("case_slug"),
            "source": entry.get("source") or CAP.SOURCE, "source_url": entry.get("url"),
            "source_note": entry.get("note") or CAP.SOURCE_NOTE, "page": 1, "place": "caption", **stamp})
        for p in j.parties:
            pkey = f"{sha}/party/{p.position}"
            hide = bool(withheld) and not p.crown and not p.anonymised
            if hide:
                res.withheld.append(_kept(pkey, p.name, p.capacity, "judgment_parties", sha, j.citation,
                                          withheld + (f" ({', '.join(kinds)})" if kinds else "")))
            res.parties.append({
                "key": pkey, "judgment": key, "citation": j.citation, "position": p.position, "block": p.block,
                "role": p.role, "name": None if hide else p.name, "withheld": hide, "anonymised": p.anonymised,
                "crown": p.crown, "confidence": p.confidence, "capacity": None if hide else p.capacity,
                "page": 1, "place": f"caption, block {p.block}, party {p.position}", **stamp})
        res.paragraphs += [(key, n, pg, sha) for n, pg in j.paragraphs]
        if j.status != "parsed":
            res.set_aside.append((key, "parse", f"{j.status}: missing {', '.join(j.missing)}"))
    return res


# ── the page-reader piece ─────────────────────────────────────────────────────────────────────────────────────
def read_pages(sha256: str, *, url: str, model: str, store: rd.Store = None, dpi: int = None, post=None) -> dict:
    """One piece of `qv4-courts-pages`: every page of one scanned document
    with no text layer through the page reader on the card the worker holds,
    stored under profile `courts-scanned-document` (the load recognises the
    document again from that text). Counts only; no page text is printed."""
    from support.docread.read import read_document
    from support.docstore.landing import read_bytes
    store = store or rd.Store()
    version = profile_version(SCANNED)
    data = read_bytes(sha256)
    got = read_document(data, sha256, profile=SCANNED, profile_version=version, store=store, page_reader=True,
                        dpi=dpi, url=url, model=model, post=post)
    return {"document": sha256, "pages": len(got.readings) + len(got.unread), "read_now": len(got.readings) - got.replayed,
            "replayed": got.replayed, "unread": list(got.unread)}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "--pages":
        line = read_pages(argv[-1], url=os.environ["QV4_MODEL_URL"], model=os.environ["QV4_MODEL"])
        print(f"courts pages: {line['document'][:12]}: {line['pages']} page(s), read now {line['read_now']}, "
              f"replayed {line['replayed']}, unread {line['unread']}")
        return 1 if line["unread"] else 0
    print("usage: python -m registers.courts.read --pages SHA256   (the page-reader piece; QV4_MODEL_URL and QV4_MODEL from the worker)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
