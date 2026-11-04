"""The class 4 societies' own grants lists (Gambling Act 2003, s 110(4)), as
files: one layout per society's export, each a profile recognised by shape
and read from the text layer by word boxes (`pdftable`). The society is both
the publisher and the grantor of every row. A recipient is kept as printed
(a name the society cut short with '…' stays cut short) and never looked
up; no layout read prints an address. Decisions from 2017 on (ruling 71).

Each layout in `LAYOUTS` says: the society; the title lines that mark it and
give its period or decision date; the column heads, left to right; the anchor
column (every row has a figure there); how a wrapped cell is aligned; how a
row's status is told; and which column is the purpose as printed, if any.

    recognise(data)                 the profile slug, or None
    read_file(data, sha, slug)      Reading (read.Reading)
"""
import datetime as dt
import re

from registers.grants import pdftable, read

READER = "registers.grants.society 1"
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"


def a_day(text: str):
    """'1st July 2025', '31 Dec 2019', '16 December 2025' → date, or None."""
    m = re.fullmatch(_DAY, (text or "").strip())
    if not m or m.group(2)[:3].lower() not in MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    except ValueError:
        return None


_FIGURE = re.compile(r"(?<![\w.])-?\$?\s?-?\d[\d,]*(?:\.\d{1,2})?(?![\w.])")


def money(text: str):
    """'$ 5,865.00', '$27,720.33', '$0.00', '2948.5' → float; a cell with a word beside its one figure (a name's
    tail the text layer set in the amount column) → that figure; none, or two figures (rows run together) → None."""
    found = _FIGURE.findall(text or "")
    return read.amount(re.sub(r"\s+", "", found[0])) if len(found) == 1 else None


def status_by_word(row: dict, layout: dict) -> str:
    """Air Rescue to June 2023 and Milestone to 2020 print the decision as a word: APPROVED, FULLY APPROVED,
    APPROVED-PARTIAL, PARTIALLY APPROVED or PARTIALLY DECLINED (a part granted), DECLINED; DEFERRED is no decision. Two words in one row are two applications the text layer ran together: no status."""
    w = _clean(row.get("decision")).upper()
    if w in ("APPROVED", "PARTIALLY DECLINED", "PARTIALLY APPROVED", "APPROVED-PARTIAL", "FULLY APPROVED",
             "CONDITIONALLY APPROVED"):
        return "Accepted"
    return "Declined" if w in ("DECLINED", "DECLINE") else ""


def status_by_code(row: dict, layout: dict) -> str:
    """Air Rescue and Pelorus print a decision code: [A1] or [A2] approved in full or in part, [Dn] declined."""
    codes = re.findall(r"\[([AD])\d\]", row.get("reason", ""))
    if codes:
        return "Accepted" if codes[0] == "A" else "Declined"
    return layout.get("default_status") or ""


PELORUS_STOP = [r"^Reasons for (?:Partial )?Decline\b"]
PELORUS_SKIP = [r"^Pelorus Trust$", r"^\w+day, \d{1,2} \w+ \d{4}$", r"^Pelorus Trust \|", r"^Powered by\b",
                r"^\d+ of \d+$"]
LAYOUTS = {
    "society-air-rescue-decisions-pdf": {
        "society": "air-rescue-services",
        "title": [r"^Air Rescue Services Limited$", r"^All Applications$"],
        "period": r"^(?P<a>" + _DAY + r")\s+(?:to|-)\s+(?P<b>" + _DAY + r")$",
        "heads": {"recipient": "Organisation Name", "requested": ["Amount Requested", "Requested"],
                  "granted": "Amount Approved", "decision": "Declined/Partially", "reason": "Reason", "tla": "Org TLA", "interest": "Interest"},
        "anchor": "requested", "align": "bottom", "status": status_by_word, "purpose": None,
    },
    "society-air-rescue-applications-pdf": {
        "society": "air-rescue-services",
        "title": [r"^Air Rescue Services Limited$", r"^All Applications$"],
        "period": r"^(?P<a>" + _DAY + r")\s+(?:to|-)\s+(?P<b>" + _DAY + r")$",
        "heads": {"recipient": "Organisation Name", "requested": "Requested", "granted": "Amount Approved",
                  "reason": "Reason", "tla": "Org TLA", "interest": "Interest"},
        "heads_also": [{"recipient": "Organisation Name", "requested": "Requested", "granted": "Amount Approved",
                        "reason": "Reason", "tla": "Org TLA", "date": "Meeting Date", "interest": "Interest"}],
        "absent": ["Declined/Partially"],
        "anchor": "requested", "align": "bottom", "status": status_by_code, "purpose": None,
    },
    "society-agt-quarter-distributions-pdf": {
        "society": "aotearoa-gaming-trust",
        "title": [r"^Aotearoa Gaming Trust Grants (?P<q>[1-4]) ?(?:st|nd|rd|th) Quarter (?P<y>20\d\d)$"],
        "heads": {}, "edges": {"recipient": 0.0, "granted": 465.0},
        "skip": [r"^Aotearoa Gaming Trust Grants \d", r"^The Aotearoa Gaming Trust acknowledges", r"^raising of these funds"],
        "anchor": "granted", "align": "bottom", "status": lambda row, layout: "Accepted", "purpose": None,
    },
    "society-pelorus-approved-pdf": {
        "society": "pelorus-trust",
        "title": [r"^Pelorus Trust Grant Results$", r"^(?P<d>" + _DAY + r") - Approved Results$"],
        "heads": {"app": "App #", "recipient": "Organisation Name", "category": "Category", "requested": "Requested",
                  "granted": "Approved", "reason": ["Reason for", "Reason"], "interest": "NPC"},
        "skip": PELORUS_SKIP, "stop": PELORUS_STOP,
        "anchor": "requested", "align": "top", "status": status_by_code, "purpose": None,
        "totals": True, "total_is": ["granted"],
    },
    "society-pelorus-declined-pdf": {
        "society": "pelorus-trust",
        "title": [r"^Pelorus Trust Grant Results$", r"^(?P<d>" + _DAY + r") - Declined Applications$"],
        "heads": {"app": "App #", "recipient": "Organisation Name", "category": "Category", "requested": "Declined",
                  "reason": ["Reason for", "Reason"], "interest": "NPC"},
        "skip": PELORUS_SKIP, "stop": PELORUS_STOP,
        "anchor": "requested", "align": "top", "status": lambda row, layout: "Declined", "purpose": None,
        "totals": True, "total_is": ["requested"],
    },
    "society-milestone-recipients-pdf": {
        "society": "milestone-foundation",
        "title": [r"^Milestone Foundation Recipients$", r"^(?P<m>[A-Za-z]{3,9}) (?P<y4>20\d\d)\b"],
        "heads": {"recipient": "Organisation Name", "app": "Grant No", "category": "Category",
                  "requested": "Requested", "compliant": "Compliant", "granted": ["Approved", "ApprovedAmount"],
                  "decision": "Decision", "reason": "Reason for full/part decline",
                  "interest": ["Relationship", "Conflict of Interest", "Conflict", "Con"]},
        "heads_also": [
            {"recipient": "Organisation Name", "tla": "TLA", "app": "Grant No", "category": "Category",
             "requested": "Requested", "compliant": "Compliant", "granted": ["Approved", "ApprovedAmount"],
             "decision": "Decision", "reason": "Reason for full/part decline",
             "interest": ["Relationship", "Conflict of Interest", "Conflict", "Con"]},
            {"recipient": "Organisation Name", "tla": "TLA", "app": "Grant No", "category": "Category",
             "requested": "Requested", "compliant": "Compliant", "granted": ["Approved", "ApprovedAmount"],
             "decision": "Decision", "reason": "Reason for full/part decline"},
            {"recipient": "Organisation Name", "app": "Grant No", "category": "Category",
             "requested": "Requested", "compliant": "Compliant", "granted": ["Approved", "ApprovedAmount"],
             "decision": "Decision", "reason": "Reason for full/part decline"}],
        "anchor": "requested", "align": "middle", "purpose": None, "total_lines": "word", "totals": True,
        "status": status_by_word,
    },
    "society-we-care-quarter-approved-pdf": {
        "society": "we-care-community-trust",
        "title": [r"^Grants Approved for the period (?P<a>" + _DAY + r") - (?P<b>" + _DAY + r")$"],
        "heads": {"recipient": "Organisation", "category": "Category", "requested": "Requested",
                  "granted": "Approved", "declined": "Declined", "reason": "Reason"},
        "stop": [r"^Less Refunds received\b"],
        "anchor": "requested", "align": "bottom", "purpose": None, "totals": True, "total_is": ["requested",
                                                                                                "granted", "declined"],
        "status": lambda row, layout: "Accepted" if money(row.get("granted")) else "Declined",
    },
    "society-new-horizon-approved-pdf": {
        "society": "new-horizon-community-trust",
        "title": [r"^NEW HORIZON COMMUNITY TRUST$"],
        "period": r"^GRANTS APPROVED (?P<a>" + _DAY + r") - (?P<b>" + _DAY + r")$",
        "heads": {"sno": "S.No:", "app": "Grant No:", "recipient": "Organisation Name", "granted": "Amount Paid",
                  "paid": "Date Paid", "reason": "Reason", "interest": "Interests"},
        "skip": [r"^Grants Approved \d", r"^Accepted Accepted$", r"^in Full in Part$"],
        "anchor": "sno", "anchor_kind": "number", "align": "middle", "edge_mode": ["paid", "reason"], "purpose": None,
        "totals": True, "total_is": ["granted"], "total_lines": "word",
        "status": lambda row, layout: "Accepted",
    },
    "society-new-horizon-unsuccessful-pdf": {
        "society": "new-horizon-community-trust",
        "title": [r"^NEW HORIZON COMMUNITY TRUST$"],
        "period": r"^UNSUCCESSFUL GRANT APPLICATIONS (?P<a>" + _DAY + r") - (?P<b>" + _DAY + r")$",
        "heads": {"sno": "S.No:", "recipient": "ORGANISATION NAME", "app": "GRANT No.", "reason": "Decline Reason"},
        "anchor": "sno", "anchor_kind": "number", "align": "middle", "edge_mode": "gap", "purpose": None,
        "status": lambda row, layout: "Declined",
    },
    "society-trust-aoraki-meeting-outcome-pdf": {
        "society": "trust-aoraki",
        "title": [r"^Trust Aoraki Limited\b", r"^Grant Meeting Outcome - (?P<d>" + _DAY + r")\b"],
        "heads": {"app": "App Reference", "recipient": "Applicant Name", "category": "Category", "tla": "Originating",
                  "funding_tla": "Funding", "decision": "Status", "requested": "Requested", "compliant": "Compliant",
                  "declined": "Declined", "granted": "Approved", "reason": "Outcome", "interest": "NPC"},
        "skip": [r"^Trust Aoraki Limited \w+day, ", r"^Trust Aoraki Limited \|", r"^Powered by\b", r"^\d+ of \d+$",
                 r"^\d{3}(?:\.\d+)? - [A-Z][\w ,()'-]*$", r"^TLA TLA Conflicts$", r"^\d+ application\(s\)"],
        "stop": [r"^Reasons for partial or\b"],
        "summary": {"count_all": r"^Applications (\d+)\b", "count_accepted": r"^Approved (\d+)\b",
                    "count_declined": r"^Declined (\d+)\b", "total_requested": r"Total Requested (\$[\d,.]+)",
                    "total_granted": r"Total Approved (\$[\d,.]+)"},
        "anchor": "requested", "align": "top", "purpose": None,
        "status": lambda row, layout: {"FUNDED": "Accepted", "DECLINED": "Declined"}.get(
            _clean(row.get("decision")).upper().split(" ")[0], ""),
    },
    "society-trust-aoraki-successful-applications-pdf": {
        "society": "trust-aoraki",
        "title": [r"^Trust Aoraki Successful Applications (?P<m>[A-Za-z]{3,9}) (?P<yy>\d{2})$"],
        "heads": {"app": "Fund Ref", "recipient": "Org Trading Name", "tla": "App Benefiting TLA",
                  "purpose": "App Purpose", "requested": "App Requested Amount", "granted": "App Approved Amount"},
        "sections": [r"^Trust Aoraki (?:Successful|Declined) Applications \w+ \d{2}$"],
        "anchor": "requested", "align": "middle", "purpose": "purpose", "totals": True,
        "total_is": ["requested", "granted"], "total_not_section": "Declined",
        "status": lambda row, layout: "Accepted" if money(row.get("granted")) else "Declined",
    },
}
QUARTER = {"1": ("01-01", "03-31"), "2": ("04-01", "06-30"), "3": ("07-01", "09-30"), "4": ("10-01", "12-31")}
TITLE_LINES = 14       # the title, the period and the key stand in a page's first lines


def _title_match(lines: list, layout: dict):
    """{group: text} from the layout's title patterns, each matched by some line among the first, or None."""
    got = {}
    texts = [re.sub(r"\s+", " ", ln.text).strip() for ln in lines[:TITLE_LINES]]
    for pat in layout["title"]:
        m = next((m for m in (re.search(pat, t, re.I) for t in texts) if m), None)
        if m is None:
            return None
        got.update({k: v for k, v in m.groupdict().items() if v})
    if layout.get("period"):
        m = next((m for m in (re.search(layout["period"], t, re.I) for t in texts) if m), None)
        if m is None:
            return None
        got.update(a=m.group("a"), b=m.group("b"))
    return got


def _heads(layout: dict) -> list:
    return [layout["heads"]] + layout.get("heads_also", [])


def _head(lines: list, heads: dict, layout: dict):
    """The layout's head line, unless it carries a head the layout says it has not (the rule says what it is NOT)."""
    found = pdftable.find_head(lines, heads, layout.get("edge_mode", "left"))
    if found is None:
        return None
    i = found[0]
    near = " ".join(ln.text for ln in lines[max(0, i - 1):i + 1]).lower()
    if any(a.lower() in near for a in layout.get("absent", [])):
        return None
    return found


def recognise(data: bytes, ws: list = None):
    """A PDF with a text layer whose first page carries a layout's title lines and its row of column heads."""
    if not data.startswith(b"%PDF"):
        return None
    ws = pdftable.words(data) if ws is None else ws
    first = pdftable.pages_of([w for w in ws if w.page == min((w.page for w in ws), default=1)])
    lines = next(iter(first.values()), [])
    for slug, layout in LAYOUTS.items():
        if _title_match(lines, layout) is None:
            continue
        if layout.get("edges") or any(_head(lines, h, layout) is not None for h in _heads(layout)):
            return slug
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def read_file(data: bytes, sha: str, slug: str) -> read.Reading:
    layout = LAYOUTS[slug]
    p = read.profile(slug)
    out = read.Reading(slug, int(p["version"]))
    ws = pdftable.words(data)
    first_lines = next(iter(pdftable.pages_of([w for w in ws if w.page == 1]).values()), [])
    title = _title_match(first_lines, layout) or {}
    heads = layout["heads"] if layout.get("edges") else next(
        h for h in _heads(layout) if _head(first_lines, h, layout) is not None)
    t = pdftable.table(data, heads, layout["anchor"], layout["align"], ws=ws, edges=layout.get("edges"),
                       skip=layout.get("skip", ()), stop=layout.get("stop", ()), sections=layout.get("sections", ()),
                       anchor_kind=layout.get("anchor_kind", "money"), mode=layout.get("edge_mode", "left"),
                       total_lines=layout.get("total_lines", "figures"))
    decided = a_day(title["d"]) if title.get("d") else None
    start, end = (a_day(title.get("a")), a_day(title.get("b"))) if title.get("a") else (decided, decided)
    if title.get("m") and title["m"][:3].lower() in MONTHS:
        y, m = int(title["y4"]) if title.get("y4") else 2000 + int(title["yy"]), MONTHS[title["m"][:3].lower()]
        start = dt.date(y, m, 1)
        end = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    if title.get("q"):
        a, b = QUARTER[title["q"]]
        start, end = dt.date.fromisoformat(f"{title['y']}-{a}"), dt.date.fromisoformat(f"{title['y']}-{b}")
    if start is None or end is None:
        raise ValueError(f"{slug}: the title gives no period or decision date")
    period = decided.isoformat() if decided else f"{start.isoformat()}/{end.isoformat()}"
    out.stated = {"title": " / ".join(_clean(ln.text) for ln in first_lines[:4]), "period": period,
                  "pages": t.pages, "pages_with_head": t.pages_with_head, "other_lines": len(t.other)}
    for _, figures in t.totals:                            # the list's own total, printed as a line of figures
        if layout.get("total_is") and len(figures) == len(layout["total_is"]):
            out.stated.update({f"total_{col}": f for col, f in zip(layout["total_is"], figures)})
            out.notes["the list's own total line"] += 1
    for key, pat in layout.get("summary", {}).items():     # a file of several meetings prints one summary each
        found = [m.group(1) for m in (re.search(pat, _clean(text)) for _, text in t.other) if m]
        if found:
            out.stated[key] = (str(sum(int(x) for x in found)) if key.startswith("count_")
                               else f"${sum(money(x) for x in found):,.2f}")
    if t.text_pages < t.pages:
        out.notes["pages with no text layer (a scan): their rows are not read"] += t.pages - t.text_pages
    out.records = len(t.rows)
    if end.year < read.WINDOW_FROM:
        for i, _ in enumerate(t.rows, 1):
            out.set_aside.append({"document": sha, "place": f"row {i}", "stage": "window",
                                  "reason": f"a list for {period}, before {read.WINDOW_FROM} (ruling 71)"})
        read._reconcile(out)
        return out
    grantor = read.SOCIETIES[layout["society"]][0]
    measured = []                  # every row's printed figures, decided or not: what a printed total covers
    for i, row in enumerate(t.rows, 1):
        place = f"page {row['page']}, row {i}"
        if not (layout.get("totals") and not _clean(row.get("recipient"))):
            measured.append((row.get("requested"), row.get("granted"), row.get("section")))
        if layout.get("totals") and not _clean(row.get("recipient")):
            for col in ("requested", "granted"):
                if row["anchor_cells"].get(col):
                    out.stated["total_" + col] = row["anchor_cells"][col]
            out.notes["the list's own total line"] += 1
            out.records -= 1
            continue
        name = _clean(row.get("recipient"))
        if not name:
            out.set_aside.append({"document": sha, "place": place, "stage": "read", "reason": "no recipient named"})
            continue
        if name.endswith(("...", "…")):
            out.notes["a name the publisher cut short, kept as printed"] += 1
        status = layout["status"](row, layout)
        if status not in ("Accepted", "Declined"):
            out.set_aside.append({"document": sha, "place": place, "stage": "read",
                                  "reason": "no decision code the layout knows"})
            continue
        requested = _clean(row.get("requested"))
        granted = _clean(row.get("granted"))
        g = money(granted)
        if status == "Accepted" and not g:
            out.notes["approved by its code with no amount approved"] += 1
        out.grants.append({
            "key": f"grants/{layout['society']}/{sha[:16]}/{i}",
            "publisher_key": layout["society"], "grantor_key": layout["society"], "grantor_as_published": grantor,
            "committee": None,
            "recipient_as_published": name, "recipient_final_as_published": None,
            "recipient_kind": read.recipient_kind(name, None, None),
            "nzbn_as_published": None, "nzbn": None, "charity_number_as_published": None, "charity_number": None,
            "status": status,
            "amount_requested_as_published": requested or None, "amount_granted_as_published": granted or None,
            "amount_nzd": g if status == "Accepted" and g else None,
            "multi_year": None,
            "purpose_as_published": _clean(row.get(layout["purpose"])) or None if layout["purpose"] else None,
            "category_1": _clean(row.get("category")) or None, "category_2": None,
            "decided_on": decided or a_day(_clean(row.get("date"))),
            "decided_on_as_published": title.get("d") or _clean(row.get("date")) or None,
            "period": period, "round": None,
            "is_refund": None, "refunded_on": None, "refunded_on_as_published": None,
            "amount_refunded_as_published": None, "benefits": None,
            "territorial_authority": _clean(row.get("tla")) or None,
            "other_territorial_authority": None, "region": None,
            "application_as_published": _clean(row.get("app")) or None,
            "reason_as_published": _clean(row.get("reason")) or None,
            "interest_as_published": _clean(row.get("interest")) or None,
            "document": sha, "page": row["page"], "place": place, "read_from": "text", "reader": READER,
            "profile": slug, "profile_version": out.version,
        })
    counted = [m for m in measured if layout["total_not_section"] not in (m[2] or "")] \
        if layout.get("total_not_section") else measured
    for k, col in enumerate(("requested", "granted")):
        out.stated[f"rows_{col}"] = round(sum(money(m[k]) or 0 for m in counted), 2)
    read._reconcile(out)
    return out
