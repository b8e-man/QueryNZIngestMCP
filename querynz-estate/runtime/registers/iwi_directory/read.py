"""The reading of Te Kāhui Māngai's pages: pure, no network, no model.

Every page the walk lands is recognised by its shape, never by its address
alone (profiles in `profiles-proposed.jsonl`):

  iwi        an iwi page (`/iwi/<slug>/`): `<h1>` the iwi, `div#iwiHapu` with
             one `table.haputable` per rohe section (Hapū | Marae | Wharenui |
             Location, or no Hapū column), `div#iwiOrganisations` with an `<h2>`
             per kind of organisation and an `<h3>` per organisation
  region     a region map page: `dd.legend` links to iwi pages
  authority  a local or regional authority page: `dl#IwiList` "Iwi found:"
  omo        "Other Māori Organisations": `<h2>` sections, `<h3>` organisations
  nontribal  "Non-Tribal Marae": `<h2>` sections, `table.haputable` without Hapū
  site       any other page of the site: landed, not read

An organisation's entry names people (chair, chief executive, RMA contact)
with their phone, mobile and email, and the organisation's postal and
physical address. Only the labels in `KEEP` are read onto a row; every
other label is counted by its name, and its value, a contact paragraph and
a kept label holding a contact are kept whole in the entry's `private`, for
`iwi_directory_private.entry_fields` only (ruling 142, 4 November 2026;
hard limit 15 binds the surfaces). A
marae's location is the marae's own, kept as printed.
"""
import html
import re
import unicodedata

READER = "registers.iwi_directory.read"
READER_VERSION = 1
PROFILES = {"iwi": "tkm-iwi-page", "region": "tkm-region-page", "authority": "tkm-authority-page",
            "omo": "tkm-other-organisations-page", "nontribal": "tkm-non-tribal-marae-page"}
PROFILE_VERSION = 1
SOURCE = "Te Kāhui Māngai, Te Puni Kōkiri (www.tkm.govt.nz), CC BY 3.0 NZ as catalogued on data.govt.nz"

#: the only labels whose values are read; the key is the label folded, the value the column
KEEP = {"legal entity": "legal_entity", "governance structure": "governance_structure",
        "hapu represented": "hapu_represented", "area of interest": "area_of_interest",
        "local authorities": "local_authorities", "website": "website",
        "primary purpose/kaupapa": "primary_purpose"}

#: role flags by the picture's file name (its first word, or first word and qualifier: `rma_sm_hapu` is
#: `rma_hapu`), each as the site's glossary defines it; the alt text is kept as printed beside it
FLAG_BY_IMAGE = {"posttreaty": "post-settlement governance entity", "mfa": "Māori Fisheries Act 2004",
                 "iao": "iwi aquaculture organisation", "rma": "RMA iwi authority",
                 "rma_hapu": "RMA group representing hapū of the iwi", "rma_other": "RMA other iwi authority",
                 "tuhono": "Tūhono organisation", "treaty": "mandate for settlement negotiations",
                 "tree": "collective settlement governance entity",
                 "maunga": "member of Ngā Iwi o Taranaki (Taranaki Maunga collective redress)"}
#: a picture that stands for a contact (phone, email, address) is never a flag; its paragraph is kept privately
CONTACT_IMAGE = re.compile(r"phone|mobile|fax|mail|envelope|address|postal|contact|location", re.I)
#: an email address or a phone number, wherever the site prints one: a kept label holding one is not kept (a
#: website entry that is three email addresses behind `http://`, 23 October 2026)
CONTACT_VALUE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?:\+64|\b0)\d{1,2}[ -]?\d{3}[ -]?\d{3,4}\b")
#: a cell the site fills where it names nothing: blank, not a hapū or a marae
PLACEHOLDER = re.compile(r"^(?:not yet identified|unknown|-+)$", re.I)
PSGE = re.compile(r"^post[- ](?:treaty )?settlement governance entity", re.I)
MANDATE = re.compile(r"^mandate recognised by the crown", re.I)
ACT = re.compile(r"^(.*?\bAct\s+(\d{4}))\b")
DEED = re.compile(r"Deed of Settlement signed with the Crown on (\d{1,2} \w+ \d{4})", re.I)
AIP = re.compile(r"Agreement in Principle signed with the Crown on (\d{1,2} \w+ \d{4})", re.I)
CHARITY = re.compile(r"\bCC\d{5,6}\b")
NZBN = re.compile(r"\b94\d{11}\b")


class NotTheShape(ValueError):
    """The page is not the shape its profile describes: set aside whole."""


# ── small pieces ─────────────────────────────────────────────────────────────

def text(s: str) -> str:
    """Visible text of a fragment: tags out, entities decoded, white space folded."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fold(s: str) -> str:
    """A key part: lower case, macrons off, anything else not a letter or digit a dash. Double vowels stay."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def printed(s: str) -> str:
    """A name as printed, for telling two bodies apart: macrons kept (Hāua is not Hauā), case and spacing not."""
    return re.sub(r"[\W_]+", "-", unicodedata.normalize("NFC", s or "").lower()).strip("-")


def flag_kind(stem: str) -> str:
    """A role flag's rule by its picture's file stem; one no rule names is 'other: <first word>' for the check."""
    parts = re.split(r"[_.-]", stem.lower())
    for q in parts[1:]:
        if f"{parts[0]}_{q}" in FLAG_BY_IMAGE:
            return FLAG_BY_IMAGE[f"{parts[0]}_{q}"]
    return FLAG_BY_IMAGE.get(parts[0], "other: " + parts[0])


def contact_image(stem: str) -> bool:
    """A contact icon: its file name says phone, email or address, and no rule names it a flag."""
    return flag_kind(stem).startswith("other: ") and bool(CONTACT_IMAGE.search(stem))


def label_key(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s).replace("-", " ").replace(" kaupapa", "/kaupapa")).strip()


def _between(page: str, start: str, ends=("id=\"clearFooterHome\"", "id=\"footer\"")) -> str:
    i = page.find(start)
    if i < 0:
        return ""
    j = min([k for k in (page.find(e, i) for e in ends) if k > 0] or [len(page)])
    return page[i:j]


def h1_of(page: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", _between(page, 'id="introBox"') or page, re.S)
    return text(m.group(1)) if m else ""


def slug_of(url: str) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


# ── recognition ──────────────────────────────────────────────────────────────

def recognise(body: bytes) -> str:
    """The page's kind by its shape: 'iwi', 'region', 'authority', 'omo', 'nontribal' or 'site'."""
    page = body.decode("utf-8", "replace")
    if "<title>TKM |" not in page and "Te Kahui Mangai" not in page:
        raise NotTheShape("not a Te Kāhui Māngai page (no TKM title)")
    if 'id="iwiHapu"' in page and 'id="iwiOrganisations"' in page and h1_of(page):
        return "iwi"
    if re.search(r"<dd class='legend'><a href='/iwi/", page):
        return "region"
    if 'id="IwiList"' in page:
        return "authority"
    h1 = h1_of(page)
    if h1 == "Other Māori Organisations" and re.search(r"<h3[ >]", page):
        return "omo"
    if h1.startswith("Non-Tribal Marae") and 'class="haputable"' in page:
        return "nontribal"
    return "site"


# ── the parts of a page ──────────────────────────────────────────────────────

def tables(section: str) -> list:
    """[(rohe heading or '', [column], [[cell]])] for each table.haputable, in order; a blank first cell is the
    row above's (the page prints a hapū once for its several marae). A row of one cell under several heads is a
    note, dropped; under one head (a list of hapū alone) it is the row."""
    out, heading = [], ""
    for m in re.finditer(r"<h4[^>]*>(.*?)</h4>|<h2[^>]*>(.*?)</h2>|<table class=\"haputable\">(.*?)</table>",
                         section, re.S):
        if m.group(1) is not None:
            heading = text(m.group(1))
            continue
        if m.group(2) is not None:
            heading = text(m.group(2))
            continue
        body = m.group(3)
        cols = [text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)]
        if not cols:
            raise NotTheShape(f"a hapū table under {heading!r} has no column heads")
        rows, above = [], None
        for tr in re.findall(r"<tr class=\"(?:odd|even)\"[^>]*>(.*?)</tr>", body, re.S):
            cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) <= 1 and len(cols) > 1 or not any(cells):
                continue
            if len(cells) != len(cols):
                raise NotTheShape(f"a row of {len(cells)} cells under {len(cols)} heads ({heading!r})")
            if above is not None and not cells[0] and cols[0] == "Hapū":
                cells[0] = above[0]
            rows.append(cells)
            above = cells
        out.append((heading, cols, rows))
    return out


def organisations(section: str) -> list:
    """[{name, listed_as, last_updated, flags: [(kind, alt, bracket)], fields: {column: value}, unread: [label]}]
    in page order. `listed_as` is the `<h2>` above the entry."""
    out, listed_as = [], ""
    section = re.sub(r"(?is)<noscript>.*?</noscript>", "", section)
    marks = list(re.finditer(r"<h2[^>]*>(.*?)</h2>|<h3[^>]*>(.*?)</h3>", section, re.S))
    for i, m in enumerate(marks):
        if m.group(1) is not None:
            listed_as = text(m.group(1))
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(section)
        block = section[m.end():end]
        entry = {"name": text(m.group(2)), "listed_as": listed_as, "last_updated": None, "flags": [],
                 "fields": {}, "unread": [], "private": []}
        lu = re.search(r"Last updated:\s*([0-9/]+)", block)
        if lu:
            entry["last_updated"] = lu.group(1)
        for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S):
            img = re.search(r"<img[^>]*src=\"/images/([A-Za-z0-9_-]+)[^\"]*\"[^>]*alt=\"([^\"]*)\"[^>]*>", p)
            if img and contact_image(img.group(1)):
                if text(p):
                    entry["private"].append((img.group(1), text(p)))
                continue
            if img:
                after = text(p[img.end():])
                br = re.search(r"\[\s*(.*?)\s*\]", after)
                alt = img.group(2).strip() or re.sub(r"\s*\[.*?\]\s*", " ", after).strip()[:300]
                entry["flags"].append((flag_kind(img.group(1)), alt,
                                       br.group(1) if br else None))
                continue
            for lab, val in re.findall(r"<b>\s*([^<]+?)\s*</b>(.*?)(?=<b>|$)", p, re.S):
                key = label_key(lab.rstrip(":"))
                col = KEEP.get(key)
                if col is None:
                    entry["unread"].append(lab.rstrip(":").strip())
                    if text(val.lstrip(":")):
                        entry["private"].append((lab.rstrip(":").strip(), text(val.lstrip(":"))))
                    continue
                if col == "website":
                    href = re.search(r"href=\"(https?://[^\"]+)\"", val)
                    entry["fields"][col] = href.group(1) if href else text(val)
                else:
                    entry["fields"][col] = text(val.lstrip(":")) or None
                if CONTACT_VALUE.search(entry["fields"][col] or ""):
                    entry["private"].append((lab.rstrip(":").strip(), entry["fields"][col]))
                    entry["fields"][col] = None
                    entry["unread"].append(lab.rstrip(":").strip() + " (a contact printed in it)")
        out.append(entry)
    return out


def settlement_of(flag) -> dict:
    """A settlement as a post-settlement governance entity's flag names it, or a mandate's stage."""
    kind, alt, bracket = flag
    if PSGE.match(alt):
        if bracket:
            act = ACT.match(bracket)
            if act:
                return {"name": act.group(1), "act": act.group(1), "act_year": int(act.group(2)),
                        "stage": "settled: Act", "signed_on": None, "as_printed": bracket}
            deed = DEED.search(bracket)
            return {"name": bracket, "act": None, "act_year": None,
                    "stage": "settled: deed signed" if deed else "settled: as printed",
                    "signed_on": deed.group(1) if deed else None, "as_printed": bracket}
        m = re.search(r"in the (.+?)\.?$", alt)
        if not m:
            # the flag's own words and nothing beside them ("Post-Treaty settlement governance entity."): the entry
            # says what the body is and names no settlement
            return {"name": None, "act": None, "act_year": None, "stage": "settled: none named", "signed_on": None,
                    "as_printed": alt}
        return {"name": m.group(1), "act": None, "act_year": None, "stage": "collective settlement",
                "signed_on": None, "as_printed": alt}
    if MANDATE.match(alt):
        aip = AIP.search(bracket or "")
        return {"name": None, "act": None, "act_year": None, "stage": "mandate recognised",
                "signed_on": aip.group(1) if aip else None, "as_printed": bracket or alt}
    return None


def settlement_row_key(entity_key: str, settlement_key) -> str:
    """A settlement row's own key: the entity's with the settlement's, so a key names one row; a settlement met
    under several bodies (a collective, a shared Act) keeps its own key in `settlement_key`."""
    return f"{entity_key}|{settlement_key or 'no settlement named'}"


# ── one page → rows ──────────────────────────────────────────────────────────

def _cite(sha, url, place, kind):
    return {"document": sha, "page": 1, "place": place, "read_from": "text", "reader": f"{READER} v{READER_VERSION}",
            "profile": PROFILES[kind], "profile_version": PROFILE_VERSION, "url": url}


def _entity(key, kind, name, cite, **kw):
    row = {"key": key, "kind": kind, "name": name, "iwi_key": None, "listed_as": None, "region": None,
           "legal_entity": None, "governance_structure": None, "hapu_represented": None, "area_of_interest": None,
           "local_authorities": None, "primary_purpose": None, "website": None, "wharenui": None, "location": None,
           "flags": [], "charity_number": None, "nzbn": None, "last_updated": None}
    row.update(kw)
    row.update(cite)
    return row


def _org_rows(entries, sha, url, kind, iwi_key=None):
    ents, rels, sets = [], [], []
    for n, e in enumerate(entries, 1):
        key = "tkm/org/" + fold(e["name"])
        psge = any(PSGE.match(f[1]) for f in e["flags"])
        printed = " ".join(v for v in (e["name"], e["fields"].get("legal_entity")) if v)
        cc, bn = CHARITY.search(printed), NZBN.search(printed)
        cite = _cite(sha, url, f"organisations, entry {n}", kind)
        ents.append(_entity(key, "governance entity" if psge else "organisation", e["name"], cite,
                            listed_as=e["listed_as"] or None, flags=[f"{f[0]}: {f[1]}" + (f" [{f[2]}]" if f[2] else "")
                                                                    for f in e["flags"]],
                            charity_number=cc.group(0) if cc else None, nzbn=bn.group(0) if bn else None,
                            last_updated=e["last_updated"], _private=list(e["private"]), **e["fields"]))
        if iwi_key:
            rels.append({"from_key": key, "relation": "organisation of iwi", "to_key": iwi_key, "to_name": None,
                         "section": e["listed_as"] or None, **cite})
        for f in e["flags"]:
            s = settlement_of(f)
            if s is None:
                continue
            if s["stage"] == "mandate recognised":
                s_key = "tkm/mandate/" + fold(e["name"])
            elif s["stage"] == "settled: none named":
                s_key = None
            elif s["act"] or s["stage"] == "collective settlement":
                s_key = "tkm/settlement/" + fold(s["name"])
            else:
                s_key = "tkm/settlement/" + fold(e["name"]) + "/" + fold(s["signed_on"] or s["as_printed"])
            sets.append({"key": settlement_row_key(key, s_key), "settlement_key": s_key, "entity_key": key,
                         "iwi_key": iwi_key, **s, **cite})
    return ents, rels, sets


#: the hapū tables' heads as the site prints them: hapū with marae, marae alone, or a list of hapū alone (its
#: marae in a table of their own beside it, the iwi's); the wharenui column is left out on some pages
HAPU_HEADS = [h + m for h in (["Hapū"], []) for m in (["Marae", "Wharenui", "Location"], ["Marae", "Location"])] + [["Hapū"]]


def read_iwi(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    name = h1_of(page)
    if not name:
        raise NotTheShape("no iwi heading")
    iwi_key = "tkm/iwi/" + slug_of(url)
    intro = _between(page, 'id="introBox"', ("</div>",))
    region = re.search(r"href='/region/[^']+'>(.*?)</a>", intro)
    main = _between(page, 'id="iwiMain"', ('id="tabs"',))
    iwi_flags = [a.strip() for a in re.findall(r"<img[^>]*alt=\"([^\"]*)\"", main)]
    head = _cite(sha, url, "heading", "iwi")
    ents = [_entity(iwi_key, "iwi", name, head, region=text(region.group(1)) if region else None, flags=iwi_flags)]
    rels = []
    rohe = _between(page, 'id="iwiRohe"', ('id="iwiHapu"',))
    for dl in re.findall(r"<dl class=\"authority_tree\">(.*?)</dl>", rohe, re.S):
        dt = re.search(r"<dt>(.*?)</dt>", dl, re.S)
        for dd in re.findall(r"<dd>(.*?)</dd>", dl, re.S):
            rels.append({"from_key": iwi_key, "relation": "rohe in local authority", "to_key": None,
                         "to_name": text(dd), "section": text(dt.group(1)) if dt else None,
                         **_cite(sha, url, "rohe, local authorities", "iwi")})
    hapu_sec = _between(page, 'id="iwiHapu"', ('id="iwiOrganisations"',))
    if not hapu_sec:
        raise NotTheShape("no hapū and marae section")
    seen = {}
    for t, (heading, cols, rows) in enumerate(tables(hapu_sec), 1):
        if cols not in HAPU_HEADS:
            raise NotTheShape(f"hapū table {t} has heads {cols}")
        for r, cells in enumerate(rows, 1):
            cite = _cite(sha, url, f"hapū table {t}, row {r}", "iwi")
            row = {c: ("" if PLACEHOLDER.match(v) else v) for c, v in zip(cols, cells)}
            hapu, marae = row.get("Hapū", ""), row.get("Marae", "")
            wharenui, location = row.get("Wharenui", ""), row.get("Location", "")
            h_key = None
            if hapu:
                h_key = f"tkm/hapu/{slug_of(url)}/{fold(hapu)}"
                if h_key not in seen:
                    seen[h_key] = True
                    ents.append(_entity(h_key, "hapū", hapu, cite, iwi_key=iwi_key, listed_as=heading or None))
                    rels.append({"from_key": h_key, "relation": "hapū of iwi", "to_key": iwi_key, "to_name": None,
                                 "section": heading or None, **cite})
            if marae:
                m_key = f"tkm/marae/{fold(marae)}/{fold(location)}"
                if m_key not in seen:
                    seen[m_key] = True
                    ents.append(_entity(m_key, "marae", marae, cite, listed_as="tribal marae",
                                        wharenui=wharenui or None, location=location or None))
                to = (h_key, "marae of hapū") if h_key else (iwi_key, "marae of iwi")
                if (m_key, to) not in seen:
                    seen[(m_key, to)] = True
                    rels.append({"from_key": m_key, "relation": to[1], "to_key": to[0], "to_name": None,
                                 "section": heading or None, **cite})
    org_sec = _between(page, 'id="iwiOrganisations"')
    entries = organisations(org_sec)
    o_ents, o_rels, sets = _org_rows(entries, sha, url, "iwi", iwi_key)
    return {"kind": "iwi", "entities": ents + o_ents, "relations": rels + o_rels, "settlements": sets,
            "unread": sorted({l for e in entries for l in e["unread"]}), "iwi_links": []}


def read_region(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    region = h1_of(page)
    links = re.findall(r"<dd class='legend'><a href='(/iwi/[^']+/)'[^>]*>(?:<span[^>]*>.*?</span>)?(.*?)</a>", page, re.S)
    if not links:
        raise NotTheShape("a region page that links no iwi")
    rels = [{"from_key": "tkm/iwi/" + slug_of(href), "relation": "iwi in region", "to_key": None, "to_name": region,
             "section": text(label), **_cite(sha, url, f"legend, entry {n}", "region")}
            for n, (href, label) in enumerate(links, 1)]
    return {"kind": "region", "entities": [], "relations": rels, "settlements": [], "unread": [],
            "iwi_links": [slug_of(h) for h, _ in links]}


def read_authority(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    dl = re.search(r"<dl id=\"IwiList\">(.*?)</dl>", page, re.S)
    if not dl:
        raise NotTheShape("no iwi list")
    links = re.findall(r"href=\"(/iwi/[^\"]+/)\"", dl.group(1))
    return {"kind": "authority", "entities": [], "relations": [], "settlements": [], "unread": [],
            "iwi_links": [slug_of(h) for h in links], "authority": h1_of(page).replace("Browse by:", "").strip()}


def read_omo(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    sec = _between(page, 'id="middleNewsColumn"')
    entries = organisations(sec)
    if not entries:
        raise NotTheShape("no organisation on the other organisations page")
    ents, rels, sets = _org_rows(entries, sha, url, "omo")
    return {"kind": "omo", "entities": ents, "relations": rels, "settlements": sets,
            "unread": sorted({l for e in entries for l in e["unread"]}), "iwi_links": []}


def read_nontribal(body: bytes, sha: str, url: str) -> dict:
    page = body.decode("utf-8", "replace")
    ents, seen = [], set()
    for t, (heading, cols, rows) in enumerate(tables(_between(page, 'id="middleNewsColumn"')), 1):
        if cols != ["Marae", "Wharenui", "Location"]:
            raise NotTheShape(f"non-tribal table {t} has heads {cols}")
        for r, (marae, wharenui, location) in enumerate(rows, 1):
            key = f"tkm/marae/{fold(marae)}/{fold(location)}"
            if not marae or key in seen:
                continue
            seen.add(key)
            ents.append(_entity(key, "marae", marae, _cite(sha, url, f"table {t}, row {r}", "nontribal"),
                                listed_as=heading or "non-tribal marae", wharenui=wharenui or None,
                                location=location or None))
    if not ents:
        raise NotTheShape("no marae on the non-tribal marae page")
    return {"kind": "nontribal", "entities": ents, "relations": [], "settlements": [], "unread": [], "iwi_links": []}


READERS = {"iwi": read_iwi, "region": read_region, "authority": read_authority, "omo": read_omo,
           "nontribal": read_nontribal}


def read_page(body: bytes, sha: str, url: str) -> dict:
    """One landed page → {'kind', 'entities', 'relations', 'settlements', 'unread', 'iwi_links'}; a 'site' page
    gives no rows. Raises NotTheShape where the page claims a kind and is not its shape."""
    kind = recognise(body)
    if kind == "site":
        return {"kind": "site", "entities": [], "relations": [], "settlements": [], "unread": [], "iwi_links": []}
    return READERS[kind](body, sha, url)
