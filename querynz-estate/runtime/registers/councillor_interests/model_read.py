"""The text reader's reading of a council's register of members' pecuniary
interests held as a PDF (profile `interests-register-pdf-text` v1; Arthur,
2 November 2026: "we want to gather and ingest all of this"; ruling 128
lifted ruling 79's hold on model reading for node2 alone; ruling 130 (b):
a document over the budget is read in pieces by its rule, never excerpted).

The PDFs share no layout: a label column and an answer column (Kaipara), a
numbered questionnaire (Buller), one file per member (Christchurch,
Tauranga), a landscape table of every member (Manawatū-Whanganui). So no
deterministic grammar reads them all; the text layer (`pdftotext -layout`,
support.docread.pages) is taken by the lane and the text reader
(Flash-Next, profile `text-reader`, the standing server on this box, hard
limit 10) reads it through the model client, which names the model and
refuses an answer from any other. One reading per document hash, stamped
with the reader's version, the served model and the prompt's hash, stored
in the reader store and replayed by every load (ruling 50: the load calls
no model).

Everything the register prints is read and kept (ruling 142; ruling 143:
real-property declarations kept whole, a spouse's or partner's interests
read and kept). Each row carries its flags (read.flags): `real_property`
(typed real property, or a heading naming real property, land, a home, an
address or a contact), `of_partner` (a spouse's, partner's or family
member's), and `private_entries`, the count of entries shaped like a street
address, a road or highway, a rural delivery, a title, an email or a phone
number (`private_entry`), which are kept in `councillor_interests_private
.entries` by the row's key and the entry's ordinal. Prompt 2 (4 November
2026) asks for every entry as printed; a document whose prompt-2 reading is
not stored yet replays its prompt-1 reading (`PROMPT_1`, which left those
out) until the text reader reaches it.

Recognition (measured 2 November 2026 on the 370 held PDFs with a text
layer: 359 name pecuniary interests, an interests register or a
declaration of interest in their first two pages): a PDF whose text names
one of MARKERS anywhere. A PDF with no usable text layer waits for the page
reader and is counted, never read here. A PDF whose text names none of
them (Christchurch's lists of council appointments to outside bodies) is
not a register: set aside at read, named.

    python -m registers.councillor_interests.model_read --pieces            every register PDF waiting, one sha256 a line
    python -m registers.councillor_interests.model_read --piece SHA256      one piece of qv4-councillor-interests-read
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error

from support import modelclient
from support import profiles
from support import reader as rd
from support.docread import pages
from registers.councillor_interests import read

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profiles-proposed.jsonl")
READER = "registers.councillor_interests.model_read 1"
LANE = "councillor_interests"
PROFILE = "interests-register-pdf-text"
PAGE_PROFILE = "interests-register-html-text"     # a page that prints the register in a shape read.py does not read
TEXT_MODEL = os.environ.get("QV4_COUNCILLOR_INTERESTS_TEXT_MODEL") or "qwen4exp"   # profiles.toml [profiles.text-reader]
URL = os.environ.get("QV4_MODEL_URL") or "http://127.0.0.1:8060/v1/chat/completions"
#: the profile's reading rule: pieces of whole pages up to BUDGET_CHARS, a page over it cut at line ends. The budget is
#: the ANSWER's, not the request's: a register's answer is about as long as its text (measured 2 November 2026 on ten
#: councils' PDFs: 12,567 characters in, 12,046 out; 16,951 in, 14,672 out), and every answer over about 14,500
#: characters was cut at MAX_TOKENS and unusable (five of ten at a 34,000 budget). 12,000 keeps the answer under it
BUDGET_CHARS = 12000
SPLIT = "pages, then lines"
#: 2 November 2026: a page that prints a category line per member answers at twice its length (Rangitikei: 8,000
#: characters in, 16,168 out, cut at 4,096 tokens); 12,000 characters in (about 3,600 tokens) and 8,192 out stay under
#: the text-reader profile's 16,384-token request
MAX_TOKENS = 8192
ATTEMPTS = 2
WAIT_TEXT = "waiting: text reader"
WAIT_PAGES = "waiting: page reader"
NOT_A_REGISTER = "not a register: its text names no pecuniary interests, interests register or declaration of interest"
MARKERS = re.compile(r"pecuniar|pecuinar|register\s+of\s+(elected\s+)?(members[’'`]?\s*)?(pecuniary\s+(and\s+other\s+"
                     r"specified\s+)?)?interests?|interests?\s+register|declarations?\s+of\s+interests?|\b54\s*E\b", re.I)
#: the statutory kinds a category is typed by (Local Government Act 2002, s 54E)
KINDS = ("company", "other business", "employment", "trust", "organisation", "real property", "superannuation",
         "debt", "gift", "travel", "other")
ROAD = read.ROAD
#: prompt 1 (2 November 2026): left out real property's entries, addresses, contacts and a spouse's or partner's
#: interests; its stored readings are replayed for a document not yet read under prompt 2
PROMPT_1 = (
    "You read the text of one New Zealand council's register of its elected members' pecuniary interests (Local "
    "Government Act 2002, Part 4 subpart 3), or one member's return, or one piece of such a register. Answer with ONE "
    "JSON object and nothing else:\n"
    '{"as_at": "<the date the register says it is at or covers, as printed, or null>",\n'
    ' "members": [{"member": "<the member\'s name exactly as printed, without the title>", '
    '"role": "<Mayor, Deputy Mayor, Councillor, Chair, Deputy Chair, Community Board member, ... as printed, or null>", '
    '"interests": [{"category": "<the category heading as printed>", '
    '"kind": "company" | "other business" | "employment" | "trust" | "organisation" | "real property" | '
    '"superannuation" | "debt" | "gift" | "travel" | "other", '
    '"entries": ["<one entry as printed: a company, a trust, an employer, an organisation and the position held>"]}]}]}\n'
    "Rules. One member per person the register covers, in the order printed, each once. Under each member every category "
    "the register prints for them, with its entries as printed, one string per entry; a category answered nil, none, "
    "not applicable or a dash has an empty entries list. Type each category by what it covers: directorships and "
    "controlling interests in companies kind company; other business entities and partnerships kind other business; "
    "employers kind employment; trusts kind trust; organisations, governing bodies, boards, clubs and societies kind "
    "organisation; land, property, buildings or a home kind real property; retirement or superannuation schemes kind "
    "superannuation; debts owed to or by the member kind debt; gifts kind gift; travel paid by others kind travel; "
    "anything else kind other. For a category of kind real property give the heading and an EMPTY entries list: never "
    "copy a property, a location, a title or an address. Never copy a street address, a road, a rural delivery number, "
    "a postal address, an email address or a telephone number into any entry. Leave out every entry about a member's "
    "spouse, partner or family. Keep spelling and macrons as printed. Never add anything the text does not print. The "
    "introduction, the statute's wording and the instructions to members are not entries: read only what each member "
    "declared.")
#: prompt 2 (4 November 2026, ruling 142): every entry as printed
PROMPT = (
    "You read the text of one New Zealand council's register of its elected members' pecuniary interests (Local "
    "Government Act 2002, Part 4 subpart 3), or one member's return, or one piece of such a register. Answer with ONE "
    "JSON object and nothing else:\n"
    '{"as_at": "<the date the register says it is at or covers, as printed, or null>",\n'
    ' "members": [{"member": "<the member\'s name exactly as printed, without the title>", '
    '"role": "<Mayor, Deputy Mayor, Councillor, Chair, Deputy Chair, Community Board member, ... as printed, or null>", '
    '"interests": [{"category": "<the category heading as printed>", '
    '"kind": "company" | "other business" | "employment" | "trust" | "organisation" | "real property" | '
    '"superannuation" | "debt" | "gift" | "travel" | "other", '
    '"entries": ["<one entry as printed: a company, a trust, an employer, an organisation and the position held, a property>"]}]}]}\n'
    "Rules. One member per person the register covers, in the order printed, each once. Under each member every category "
    "the register prints for them, with its entries as printed, one string per entry; a category answered nil, none, "
    "not applicable or a dash has an empty entries list. Type each category by what it covers: directorships and "
    "controlling interests in companies kind company; other business entities and partnerships kind other business; "
    "employers kind employment; trusts kind trust; organisations, governing bodies, boards, clubs and societies kind "
    "organisation; land, property, buildings or a home kind real property; retirement or superannuation schemes kind "
    "superannuation; debts owed to or by the member kind debt; gifts kind gift; travel paid by others kind travel; "
    "anything else kind other. Copy every entry of every category as printed, real property included: a property, a "
    "location, a title, an address, a road, a rural delivery number, an email address or a telephone number is copied "
    "as printed. Include every entry about a member's spouse, partner or family, as printed. Keep spelling and macrons "
    "as printed. Never add anything the text does not print. The "
    "introduction, the statute's wording and the instructions to members are not entries: read only what each member "
    "declared.")
NUDGE = "Your answer held no JSON object. Answer again with the ONE JSON object described, and nothing else."
_JSON = re.compile(r"\{.*\}", re.S)


def profile_version(slug: str = PROFILE) -> int:
    """The ledger's version; until the integrator appends it, the lane's proposed line."""
    held = [p for p in (profiles.profile(slug), profiles.profile(slug, path=PROPOSED) if os.path.exists(PROPOSED) else None) if p]
    if not held:
        raise LookupError(f"no document profile {slug}")
    return max(int(p["version"]) for p in held)


def settings(prompt: str = None) -> dict:
    prompt = PROMPT if prompt is None else prompt
    return {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16], "budget_chars": BUDGET_CHARS, "split": SPLIT,
            "temperature": 0.0, "max_tokens": MAX_TOKENS, "thinking": False, "attempts": ATTEMPTS}


def key_for(sha256: str, piece: int, version: int, model: str = TEXT_MODEL, profile: str = PROFILE,
            prompt: str = None) -> str:
    return rd.reading_key(sha256, piece, model, settings(prompt), profile, version)


#: the reading a load replays where prompt 2's is not stored yet: prompt 1, keyed under profile version 1
EARLIER = ((PROMPT_1, 1),)


# ── recognition and the reading rule ───────────────────────────────────────────────────────────────────────────
#: an HTML page that prints the register itself, not a page that links it (measured 2 November 2026 on the held
#: landing pages: New Plymouth 85,373 characters and 7 mentions of pecuniary interests, Hauraki 16,847 and 65, Rangitikei
#: 20,786 and 14, Greater Wellington's statutory returns 7,849 and 20; a page that only links a register, 1 to 3)
PAGE_MIN_CHARS, PAGE_MIN_MARKERS = 2000, 5
PAGE_CHUNK = 8000
_BLOCK = re.compile(r"<(?:/p|br\s*/?|/tr|/li|/h[1-6]|/div|/table|/section|/td|/th)\b[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|nav|header|footer|noscript)\b.*?</\1>", re.S | re.I)


def page_text(body: bytes) -> str:
    """An HTML page's text with its blocks on their own lines (scripts, styles, navigation, header and footer out)."""
    import html as H
    page = body.decode("utf-8", "replace")
    page = _DROP.sub(" ", page)
    page = _BLOCK.sub("\n", page)
    text = H.unescape(re.sub(r"<[^>]+>", " ", page))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def page_texts(body: bytes, chunk: int = PAGE_CHUNK) -> dict:
    """The page's text in numbered parts of whole lines up to `chunk` characters (a page has no pages of its own)."""
    out, cur, size = {}, [], 0
    for line in page_text(body).splitlines():
        if cur and size + len(line) + 1 > chunk:
            out[len(out) + 1] = "\n".join(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out[len(out) + 1] = "\n".join(cur)
    return out


def recognise_page(body: bytes, url: str = None, host: str = None) -> tuple:
    """(state, texts, profile) for an HTML page: '' when it prints a register (PAGE_PROFILE), else why not. With its
    address, a page that links a register document is the register's landing page, not the register (Tauranga's and
    Hastings' name the register in every link)."""
    if body[:5].startswith(b"%PDF"):
        return "a PDF, not a page", {}, PAGE_PROFILE
    if url and host:
        from registers.councillor_interests import capture
        if any(k == "document" for _u, k in capture.register_links(body, url, host)):
            return "a landing page: it links register documents", {}, PAGE_PROFILE
    text = page_text(body)
    if len(text) < PAGE_MIN_CHARS or len(MARKERS.findall(text)) < PAGE_MIN_MARKERS:
        return "not a register page: it names the register too seldom to print it", {}, PAGE_PROFILE
    return "", page_texts(body), PAGE_PROFILE


def page_wanted(council: str, councils_with_documents: set) -> bool:
    """Whether a council's page is read by the text reader at all: only where the council has no register document
    held (else the page is a landing page that links them: Tauranga's and Christchurch's name the register in every
    link) and its terms do not bar automated access."""
    from registers.councillor_interests import capture
    return council not in councils_with_documents and council not in capture.TERMS_BAR


def prepare(data: bytes) -> tuple:
    """(state, texts, profile): a PDF by PROFILE, an HTML page by PAGE_PROFILE."""
    if data[:5].startswith(b"%PDF"):
        why, texts = recognise(data)
        return why, texts, PROFILE
    return recognise_page(data)


def recognise(data: bytes, texts: dict = None) -> tuple:
    """(state, texts): '' when the document is a register PDF this profile reads from its text, else why not:
    WAIT_PAGES for a PDF with no usable text layer, NOT_A_REGISTER, or 'not a PDF'."""
    if not data[:5].startswith(b"%PDF"):
        return "not a PDF", {}
    texts = texts if texts is not None else pages.text_pages(data)
    if pages.read_from(data, texts) == "pixels":
        return WAIT_PAGES, texts
    if not MARKERS.search("\n".join(texts[p] for p in sorted(texts))):
        return NOT_A_REGISTER, texts
    return "", texts


def pieces(texts: dict, budget: int = BUDGET_CHARS) -> tuple:
    """([(first page, last page, text)], pages too large, thin pages): whole pages packed in order up to the budget;
    a page over the budget is cut at line ends into parts of its own. A thin page (no text layer) is left out and
    named; a single line over the budget cannot be split by the rule and its page is named too large."""
    thin = set(pages.thin_pages(texts))
    out, too_big, cur, first = [], [], [], None
    size = 0
    for p in sorted(texts):
        if p in thin:
            continue
        t = texts[p].strip()
        if len(t) > budget:
            lines = t.splitlines()
            if any(len(line) > budget - 40 for line in lines):
                too_big.append(p)
                continue
            if cur:
                out.append((first, last, "\n\n".join(cur)))
                cur, size = [], 0
            part, n = [], 0
            for line in lines:
                if part and n + len(line) + 1 > budget - 40:
                    out.append((p, p, f"[page {p}, continued]\n" + "\n".join(part) if out and out[-1][0] == p
                                else f"[page {p}]\n" + "\n".join(part)))
                    part, n = [], 0
                part.append(line)
                n += len(line) + 1
            if part:
                out.append((p, p, f"[page {p}, continued]\n" + "\n".join(part)))
            continue
        if cur and size + len(t) + 20 > budget:
            out.append((first, last, "\n\n".join(cur)))
            cur, size = [], 0
        if not cur:
            first = p
        cur.append(f"[page {p}]\n{t}")
        size += len(t) + 20
        last = p
    if cur:
        out.append((first, last, "\n\n".join(cur)))
    return out, too_big, sorted(thin)


# ── the answer ─────────────────────────────────────────────────────────────────────────────────────────────────
def _clean(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "", "null") else None


def private_entry(e: str) -> bool:
    return read.private_entry(e)


def parse_answer(text: str):
    """The JSON object in the model's answer, checked and normalised, or None."""
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        body = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("members"), list):
        return None
    members = []
    for mem in body["members"]:
        if not isinstance(mem, dict) or not _clean(mem.get("member")):
            continue
        cats = []
        for c in mem.get("interests") or []:
            if not isinstance(c, dict) or not _clean(c.get("category")):
                continue
            kind = str(c.get("kind") or "other").strip().lower()
            kind = kind if kind in KINDS else "other"
            ents = [_clean(e) for e in (c.get("entries") or []) if isinstance(e, (str, int, float)) and _clean(e)]
            cats.append({"category": _clean(c["category"]), "kind": kind,
                         "entries": [e for e in ents if not read.NIL.match(e)]})
        members.append({"member": _clean(mem["member"]), "role": _clean(mem.get("role")), "interests": cats})
    return {"as_at": _clean(body.get("as_at")), "members": members}


def kept(members: list) -> tuple:
    """(rows, flagged): one row per member and category, every one kept with its flags (read.flags); each flag
    counted by heading."""
    from collections import Counter
    rows, flagged = [], Counter()
    for mi, mem in enumerate(members, 1):
        for ci, c in enumerate(mem["interests"], 1):
            row = read.flags({"member": mem["member"], "role": mem["role"], "category": c["category"], "kind": c["kind"],
                              "entries": list(c["entries"]), "member_no": mi, "category_no": ci}, private_entry)
            for f, why in read.FLAG_WHY.items():
                if row[f]:
                    flagged[(c["category"], why)] += row[f] if f == "private_entries" else 1
            rows.append(row)
    return rows, flagged


def ask(text: str, *, url: str, model: str, post=None, request: dict = None, timeout: float = 900.0) -> tuple:
    """(parsed or None, served model, attempts, the last answer's length)."""
    extra = {"temperature": 0.0, "max_tokens": MAX_TOKENS, "chat_template_kwargs": {"enable_thinking": False}}
    for k, v in (request or {}).items():
        if k not in ("temperature", "max_tokens"):
            extra.setdefault(k, v)
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}]
    served, parsed, n, chars = model, None, 0, 0
    for n in range(1, ATTEMPTS + 1):
        out = modelclient.chat(url, lane=LANE, model=model, messages=messages, extra=extra, timeout=timeout, post=post)
        answer = (out["choices"][0]["message"]["content"] or "").strip()
        served, chars = out.get("model") or model, len(answer)
        parsed = parse_answer(answer)
        if parsed is not None:
            break
        messages = messages + [{"role": "assistant", "content": answer[:2000]}, {"role": "user", "content": NUDGE}]
    return parsed, served, n, chars


def _store_parsed(parsed: dict) -> dict:
    """What the store keeps of an answer: the whole parsed answer (ruling 142)."""
    return {"as_at": parsed["as_at"], "members": parsed["members"]}


def read_document(sha256: str, data: bytes, *, version: int, url: str = None, model: str = None, store: rd.Store = None,
                  post=None, request: dict = None) -> dict:
    """Every piece of the document read once and stored (piece n stored as page n of the reading key); a stored piece
    is replayed. A piece with no usable answer after the attempts is stored as set aside. Returns the counts."""
    store = store or rd.Store()
    model = model or TEXT_MODEL
    why, texts, profile = prepare(data)
    version = _version(profile, version)
    if why:
        return {"state": why, "pieces": 0, "read": 0, "replayed": 0, "members": 0, "profile": profile}
    parts, too_big, thin = pieces(texts)
    out = {"state": "read", "pieces": len(parts), "read": 0, "replayed": 0, "members": 0, "too_big": too_big,
           "thin": thin, "unusable": 0, "profile": profile}
    for n, (first, last, text) in enumerate(parts, 1):
        key = key_for(sha256, n, version, model, profile)
        if store.has(key):
            got = store.get(key)
            out["replayed"] += 1
        else:
            now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            parsed, served, attempts, chars = ask(text, url=url or URL, model=model, post=post, request=request)
            checks = {"pages": [first, last], "attempts": attempts, "answer_chars": chars, "pieces": len(parts)}
            if parsed is None:
                got = rd.Reading(sha256, n, READER, served, settings(), profile, version, "text", "", rows=[],
                                 checks={**checks, "usable": False,
                                         "reason": f"no usable JSON object in the answer after {attempts} attempt(s)"},
                                 made_at=now)
            else:
                safe = _store_parsed(parsed)
                got = rd.Reading(sha256, n, READER, served, settings(), profile, version, "text",
                                 json.dumps(safe, ensure_ascii=False, sort_keys=True), rows=[],
                                 checks={**checks, "usable": True, "members": len(safe["members"])}, made_at=now)
            store.put(got)
            out["read"] += 1
        if not (got.checks or {}).get("usable", True) or not got.text:
            out["unusable"] += 1
        else:
            out["members"] += len(json.loads(got.text)["members"])
    return out


def replay(sha256: str, data: bytes, *, version: int = None, store: rd.Store = None, model: str = TEXT_MODEL) -> dict:
    """The load's side, never a call: {'state', 'as_at', 'rows', 'flagged', 'unread'} from the stored pieces.
    state: 'read', WAIT_TEXT (a piece not yet read), WAIT_PAGES, NOT_A_REGISTER, 'set aside: ...'."""
    from collections import Counter
    store = store or rd.Store()
    why, texts, profile = prepare(data)
    version = _version(profile, version)
    if why:
        return {"state": why, "as_at": None, "rows": [], "flagged": Counter(), "unread": [], "profile": profile,
                "version": version}
    parts, too_big, thin = pieces(texts)
    if not parts:
        return {"state": f"set aside: every page over the budget of {BUDGET_CHARS} characters ({too_big})",
                "as_at": None, "rows": [], "flagged": Counter(), "unread": too_big, "profile": profile,
                "version": version}
    members, as_at, unusable = [], None, []
    # one prompt for the whole document: prompt 2's reading where every piece is stored, else the earlier one's
    used = version
    keys = [key_for(sha256, n, version, model, profile) for n in range(1, len(parts) + 1)]
    if not all(store.has(k) for k in keys):
        for prompt, v in EARLIER:
            old = [key_for(sha256, n, v, model, profile, prompt) for n in range(1, len(parts) + 1)]
            if all(store.has(k) for k in old):
                keys, used = old, v
                break
        else:
            return {"state": WAIT_TEXT, "as_at": None, "rows": [], "flagged": Counter(), "unread": [],
                    "profile": profile, "version": version}
    for n, (first, last, _t) in enumerate(parts, 1):
        got = store.get(keys[n - 1])
        if not (got.checks or {}).get("usable", True) or not got.text:
            unusable.append(n)
            continue
        body = json.loads(got.text)
        as_at = as_at or body.get("as_at")
        for m in body["members"]:
            m["pages"] = f"{first}-{last}" if first != last else str(first)
            m["piece"] = n
        members += body["members"]
    if len(unusable) == len(parts):
        return {"state": "set aside: the text reader gave no usable answer", "as_at": None, "rows": [],
                "flagged": Counter(), "unread": [], "profile": profile, "version": version}
    rows, flagged = kept(members)
    for r in rows:
        m = members[r["member_no"] - 1]
        r.update(pages=m["pages"], piece=m["piece"], model=got.model)
    return {"state": "read", "as_at": as_at, "rows": rows, "flagged": flagged,
            "unread": sorted(set(too_big) | set(thin)), "unusable_pieces": unusable, "profile": profile,
            "version": used}


def _version(profile: str, version: int = None) -> int:
    """The version a reading is keyed under: the one given for the PDF profile (a test's), else the ledger's."""
    return version if (version and profile == PROFILE) else profile_version(profile)


# ── the job ────────────────────────────────────────────────────────────────────────────────────────────────────
def waiting(conn, store: rd.Store = None, version: int = None, read_bytes=None) -> list:
    """The register PDFs with a text layer, and the pages that print a register, with a piece not yet stored,
    smallest first (sha256). Pages: the newest landed copy of every page the capture asked."""
    from support.docstore.landing import read_bytes as rb
    read_bytes = read_bytes or rb
    store = store or rd.Store()
    out = []
    docs = conn.execute("SELECT sha256, council FROM councillor_interests.documents ORDER BY council, sha256").fetchall()
    with_docs = {c for _s, c in docs}
    shas = [s for s, _c in docs]
    from registers.councillor_interests import capture
    pages_of = {s: (u, capture.REGISTERS.get(c, ("",))[0]) for s, c, u in conn.execute(
        "SELECT DISTINCT ON (url) sha256, council, url FROM councillor_interests.capture_items WHERE kind = 'page' "
        "AND sha256 IS NOT NULL ORDER BY url, asked_at DESC").fetchall() if page_wanted(c, with_docs)}
    shas += list(pages_of)
    for sha in dict.fromkeys(shas):
        data = read_bytes(sha)
        why, texts, profile = prepare(data) if sha not in pages_of else recognise_page(data, *pages_of[sha])
        if why:
            continue
        if profile == PAGE_PROFILE and read.recognise(data) == "register":
            continue                                        # the page grammar reads it
        v = _version(profile, version)
        parts, _big, _thin = pieces(texts)
        if any(not store.has(key_for(sha, n, v, profile=profile)) for n in range(1, len(parts) + 1)):
            out.append((sum(len(p[2]) for p in parts), sha))
    return [sha for _n, sha in sorted(out)]


def piece(sha256: str, *, url: str, model: str, store: rd.Store = None, post=None, request: dict = None,
          wait_s: float = 0.0) -> dict:
    """One piece of `qv4-councillor-interests-read`: the document's bytes from the store, every reading piece read."""
    from support.docstore.landing import read_bytes
    data = read_bytes(sha256)
    version = None
    deadline = time.monotonic() + wait_s
    t0 = time.monotonic()
    while True:
        try:
            got = read_document(sha256, data, version=version, url=url, model=model, store=store, post=post,
                                request=request)
            break
        except (urllib.error.URLError, ConnectionError, modelclient.WrongModel) as exc:
            if time.monotonic() >= deadline:
                raise
            print(f"councillor interests read: the model is not answering ({type(exc).__name__}); waiting a minute",
                  file=sys.stderr)
            time.sleep(60)
    return {**got, "document": sha256, "profile": f"{got['profile']}@{_version(got['profile'])}", "seconds": round(time.monotonic() - t0, 1)}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    database = argv[argv.index("--database") + 1] if "--database" in argv else "querynz_v4"
    from support import db
    if "--pieces" in argv:
        with db.connect(db.READ_KEY, database) as conn:
            conn.execute("SET statement_timeout = '60s'")
            for sha in waiting(conn):
                print(sha)
        return 0
    if "--piece" in argv:
        sha = argv[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            print("--piece takes the document's sha256 as the last argument", file=sys.stderr)
            return 2
        request = json.loads(os.environ.get("QV4_MODEL_REQUEST") or "{}")
        line = piece(sha, url=os.environ.get("QV4_MODEL_URL") or URL, model=os.environ.get("QV4_MODEL") or TEXT_MODEL,
                     request=request, wait_s=5400 if "--wait" in argv else 0)
        print(f"councillor interests read: {sha[:12]} {line['profile']}: {line['state']}, {line['pieces']} piece(s), "
              f"{line['read']} read now, {line['replayed']} replayed, {line['members']} member(s), {line['seconds']} s")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
