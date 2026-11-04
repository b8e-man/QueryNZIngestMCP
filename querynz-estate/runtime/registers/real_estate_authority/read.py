"""The reading (step 5.3; Arthur, 2 November 2026: "alright do it"): each landed abstract page of the Authority's decisions
database read deterministically into one decision and the parties it names. No model: the abstract is a fixed form of
`<h4>LABEL</h4>` / `<p>value</p>` pairs under an `<h3>Complaint Number: …</h3>` heading (profile
`rea-decision-abstract`, v1; seen on every one of the 3,062 abstracts held on 2 November 2026).

What is read, and what is not:

  decision  the complaint number; the deciding body and whether it is an appeal, and the citation, from the heading
            under it ("Appeal Decision by the Real Estate Agents Disciplinary Tribunal: [2024] NZREADT 47"); the
            decision (the finding, and the note the page prints under it); the penalty as printed and its kinds (the
            "/ Censure / Fines" tags); the complaint and transaction types; the chairperson or judge; the sections of
            the Act and the code cited (their numbers only); the complaint history's dated steps and their PDFs
  parties   each licensee or agency the AGENT field names (an agency is printed "NAME (Agency)"), with its licence
            number where printed; each DEFENDANT of a prosecution (its abstract prints the court's heading as its <h3>
            and no complaint number), a company by its legal ending an organisation. "Represented by:" (counsel) is not
            a party
  private   every field the lane's tables do not read, whole, as printed: the REASONING text (read too for a suppression
            order) and the COMPLAINANT among them (`abstract_fields`, in real_estate_authority_private; ruling 142,
            4 November 2026)

Suppression: where the decision orders a licensee's name suppressed, the database prints no AGENT field. Where it prints
one and the text records a suppression order (not a request declined), the decision and its parties are flagged
`suppressed`; their names, licence numbers and the penalty text are left off the lane's tables and kept whole in the
private twin (`suppressed_parties`, `abstract_fields`; ruling 142). A penalty that names a street address is flagged
beside it (ruling 102).

    read_abstract(page, sha, version, case)   {"decision": {...}, "parties": [...], "set_aside": [...]}
"""
import html as _html
import re

PROFILE = "rea-decision-abstract"
READER = "registers.real_estate_authority.read 2"
SOURCE = "real_estate_authority"

HEADING = re.compile(r"<h3>\s*Complaint Number:(.*?)</h3>", re.S)
#: a prosecution's abstract prints no complaint number: its <h3> is the court's heading itself
COURT_HEADING = re.compile(r"<h3>\s*((?:Appeal )?Decision by the .*?)</h3>", re.S)
#: a defendant whose name ends as a company's does is an organisation, not a person
LEGAL_ENDING = re.compile(r"\b(?:Limited|Ltd\.?|Incorporated|Inc\.?|Trust|Company)\s*$", re.I)
SUBHEAD = re.compile(r'<h3>\s*Complaint Number:.*?</h3>\s*<h4[^>]*>(.*?)</h4>', re.S)
PAIR = re.compile(r'<h4[^>]*>\s*([^<]+?)\s*</h4>\s*</div>\s*<div class="pure-u-sm-2-3">\s*<p>(.*?)</p>', re.S)
#: the bodies a heading names, for a heading that prints no colon before its citation; a court's place in brackets
#: ("High Court (Wellington)") stays with the body
BODIES = ("Complaints Assessment Committee", "Real Estate Agents Disciplinary Tribunal", "High Court", "Court of Appeal",
          "Supreme Court")
#: "NAME (Agency)? (Licensee NNNNNNNN)"; one abstract prints "(Licensee (NNNNNNNN) )"
PARTY = re.compile(r"^(?P<name>.+?)\s*(?P<agency>\(Agency\))?\s*(?:\(Licensee\s*\(?\s*(?P<lic>\d+)\s*\)?\s*\))?\s*$")
HISTORY_ROW = re.compile(r"<tr>\s*<td[^>]*>\s*(\d{1,2} \w{3} \d{4}):?\s*</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S)
PDF = re.compile(r'href="(/reaa/pdfs/[^"]+\.pdf)"', re.I)
SECTION = re.compile(r"\[\s*(?:<a[^>]*>)?\s*([^<\]]+?)\s*(?:</a>)?\s*\]")
#: a suppression ORDERED, not a request declined ("there is insufficient reason to … suppression")
SUPPRESSED = re.compile(r"suppress\w*\s+(?:of\s+)?(?:the\s+)?(?:licensee|name|his|her|their)|name\s+suppression|"
                        r"name\s+was\s+suppressed|s(?:ection)?\s*108\b.{0,20}suppress|limiting\s+publication", re.I)
DECLINED = re.compile(r"insufficient\s+reason|declin\w*\s+(?:to\s+)?(?:the\s+)?(?:request\s+for\s+)?(?:name\s+)?suppress|"
                      r"request\s+for\s+(?:name\s+)?suppression\s+(?:is|was)\s+(?:declined|refused|not granted)", re.I)
#: a street address: a number then one to three capitalised words then a street word (as the diaries reader flags one)
STREET = re.compile(r"\b\d{1,5}[A-Za-z]?(?:\s*[-/]\s*\d{1,5}[A-Za-z]?)?,?\s+(?:[A-ZĀĒĪŌŪ][\w'’.-]*\s+){1,3}"
                    r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Place|Pl|Lane|Terrace|Tce|Crescent|Cres|Way|Grove|"
                    r"Close|Court|Ct|Parade|Highway|Hwy|Boulevard|Rise|Heights)\b")
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                      "Dec"), start=1)}
#: the abstract's fields the lane's own tables read; every other field is kept whole in the private twin (ruling 142)
READ_LABELS = frozenset({"DECISION", "PENALTY", "SENTENCE", "COMPLAINT TYPE", "TRANSACTION TYPE", "CHAIRPERSON", "JUDGE",
                         "CHARGE", "AGENT", "DEFENDANT", "COMPLAINT HISTORY"})
NOT_A_PARTY = re.compile(r"^(?:Represented by:|Search the public register)", re.I)


def text(fragment: str) -> str:
    """A fragment's text: tags out, entities read, spaces squashed."""
    t = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", _html.unescape(t).replace("\xa0", " ")).strip()


def lines(fragment: str) -> list:
    """A field's lines, split at <br> and at the tag boundaries the page prints (<em>, a table row)."""
    parts = re.split(r"<br\s*/?>|</?em>|</tr>", fragment or "")
    return [t for t in (text(p) for p in parts) if t]


def iso(day: str):
    m = re.match(r"(\d{1,2}) (\w{3}) (\d{4})", day or "")
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def heading(s: str) -> tuple:
    """'Appeal Decision by the Real Estate Agents Disciplinary Tribunal: [2024] NZREADT 47' -> (body, citation, appeal);
    the '(CAC)' after the Committee dropped; a heading with no colon is cut after the body it begins with."""
    appeal = s.startswith("Appeal ")
    rest = s[len("Appeal "):] if appeal else s
    if not rest.startswith("Decision by the "):
        return None, None, appeal
    rest = rest[len("Decision by the "):]
    if ":" in rest:
        body, cit = rest.split(":", 1)
    else:
        body = next((b for b in BODIES if rest.startswith(b)), rest)
        cit = rest[len(body):]
    body = body.replace("(CAC)", "").strip()
    cit = cit.replace("(CAC)", "").strip(" :")
    return body or None, cit or None, appeal


def recognise(page: bytes) -> bool:
    """The profile's landmarks: the complaint-number heading and at least the DECISION and COMPLAINT HISTORY pairs."""
    h = page.decode("utf-8", "replace") if isinstance(page, bytes) else page
    labels = {lab for lab, _ in PAIR.findall(h)}
    if HEADING.search(h):
        return {"DECISION", "COMPLAINT HISTORY"} <= labels
    return bool(COURT_HEADING.search(h)) and {"DEFENDANT", "DECISION"} <= labels


def kinds(fragment: str) -> list:
    """The penalty's kinds: the '/ Censure / Fines' tags the page prints in <em>."""
    em = " ".join(re.findall(r"<em>(.*?)</em>", fragment or "", re.S))
    return [k for k in (text(x) for x in text(em).split("/")) if k]


def parties_of(fragment: str, role: str) -> list:
    out = []
    for ln in re.split(r"<br\s*/?>", fragment or ""):
        t = text(ln)
        if not t or NOT_A_PARTY.match(t):
            continue
        m = PARTY.match(t)
        name = (m.group("name") if m else t).strip(" ,;")
        if not name:
            continue
        kind = "agency" if m and m.group("agency") else "organisation" if LEGAL_ENDING.search(name) else "person"
        out.append({"name": name, "kind": kind,
                    "licence_number": m.group("lic") if m else None, "role": role})
    return out


def read_abstract(page: bytes, sha: str, version: int, case: dict) -> dict:
    """`case`: the lane's row, {case_id, year, decision_date, body}. Returns the decision, its parties, its set-asides."""
    h = page.decode("utf-8", "replace")
    cid = case["case_id"]
    stamp = {"document": sha, "page": None, "read_from": "html", "reader": READER, "profile": PROFILE,
             "profile_version": version}
    if not recognise(h):
        return {"decision": None, "parties": [], "set_aside": [{"document": sha, "place": f"case {cid}",
                                                                 "stage": "recognise",
                                                                 "reason": f"not the {PROFILE} shape"}]}
    fields = {}
    for lab, val in PAIR.findall(h):
        fields.setdefault(lab, val)
    if HEADING.search(h):
        complaint = text(HEADING.search(h).group(1)) or None
        decided_by, citation, appeal = heading(text(SUBHEAD.search(h).group(1)) if SUBHEAD.search(h) else "")
    else:
        complaint = None
        decided_by, citation, appeal = heading(text(COURT_HEADING.search(h).group(1)))
    dec = lines(fields.get("DECISION"))
    pen = fields.get("PENALTY") or fields.get("SENTENCE")
    penalty = text(re.sub(r"<em>.*?</em>", " ", pen or "", flags=re.S)) or None
    whole = " ".join(text(v) for k, v in fields.items() if k != "COMPLAINT HISTORY")
    ordered = bool(SUPPRESSED.search(whole)) and not DECLINED.search(whole)
    history = []
    for day, cell in HISTORY_ROW.findall(fields.get("COMPLAINT HISTORY") or ""):
        step = re.sub(r"\s+\d+(?:\.\d+)?\s*[kKmM][bB]?$", "", text(re.sub(r"<a[^>]*>(.*?)</a>", r" \1 ", cell, flags=re.S)))
        history.append({"on": iso(day), "step": step,
                        "pdfs": PDF.findall(cell)})
    sections = {k: [text(s) for s in SECTION.findall(v)] for k, v in fields.items() if k.endswith("SECTIONS CITED")}
    parties = parties_of(fields.get("AGENT"), "licensee") + parties_of(fields.get("DEFENDANT"), "defendant")
    key = f"{SOURCE}/{cid}"
    decision = {
        "key": key, "case_id": cid, "complaint_number": complaint, "listed_body": case.get("body") or None,
        "decided_by": decided_by, "appeal": appeal, "citation": citation,
        "decided_on": case.get("decision_date"), "year": case.get("year"),
        "decision": dec[0] if dec else None, "decision_note": " ".join(dec[1:]) or None,
        "penalty": None if ordered and penalty else penalty, "penalty_kinds": kinds(pen),
        "penalty_names_address": bool(penalty and STREET.search(penalty)),
        "complaint_type": text(fields.get("COMPLAINT TYPE")) or None,
        "transaction_type": text(fields.get("TRANSACTION TYPE")) or None,
        "chairperson": text(fields.get("CHAIRPERSON") or fields.get("JUDGE")) or None,
        "charge": text(fields.get("CHARGE")) or None,
        "act_sections": sum((v for k, v in sections.items() if "ACT" in k), []),
        "code_sections": sum((v for k, v in sections.items() if "CODE" in k), []),
        "history": history, "parties_named": len(parties), "suppressed": ordered,
        "abstract_url": f"https://decisions.dotnous.com/reaa/v2/abstract.aspx?case={cid}",
        **stamp, "place": "abstract",
    }
    rows = []
    for i, p in enumerate(parties, start=1):
        rows.append({"key": f"{key}/party/{i}", "decision_key": key, "case_id": cid, "seq": i,
                     "name": None if ordered else p["name"],
                     "licence_number": None if ordered else p["licence_number"],
                     "kind": p["kind"], "role": p["role"], "suppressed": ordered,
                     "decided_on": decision["decided_on"], "decision": decision["decision"],
                     **stamp, "place": f"{'AGENT' if p['role'] == 'licensee' else 'DEFENDANT'}[{i}]"})
    private = [{"key": r["key"], "decision_key": key, "name": p["name"], "licence_number": p["licence_number"],
                "document": sha, "place": r["place"]} for r, p in zip(rows, parties) if ordered]
    read_labels = READ_LABELS - ({"PENALTY", "SENTENCE"} if ordered else set())
    kept = [{"key": key, "label": lab, "text": text(val) or None, "document": sha}
            for lab, val in fields.items() if lab not in read_labels and not lab.endswith("SECTIONS CITED")]
    return {"decision": decision, "parties": rows, "set_aside": [], "suppressed_parties": private,
            "abstract_fields": kept}
