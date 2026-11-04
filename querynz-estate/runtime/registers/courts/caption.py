"""The caption grammar of a New Zealand judgment, read from the text layer
with its layout kept (`pdftotext -layout`, one page at a time). Pure:
stdlib only, no model, no network, no database.

Taken as ideas from the old estate's `courts_register/parse.py` (its civil
BETWEEN/AND grammar with ordinal and parenthetical roles, the criminal
KING v DEFENDANT grammar, the wrapped-name rejoin flagged low, an
anonymised party flagged and never expanded) and rebuilt on what the held
documents show (docs/research/legal-documents.md):

  the court      "IN THE SUPREME COURT OF NEW ZEALAND" and its te reo line
  the registry   "AUCKLAND REGISTRY" (the High Court only)
  case numbers   "SC 106/2022", "CA274/2022", "CIV-2026-404-000001", "CRI-…"
  the citation   "[2024] NZSC 161", on its own line under the case numbers;
                 a banner above the court line may cite ANOTHER judgment, so
                 only a citation on a line of its own after the court line counts
  the parties    BETWEEN / AND, the name in the right-hand column, its role on
                 the line under it ("Appellant", "First Respondents", …); or,
                 in a criminal caption, the prosecutor above a lone "v" and each
                 defendant on a line of its own below it
  labels         "Hearing:", "Court:", "Counsel:", "Appearances:", "Judgment:"
  suppression    a banner above the court line ("NOTE: PUBLICATION OF NAME …
                 PROHIBITED BY S 203 …", "ORDER PROHIBITING PUBLICATION …"), or an
                 order prohibiting or suppressing publication in the text
  paragraphs     "[12]" at the start of a line, with its page
  outcome        "The appeal is dismissed." in the orders under the judgment's
                 heading, kept as a closed vocabulary ("appeal dismissed"), never
                 as text

A role printed in the singular ("Appellant") holds one party however many
lines its name wraps over; a role in the plural ("Respondents") holds one
party per line once wrapped names are rejoined, and is marked low when a
rejoin was needed. A consolidated appeal names several parties in one
block: one Party per party, each with its role.

    parse(pages: dict[int, str], file_name: str = "") -> Judgment
"""
import dataclasses
import datetime as dt
import re
from dataclasses import dataclass, field

VERSION = "registers.courts.caption 2"

COURTS = {"SUPREME COURT": "NZSC", "COURT OF APPEAL": "NZCA", "HIGH COURT": "NZHC", "DISTRICT COURT": "NZDC",
          "EMPLOYMENT COURT": "NZEmpC", "ENVIRONMENT COURT": "NZEnvC", "FAMILY COURT": "NZFC",
          "EMPLOYMENT RELATIONS AUTHORITY": "NZERA", "HUMAN RIGHTS REVIEW TRIBUNAL": "NZHRRT"}
#: one spelling of each court code, however a citation or a file name cases it ("NZEMPC" in a file name is NZEmpC)
COURT_CODES = {c.upper(): c for c in ("NZSC", "NZCA", "NZHC", "NZDC", "NZFC", "NZYC", "NZEmpC", "NZEnvC", "NZERA", "NZCC",
                                      "NZHRRT", "NZIPT", "NZACC", "NZLCRO", "NZDT", "NZTT", "NZREADT", "NZMVDT", "NZSSAA", "NZIACDT")}


def court_code(code: str) -> str:
    """The court's code in its one spelling; a code not in the list as the citation printed it."""
    return COURT_CODES.get((code or "").upper(), code)
CITE = re.compile(r"\[(\d{4})\]\s+(NZ[A-Za-z]{2,6})\s+(\d{1,5})\b")
CITE_LINE = re.compile(r"^\s*\[(\d{4})\]\s+(NZ[A-Za-z]{2,6})\s+(\d{1,5})\s*$")
FILE_CITE = re.compile(r"(\d{4})-(NZ[A-Za-z]{2,6})-(\d{1,5})(?:[^0-9].*)?\.pdf$", re.I)
#: the court line; a hearing transcript's cover sheet prints the case number beside it on the same line
COURT_LINE = re.compile(r"^\s*IN THE ([A-ZĀĒĪŌŪ ]+?) OF NEW ZEALAND\b[^\n]*$", re.M)
#: the same without "OF NEW ZEALAND": the District Court ("IN THE DISTRICT COURT AT …"), the Employment Relations Authority,
#: the Human Rights Review Tribunal and any tribunal or authority (fix-2, 31 October 2026). An explicit alternation first:
#: a lazy class alone matched COURT inside COURT OF APPEAL (lesson); "IN THE MATTER OF THE … TRIBUNAL" is a subject, not a court
COURT_LINE_BARE = re.compile(r"^\s*IN THE (SUPREME COURT|COURT OF APPEAL|HIGH COURT|DISTRICT COURT|EMPLOYMENT COURT|FAMILY COURT|"
                             r"YOUTH COURT|ENVIRONMENT COURT|CORONERS COURT|MĀORI LAND COURT|MAORI LAND COURT|"
                             r"EMPLOYMENT RELATIONS AUTHORITY|HUMAN RIGHTS REVIEW TRIBUNAL|(?!MATTER\b)[A-ZĀĒĪŌŪ' ]+? (?:TRIBUNAL|AUTHORITY))"
                             r"(?= AT\b|\s{2,}|\s*$)[^\n]*$", re.M)


def court_line(text: str):
    """The court line's match (group 1 the court's name), with or without "OF NEW ZEALAND", or None."""
    return COURT_LINE.search(text or "") or COURT_LINE_BARE.search(text or "")
REO_LINE = re.compile(r"^\s*I TE K[OŌ]TI\b", re.M)
REGISTRY = re.compile(r"^\s*([A-ZĀĒĪŌŪ'’\- ]{3,40}?) REGISTRY\s*$")
CASE_NO = re.compile(r"\b(SC \d{1,4}/\d{4}|CA ?\d{1,4}/\d{4}|(?:CIV|CRI|CRC|CIVP)-\d{4}-\d{3}-\d{1,6})\b")
#: a label: a known one anywhere, or any capitalised word or two at the left margin ending in a colon
#: ("Further hearing:", "Sentencing hearing:"); a party's name sits in the right-hand column, never at the margin
LABEL = re.compile(r"^\s*(?:(?:Hearings?|Court|Counsel|Appearances|Judgments?|Sentence|Sentenced|Plea|Verdict|Date|"
                   r"Delivered|Submissions|Representation|Solicitors|Ruling|Decision|Minute|Trial|Result|On the papers|"
                   # the Employment Relations Authority's and the tribunals' labels (fix-2)
                   r"Member of Authority|Representatives?|Investigation(?: Meeting)?|Submissions? [Rr]eceived|Information [Rr]eceived|"
                   r"Determination|Date of [Dd]etermination|Date of [Dd]ecision|BEFORE|REPRESENTATION|DATE OF HEARING|DATE OF DECISION|"
                   r"DATE OF LAST SUBMISSIONS|HEARD AT|Decision No|Reference No)\s*:"
                   r"|\s{0,6}[A-Z][a-z]+(?:[ /][a-z(][a-z)]+){0,3}\s*:(?:\s|$))")
PARTY_LABEL = re.compile(r"^\s*(AND IN THE MATTER OF|IN THE MATTER OF|IN THE MATTER|AND BETWEEN|BETWEEN|UNDER|AND)\b(?:\s{2,}(.*\S))?\s*$")
_ORD = r"(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth)"
_BASE = (r"(?:Cross[- ])?(?:Appellants?|Respondents?|Applicants?|Plaintiffs?|Defendants?|Interveners?|Intervenors?|"
         r"Claimants?|Objectors?|Informants?|Prosecutors?|Referrers?|Judgment (?:Debtors?|Creditors?)|"
         r"(?:Third|Interested|Non)[- ]Part(?:y|ies))")
ROLE = re.compile(rf"^(?:(?:Shareholder|Director|Trustee|Executor|Administrator|Guardian|Liquidator|Receiver)s? of (?:the )?)?"
                  rf"(?:{_ORD}(?: and {_ORD})? )?(?:Intended |Proposed |Putative )?{_BASE}"
                  rf"(?:\s*(?:/|and)\s*(?:{_ORD} )?{_BASE})*"
                  r"(?:\s*\([^)]{1,80}\)|\s+in\s+(?:SC|CA)\s?\d{1,4}/\d{4}.{0,40}|\s+\(?[A-Z]{2,3}\s?\d{1,4}/\d{4}\)?)?\.?$", re.I)
PLURAL = re.compile(r"(?:Appellants|Respondents|Applicants|Plaintiffs|Defendants|Interveners|Intervenors|Claimants|Objectors|"
                    r"Informants|Prosecutors|Referrers|Debtors|Creditors|Parties)\b", re.I)
#: an anonymised party: an initial or two, an initial with a case number, "MR N"; flagged, never expanded
ANON = re.compile(r"^(?:[A-Z]{1,3}|[A-Z]{1,3} \([A-Z0-9 ,/]{3,40}\)|(?:MR|MS|MRS|MISS|DR) [A-Z])$")
#: the Crown and the public prosecutors: a suppression order never covers them. The pattern is matched on the
#: upper-cased name both by Python (re.match) and by Postgres (`~`, model_read.kept_sql), so it is written in the
#: part of the dialect both share: anchored at both ends, no \b (a backspace to Postgres, which is why the check
#: and the load disagreed on 31 October 2026), no \d, no flags
CROWN = re.compile(r"^(?:THE KING|THE QUEEN|R|THE CROWN|CROWN|HIS MAJESTY THE KING|NEW ZEALAND POLICE|POLICE|"
                   r"(?:THE )?ATTORNEY[- ]GENERAL(?:[^A-Z0-9].*)?|(?:THE )?SOLICITOR[- ]GENERAL(?:[^A-Z0-9].*)?|"
                   r"COMMISSIONER OF INLAND REVENUE|COMMISSIONER OF POLICE|SERIOUS FRAUD OFFICE|DIRECTOR OF THE SERIOUS FRAUD OFFICE)$")
_PREV_OPEN = re.compile(r"(?:,|&|\(|-|\b(?:AND|OF|ON|THE|TE|O|NGĀTI|NGATI|NGĀ|NGA|ME|MŌ|MO|KI|FOR|IN|AS|BY|TO|AT|A))$")
_CURR_CONT = re.compile(r"^(?:\(|&|AND\b|ME\b|OF\b|TRUST\b|TRUSTEES?\b|INCORPORATED\b|INC\b|LIMITED\b|LTD\b|BOARD\b|"
                        r"COMPANY\b|PARTNERSHIP\b|SOCIETY\b|CORPORATION\b|AUTHORITY\b|COUNCIL\b|ASSOCIATION\b|"
                        r"HOLDINGS\b|GROUP\b|INVESTMENTS?\b|PROPERTIES\b|NOMINEES\b|SERVICES\b|DEVELOPMENTS?\b)")
#: a banner or an order that prohibits or suppresses publication
SUPPRESS = re.compile(r"PROHIBIT\w*\s+(?:THE\s+)?PUBLICATION|PUBLICATION\s+(?:OF\s+.{0,160}?)?PROHIBITED|SUPPRESS|"
                      r"NON-PUBLICATION|RESTRICTIONS ON PUBLISHING|PUBLICATION OF .{0,80}NOT PERMITTED|"
                      r"FAMILY COURT ACT 1980|NOT TO BE PUBLISHED", re.I | re.S)
BODY_SUPPRESS = re.compile(r"\border\w*\s+(?:prohibiting|suppressing|for\s+(?:permanent|interim)\s+suppression)|"
                           r"\b(?:permanent|interim|final)\s+(?:name\s+)?suppression\b|\bname\s+suppression\b|"
                           r"\bsuppression\s+(?:of\s+(?:the\s+|his\s+|her\s+|their\s+)?name|order)|"
                           r"\bsuppress(?:es|ed|ing)?\s+(?:the\s+|his\s+|her\s+|their\s+)?(?:names?|identity|identifying)|"
                           r"\bprohibit(?:s|ed|ing)?\s+(?:the\s+)?publication|"
                           # the Employment Relations Authority's and the tribunals' wording (fix-2: measured on 292 determinations
                           # and 507 tribunal decisions, 31 October 2026)
                           r"\bnon-publication\s+orders?\b|\borders?\s+(?:for|of)\s+non-publication\b|\b(?:is|are|be|been)\s+anonymi[sz]ed\b", re.I)
STATUTE = re.compile(r"\bSS?\s?(\d{2,3}[A-Z]?)\b(?:\([0-9a-z]+\))*\s+(?:OF\s+THE\s+)?CRIMINAL PROCEDURE ACT 2011", re.I)
#: a numbered paragraph: "[12]" at the left margin, followed by words; not "[2024] NZSC 161" (a citation in a
#: footnote) and not a paragraph quoted from another judgment (indented, or out of the sequence)
PARA = re.compile(r"^(\s{0,12})\[(\d{1,4})\]\s+(?![A-Z]{2,}[a-z]*\s+\d|\d+\s+[A-Z]{2,})\S")
DATE = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")
RUNHEAD = re.compile(r"\[(\d{4})\]\s+NZ[A-Z]{2,5}\s+\d{1,5}\s+\[(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})\]")
DELIVERED = re.compile(r"This (?:judgment|decision|ruling) was delivered by (?:me|the Court|Justice [^\n]{1,40}?) on\s+(\d{1,2} [A-Z][a-z]+ \d{4})")
HEADING = re.compile(r"^\s*((?:\(?ORAL\)?\s+|RESERVED\s+|INTERLOCUTORY\s+|COSTS\s+|SUPPLEMENTARY\s+|FURTHER\s+)?"
                     r"(?:JUDGMENT|JUDGMENTS|SENTENCING NOTES|SENTENCING REMARKS|NOTES ON SENTENCING|REASONS FOR JUDGMENT|"
                     r"REASONS|MINUTE|RULING|DECISION|RESULT|DETERMINATION)(?:\s+\(No \d+\))?)\s+OF\s+(.{2,90}?)\s*$", re.M)
OUTCOME = re.compile(r"\b(cross-appeal|appeals?|applications?|application for leave to appeal|leave to appeal|"
                     r"application for an extension of time(?: to appeal)?|application for recall|application for judicial review|"
                     r"claim|proceeding|charge|conviction|sentence)\b[^.;\n]{0,80}?\b(?:is|are)\s+(?:therefore\s+|accordingly\s+)?"
                     r"(dismissed|allowed|granted|declined|quashed|struck out|refused|adjourned|discontinued|upheld|set aside)",
                     re.I)
MONTHS = {m: i for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"), 1)}


@dataclass
class Party:
    name: str
    role: str
    position: int
    block: int                      # the caption block it was read from (BETWEEN = 1, each AND one more)
    anonymised: bool = False
    crown: bool = False
    confidence: str = "high"        # low: its name was rejoined from wrapped lines in a plural role, or split
    capacity: str = None            # "as trustees of THE … TRUST", as printed under the names it qualifies


@dataclass
class Judgment:
    citation: str = None
    court: str = None               # NZSC, NZCA, NZHC (from the citation; the court line agrees or it is a line)
    court_name: str = None          # as the court line prints it: "SUPREME COURT"
    registry: str = None
    case_numbers: list = field(default_factory=list)
    caption_shape: str = None       # between | criminal | matter | none
    parties: list = field(default_factory=list)
    hearing: str = None             # as printed
    judges: str = None              # the Court: line, else the heading's "OF …"
    heading: str = None             # JUDGMENT OF THE COURT, SENTENCING NOTES, …
    judgment_date: dt.date = None
    date_basis: str = None          # label | running head | delivered; the load's: mcp doc_date (read.from_mcp)
    citation_basis: str = None      # the load's (read.from_mcp): document | mcp citation
    suppression: bool = False
    suppression_kinds: list = field(default_factory=list)   # banner, order in the text, CPA s 203, Family Court Act, until, paragraphs
    paragraphs: list = field(default_factory=list)           # (number, page)
    outcome: list = field(default_factory=list)              # "appeal dismissed", …
    counsel_roles: list = field(default_factory=list)        # the roles the counsel lines are "for"
    unrecognised: list = field(default_factory=list)         # caption lines no grammar took (their count is what is kept)
    notes: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.missing:
            return "parsed"
        return "partial" if self.citation and self.court else "unparsed"


#: what the caption records about its own reading, not about the document (the judgment row's housekeeping)
DIAGNOSTIC = ("unrecognised", "notes", "missing")
#: the fields the caption grammar reads from a judgment: the profiles' `by: rules` items (support/profiles/align.py)
FIELDS = tuple(f.name for f in dataclasses.fields(Judgment) if f.name not in DIAGNOSTIC)


#: the years a court document can be dated in: the colony's first courts to 2100. A date outside is the printer's slip,
#: never the document's date (the Environment Court printed "17 October 3023" on a 2023 filing, 3 November 2026). The
#: upper bound is not next year because the lane's own invented documents are dated 2099, so they are never mistaken
#: for real ones.
EARLIEST_YEAR = 1840
LATEST_YEAR = 2100


def possible_year(y: int) -> bool:
    return EARLIEST_YEAR <= y <= LATEST_YEAR


def _date(s: str):
    m = DATE.search(s or "")
    if not m or not possible_year(int(m.group(3))):
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def _upper_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def file_citation(name: str):
    m = FILE_CITE.search(name or "")
    return f"[{m.group(1)}] {court_code(m.group(2))} {m.group(3)}" if m else None


def banner_of(page1: str) -> str:
    """The text above the court line: a suppression banner when there is one."""
    m = court_line(page1)
    return page1[:m.start()] if m else ""


def suppression_kinds(banner: str, body: str) -> list:
    kinds = []
    if banner.strip() and SUPPRESS.search(banner):
        kinds.append("banner")
        for s in sorted({m.group(1).upper() for m in STATUTE.finditer(banner)}):
            kinds.append(f"CPA s {s}")
        if re.search(r"FAMILY COURT ACT 1980|family-court", banner, re.I):
            kinds.append("Family Court Act")
        if re.search(r"\bUNTIL\b", banner):
            kinds.append("until")
        if re.search(r"\[\d{1,3}\]", banner):
            kinds.append("paragraphs")
    if BODY_SUPPRESS.search(body or ""):
        kinds.append("order in the text")
    return kinds


def _merge(lines: list) -> tuple:
    """Rejoin names pdftotext wrapped: (names, rejoined_any)."""
    names, joined = [], False
    for ln in lines:
        if names and (_PREV_OPEN.search(names[-1]) and len(names[-1].split()) > 1
                      or _CURR_CONT.match(ln) or names[-1].count("(") > names[-1].count(")")):
            names[-1] = f"{names[-1]} {ln}"
            joined = True
        else:
            names.append(ln)
    return names, joined


def _split_initials(name: str) -> list:
    """"A, B AND C": several anonymised parties on one line."""
    parts = [p.strip() for p in re.split(r",\s*|\s+(?:AND|and)\s+", name) if p.strip()]
    return parts if len(parts) > 1 and all(ANON.match(p) for p in parts) else [name]


def _outside_brackets(s: str) -> str:
    out, depth = [], 0
    for ch in s:
        depth += ch == "("
        out.append(ch if depth == 0 else " ")
        depth -= ch == ")" and depth > 0
    return "".join(out)


def _split_list(s: str) -> list:
    """Split at ", " and " AND " / " and " outside brackets."""
    mask = _outside_brackets(s)
    cuts, i = [], 0
    for m in re.finditer(r",\s*|(?:^|\s+)(?:AND|and)\s+", mask):
        cuts.append(s[i:m.start()])
        i = m.end()
    cuts.append(s[i:])
    return [c.strip() for c in cuts if c.strip()]


_LISTY = re.compile(r",|(?:^|\s)AND(?:\s|$)")
DESCRIPTOR = re.compile(r"(?:^|\s)((?:as|being|trading as|t/a|in (?:his|her|their|its) capacity)\b.*)$")
LIST_END = re.compile(r"(?:,|\s+and)$")


def _emit(out: list, lines: list, role: str, block: int) -> None:
    lines = [re.sub(r"\s{2,}", " ", l).strip() for l in lines if l.strip()]
    if not lines:
        return
    # a capacity in lower case ("as trustees of") qualifies every name above it; the caps lines after it are its object
    names_lines, cap = [], []
    for l in lines:
        if cap:
            cap.append(l)
            continue
        m = DESCRIPTOR.search(l)
        if m:
            cap.append(m.group(1))
            if l[:m.start()].strip():
                names_lines.append(l[:m.start()].strip())
        else:
            names_lines.append(l)
    capacity = " ".join(cap) or None
    plural = bool(PLURAL.search(role))
    if not names_lines:
        return
    if not plural:
        names, low = [" ".join(names_lines)], False
        split = _split_initials(names[0])
        if len(split) > 1:
            names = split
    elif any(_LISTY.search(_outside_brackets(l)) for l in names_lines):
        # a list of people wrapped at the column ("A B, C D, E F AND G H") among names stacked one to a line:
        # a group runs while its lines carry a comma or an AND, or end in one, or leave a bracket open, and is
        # split at the commas and ANDs outside brackets; a stacked line is a name as in any plural block. A
        # company named with a comma or an AND would be split too, so the whole block is low
        names, low, group = [], True, []
        listy = [bool(_LISTY.search(_outside_brackets(l))) for l in names_lines]
        for i, l in enumerate(names_lines):
            if group or listy[i]:
                group.append(l)
                text = " ".join(group)
                more = i + 1 < len(names_lines) and (listy[i + 1] or re.search(r"(?:,|\bAND|\band|&)$", l)
                                                     or text.count("(") > text.count(")"))
                if not more:
                    names += _split_list(text)
                    group = []
                continue
            if names and (_CURR_CONT.match(l) or (_PREV_OPEN.search(names[-1]) and len(names[-1].split()) > 1)
                          or names[-1].count("(") > names[-1].count(")")):
                names[-1] = f"{names[-1]} {l}"
            else:
                names.append(l)
        names = [p for n in names for p in _split_initials(n)]
    else:
        # a line ending in a lower-case "and" or a comma closes a name in a list; any other line may wrap
        names, low, run = [], False, []
        for l in names_lines + [None]:
            if l is not None:
                run.append(LIST_END.sub("", l) if LIST_END.search(l) else l)
            if l is None or LIST_END.search(l):
                merged, joined = _merge(run)
                names += merged
                low = low or joined
                run = []
        names = [p for n in names for p in _split_initials(n)]
    for n in names:
        n = n.strip().rstrip(",")
        if not n:
            continue
        out.append(Party(name=n, role=role.strip().rstrip("."), position=len(out) + 1, block=block,
                         anonymised=bool(ANON.match(n)), crown=bool(CROWN.match(n)),
                         confidence="low" if low else "high", capacity=capacity))


OVER = re.compile(r"^\s*(?:…|\.{2,})?\s*\(?\s*(?:continued\s+|cont(?:['’]?d|\.)\s+|turn\s+|please\s+turn\s+)?over(?:leaf)?\b[^A-Za-z]*\)?\s*$", re.I)


def _caption_lines(text: str, start: int) -> tuple:
    """(the caption's lines after the court line up to the first label, whether a label ended them).
    A line at the left margin is a running head or a footnote, never the caption (whose names sit in
    the right-hand column, whose labels are indented and whose criminal names are centred)."""
    out = []
    for ln in text[start:].splitlines():
        if LABEL.match(ln):
            return out, True
        if ln.strip() and len(ln) - len(ln.lstrip()) < 4 and not PARTY_LABEL.match(ln) or OVER.match(ln):
            continue
        out.append(ln)
    return out, False


def _marked_over(text: str) -> bool:
    """Whether the caption, from the court line to its first label, carries a "continued over" line."""
    for ln in text.splitlines():
        if LABEL.match(ln):
            return False
        if OVER.match(ln) and ln.strip():
            return True
    return False


def _between(lines: list) -> tuple:
    """(parties, shape, unrecognised) from BETWEEN / AND blocks."""
    parties, pending, mode, block, unrec = [], [], None, 0, []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        m = PARTY_LABEL.match(raw)
        if m:
            if pending and mode == "party":
                unrec.extend(pending)
            pending = []
            label, rest = m.group(1), (m.group(2) or "").strip()
            if "MATTER" in label or label == "UNDER":
                # the subject of the proceeding (a statute, an estate, a reference); it is a party only when a
                # role line follows it ("… REFERENCE (NO 1 OF 2024) / Referrer")
                mode, block = "matter", block + 1
                if rest:
                    pending.append(rest)
                continue
            mode, block = "party", block + 1
            if rest:
                if ROLE.match(rest):
                    unrec.append(rest)
                else:
                    pending.append(rest)
            continue
        if mode == "matter":
            if ROLE.match(s):
                _emit(parties, pending, s, block)
                pending, mode = [], "party"
            elif not CASE_NO.fullmatch(s):
                pending.append(s)
            continue
        if mode != "party":
            continue
        if ROLE.match(s):
            if pending:
                _emit(parties, pending, s, block)
            else:
                unrec.append(s)
            pending = []            # the block runs on: another name and its role may follow (First / Second Plaintiff)
            continue
        if CASE_NO.fullmatch(s) or CITE_LINE.match(raw):
            continue
        if _upper_ratio(s) >= 0.6 or s.startswith("(") or _anon_list(s) or (pending and DESCRIPTOR.search(s)):
            pending.append(s)
        else:
            unrec.append(s)
    if mode == "party":
        unrec.extend(pending)
    return parties, unrec


def _anon_list(s: str) -> bool:
    """"X and S", "A, B AND C": a line of anonymised parties, whatever its case."""
    return len(_split_initials(re.sub(r"\s+and\s+", " AND ", s))) > 1


def _criminal(lines: list) -> tuple:
    """(parties, unrecognised): the prosecutor above a lone "v", each
    defendant below it on a line of its own (a wrapped name rejoined)."""
    body = [l.strip() for l in lines if l.strip()]
    try:
        vi = next(i for i, l in enumerate(body) if l in ("v", "V"))
    except StopIteration:
        return [], []
    above = [l for l in body[:vi] if _upper_ratio(l) >= 0.6 and not CASE_NO.search(l) and not CITE.search(l)
             and not REGISTRY.match(l) and not REO_LINE.match(l)]
    # the court line's te reo and the registry's te reo name sit above the citation; the prosecutor is the
    # last caps run above the "v", after the citation line
    cite_at = max((i for i, l in enumerate(body[:vi]) if CITE.search(l)), default=-1)
    above = [l for l in body[cite_at + 1:vi] if _upper_ratio(l) >= 0.6]
    below = [l for l in body[vi + 1:] if not CASE_NO.fullmatch(l)]
    parties, unrec = [], []
    if above:
        _emit(parties, above, "Prosecutor", 1)
    keep = [l for l in below if _upper_ratio(l) >= 0.6 or _anon_list(l)]
    # "A B &" over "C D": two defendants, unless the next line finishes a company's name
    names, joined, run = [], False, []
    for i, l in enumerate(keep):
        m = re.search(r"\s+(?:&|AND)$", l)
        if m and i + 1 < len(keep) and not _CURR_CONT.match(keep[i + 1]):
            run.append(l[:m.start()])
            got, _ = _merge(run)
            names += got
            run, joined = [], True
        else:
            run.append(l)
    got, j2 = _merge(run)
    names += got
    joined = joined or j2
    unrec.extend(l for l in below if l not in keep)
    for n in names:
        for p in _split_initials(n):
            parties.append(Party(name=p, role="Defendant", position=len(parties) + 1, block=2,
                                 anonymised=bool(ANON.match(p)), crown=bool(CROWN.match(p)),
                                 confidence="low" if joined else "high"))
    return parties, unrec


def _label_value(page: str, label: str) -> str:
    """A label's value with its wrapped lines (the next lines indented under it), as printed."""
    lines = page.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(rf"^(\s*{label}\s*:\s*)(.*)$", ln, re.I)
        if not m:
            continue
        col = len(m.group(1))
        out = [m.group(2).strip()]
        for nxt in lines[i + 1:i + 6]:
            # the wrapped lines sit under the value; a label on a line of its own (the Tribunal's BEFORE:, REPRESENTATION:)
            # has its values on the lines beneath it, to the next blank line or label
            if not nxt.strip() or LABEL.match(nxt) or (out[0] and len(nxt) - len(nxt.lstrip()) < col - 2):
                break
            out.append(nxt.strip())
        return " ".join(x for x in out if x)
    return None


#: a tribunal's date line, the label with or without its colon: "DATE OF DECISION 25 June 2023", "Date of Minute:", "Date of
#: Reasons for Decision:", "Date of Costs Decision:", "Dated 25 June 2023", "Decision issued on"; never the hearing's or the
#: last submissions' date
DATED_LINE = re.compile(r"^\s*(?:Date of (?!Hearing|Last Submissions|Oral)(?:[A-Za-z]+ ){0,4}?(?:Determination|Decision|Minute|Ruling|Judgment|Order)|"
                        r"Dated|Decision issued on|Determination issued on)\s*:?\s*(\d{1,2} [A-Z][a-z]+ \d{4})", re.M | re.I)


def _dated_line(head: str):
    m = DATED_LINE.search(head or "")
    return m.group(1) if m else None


def _counsel_roles(page: str) -> list:
    text = " ".join(filter(None, (_label_value(page, "Counsel"), _label_value(page, "Appearances"))))
    roles = re.findall(rf"\bfor\s+(?:the\s+)?((?:{_ORD}(?: and {_ORD})? )?(?:Intended |Proposed )?{_BASE})", text, re.I)
    return sorted({r.strip().title() for r in roles})


def parse(pages: dict, file_name: str = "") -> Judgment:
    """pages: page number (from 1) → that page's text layer."""
    out = Judgment()
    p1 = pages.get(1) or ""
    # a caption longer than a page runs on: read the caption from pages 1 and 2 together
    head = p1 + "\n" + (pages.get(2) or "")
    cl = court_line(head)
    if cl:
        out.court_name = cl.group(1).strip()
    start = cl.end() if cl else 0
    header_lines = [cl.group(0)[cl.end(1) - cl.start():]] if cl else []    # a case number printed beside the court line
    for ln in head[start:].splitlines():
        if PARTY_LABEL.match(ln) or LABEL.match(ln) or ln.strip() in ("v", "V"):
            break
        header_lines.append(ln)
    for ln in header_lines:
        m = CITE_LINE.match(ln)
        if m and not out.citation:
            out.citation, out.court = f"[{m.group(1)}] {court_code(m.group(2))} {m.group(3)}", court_code(m.group(2))
        r = REGISTRY.match(ln)
        if r and not out.registry:
            out.registry = r.group(1).strip()
        out.case_numbers += [c.replace("  ", " ") for c in CASE_NO.findall(ln) if c not in out.case_numbers]
    fc = file_citation(file_name)
    if out.citation is None:
        # the citation on a line with other text (a case number beside it), still after the court line
        m = CITE.search("\n".join(header_lines))
        if m:
            out.citation, out.court = f"[{m.group(1)}] {court_code(m.group(2))} {m.group(3)}", court_code(m.group(2))
    if out.citation is None and fc:
        out.citation, out.court = fc, fc.split()[1]
        out.notes.append("citation from the file name")
    elif fc and out.citation != fc:
        out.notes.append(f"the file name says {fc}")
    if out.court_name and COURTS.get(out.court_name) and out.court and COURTS[out.court_name] != out.court:
        out.notes.append(f"the court line says {out.court_name}")
    if out.court is None and COURTS.get(out.court_name):
        out.court = COURTS[out.court_name]          # no citation (a transcript's cover sheet): the court line names the court

    cap, labelled = _caption_lines(p1, cl.end()) if cl and cl.end() <= len(p1) else _caption_lines(head, start)
    nxt = [l for l in (pages.get(2) or "").splitlines() if l.strip()]
    if cl and cl.end() <= len(p1) and not labelled:
        # a caption longer than its page: it runs on at the top of page 2 to the first label
        cap += _caption_lines(pages.get(2) or "", 0)[0]
        out.notes.append("caption continued on page 2")
    elif cl and cl.end() <= len(p1) and nxt and (PARTY_LABEL.match(nxt[0]) or _marked_over(p1[cl.end():])):
        # the caption runs on over the page ("Continued over"): its blocks continue at the top of page 2, with an AND
        # or, where page 1 says so, straight on with the last block's next name and role (the High Court's
        # "… continued over" above the Hearing label, page 2 opening on "… / Fourth Defendants")
        more = []
        for l in nxt:
            if LABEL.match(l) or HEADING.match(l) or PARA.match(l):
                break
            more.append(l)
        cap += more
        out.notes.append("caption continued on page 2")
    if any(PARTY_LABEL.match(l) and PARTY_LABEL.match(l).group(1) in ("BETWEEN", "AND BETWEEN") for l in cap):
        out.caption_shape = "between"
        out.parties, out.unrecognised = _between(cap)
    elif any(l.strip() in ("v", "V") for l in cap):
        out.caption_shape = "criminal"
        out.parties, out.unrecognised = _criminal(cap)
    elif any("MATTER" in (PARTY_LABEL.match(l).group(1) if PARTY_LABEL.match(l) else "") for l in cap):
        out.caption_shape = "matter"
        out.parties, out.unrecognised = _between(cap)
    else:
        out.caption_shape = "none"

    out.hearing = _label_value(head, "Hearing")
    court = (_label_value(head, "Court") or _label_value(head, "Member of Authority") or _label_value(head, "Before")
             or _label_value(head, "Coram"))
    hd = HEADING.search(head)
    if hd:
        out.heading = re.sub(r"\s+", " ", hd.group(1)).strip("() ").upper()
        if not court:
            court = hd.group(2).strip()
    out.judges = re.sub(r"\s+", " ", court).strip() if court else None
    jl = (_label_value(head, "Judgment") or _label_value(head, "Sentence") or _label_value(head, "Sentenced")
          or _label_value(head, "Date of Determination") or _label_value(head, "Determination") or _label_value(head, "Date of Decision")
          or _label_value(head, "Decision") or _dated_line(head))
    for basis, val in (("label", jl), ("delivered", (DELIVERED.search(head) or [None, None])[1])):
        d = _date(val)
        if d:
            out.judgment_date, out.date_basis = d, basis
            break
    if out.judgment_date is None:
        for p in sorted(pages)[:3]:
            m = RUNHEAD.search(pages[p])
            if m:
                out.judgment_date, out.date_basis = _date(m.group(2)), "running head"
                break
    out.counsel_roles = _counsel_roles(head)

    banner = banner_of(p1)
    body = "\n".join([p1[len(banner):]] + [pages[p] for p in sorted(pages) if p != 1])
    out.suppression_kinds = suppression_kinds(banner, body)
    out.suppression = bool(out.suppression_kinds)
    want = 1
    for p in sorted(pages):
        for ln in pages[p].splitlines():
            m = PARA.match(ln)
            if m and int(m.group(2)) == want:
                out.paragraphs.append((want, p))
                want += 1
    if hd:
        orders = head[hd.end():]
        cut = re.search(r"^\s*_{5,}|^\s*REASONS\b|^\s{0,6}\[1\]\s", orders, re.M)
        orders = orders[:cut.start()] if cut else orders[:3000]
        for m in OUTCOME.finditer(orders):
            o = f"{m.group(1).lower()} {m.group(2).lower()}"
            if o not in out.outcome:
                out.outcome.append(o)

    for name, ok in (("citation", out.citation), ("court", out.court), ("judgment_date", out.judgment_date),
                     ("parties", out.parties)):
        if not ok:
            out.missing.append(name)
    return out


_ROLE_PARTS = re.compile(rf"({_ORD})|(Appellant|Respondent|Applicant|Plaintiff|Defendant|Intervener|Intervenor|Claimant|"
                         r"Objector|Informant|Prosecutor|Referrer|Debtor|Creditor|Party|Parties)", re.I)


def _role_key(role: str) -> tuple:
    """(ordinals, bases) of a role, singular and lower case; "Cross-" kept apart from the base it qualifies."""
    ords, bases = set(), set()
    for o, b in _ROLE_PARTS.findall(role or ""):
        if o:
            ords.add(o.lower())
        if b:
            bases.add("party" if b.lower() == "parties" else b.lower())
    return ords, bases


#: a criminal caption prints no role: its sides are the prosecutor and the defendant, and the counsel lines name them
#: by the stage ("for Applicant", "for Appellant", "for Respondent"; the Crown's line names no role _BASE takes)
CRIMINAL_SIDES = {"appellant", "applicant", "respondent", "defendant", "prosecutor"}
ORDINAL = {o.lower(): n for n, o in enumerate(_ORD[3:-1].split("|"), 1)}


def roles_unaccounted(j: Judgment) -> list:
    """The roles the counsel lines are "for" that no party of the caption
    holds: a party the caption grammar missed. "for Appellants" is held by a
    First and a Second Appellant; "for Second and Third Respondents" needs
    both. In a criminal caption (no printed role) the stage's words are
    held by its two sides, an ordinal by that many defendants."""
    held = [_role_key(p.role) for p in j.parties]
    out = []
    if j.caption_shape == "criminal":
        defendants = sum(1 for p in j.parties if p.role == "Defendant")
        for r in j.counsel_roles:
            ords, bases = _role_key(r)
            if not held or not bases <= CRIMINAL_SIDES or max((ORDINAL.get(o, 99) for o in ords), default=1) > max(defendants, 1):
                out.append(r)
        return out
    # a caption that prints its parties as one plural group with no ordinal ("... Respondents") holds every ordinal of
    # that base: counsel "for First and Sixth Respondents" (4 November 2026, one of the three the load's check held)
    grouped = {b for (o, bs), p in zip(held, j.parties) if not o and (p.role or "").strip().lower().endswith("s")
               for b in bs}
    for r in j.counsel_roles:
        ords, bases = _role_key(r)
        for b in bases:
            with_base = [o for o, bs in held if b in bs]
            if not with_base or (ords and b not in grouped and not ords <= set().union(*with_base)):
                out.append(r)
                break
    return out


#: the source's own inconsistencies: a counsel line "for" a role the caption truly does not hold, the court's
#: printing and not a party the grammar missed; counted apart, each judgment with its reason, never as a parse miss
INTERVENER_UNLISTED = "counsel for an intervener the caption does not list (leave to intervene given after the caption was set)"
APPEAL_UNDER_FIRST_INSTANCE = ("an appeal whose caption keeps the first instance's Plaintiff and Defendant while its counsel "
                               "lines name the appellant and the respondent")


def roles_source_exception(j: Judgment, short: list = None) -> str:
    """The reason a judgment's unaccounted counsel roles are the source's own
    printing, or None (then they are a parse miss). Two shapes only, each
    whole: every unaccounted role is an Intervener, in a caption that lists
    none; or a BETWEEN caption of Plaintiff and Defendant only whose every
    counsel line is for the Appellant or the Respondent, with no ordinal,
    and none of them held."""
    short = roles_unaccounted(j) if short is None else short
    if not short:
        return None
    held = set().union(*(_role_key(p.role)[1] for p in j.parties)) if j.parties else set()
    if all(b and b <= {"intervener", "intervenor"} for _, b in map(_role_key, short)) and not held & {"intervener", "intervenor"}:
        return INTERVENER_UNLISTED
    if (j.caption_shape == "between" and held == {"plaintiff", "defendant"} and sorted(short) == sorted(j.counsel_roles)
            and all(not o and b and b <= {"appellant", "respondent"} for o, b in map(_role_key, j.counsel_roles))):
        return APPEAL_UNDER_FIRST_INSTANCE
    return None
