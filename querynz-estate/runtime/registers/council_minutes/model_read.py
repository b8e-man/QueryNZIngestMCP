"""The text reader's reading of a council's minutes PDF in any shape but the standard template (profile
`council-minutes-text` v1; Arthur, 2 November 2026: "do it"; ruling 128 lifted ruling 79's hold on model reading for
node2 alone; ruling 130 (b): a document over the budget is read in pieces by its rule, never excerpted).

What the model sees is the text left after minutes.sections' two skips: no public-excluded part and no public forum
item ever reaches it (hard limit 16). The text layer is `pdftotext -layout` (support.docread.pages); the text reader
(profile `text-reader`, the standing server on this box, hard limit 10) reads it through the model client. One reading
per document hash and piece, stamped with the reader's version, the served model and the prompt's hash, stored in the
reader store and replayed by every load (ruling 50: the load calls no model). A scan (profile council-minutes-scanned)
comes here once the page reader has read its every page (scans.py): its page texts take the text layer's place, go
through the same two skips, and its pieces' settings name the page reader as their text's source.

Whatever the model answers: an attendee whose name is shaped like an address, a phone number or an email, or who is a
member of the public, is dropped; a resolution's text is kept whole with minutes.names_address beside it (ruling 102).

    python -m registers.council_minutes.model_read --pieces            every minutes PDF of this profile waiting, one sha256 a line
    python -m registers.council_minutes.model_read --piece SHA256      one piece of qv4-council-minutes-read
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
from registers.council_minutes import minutes as M
from registers.council_minutes import scans as SC

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "profiles-proposed.jsonl")
READER = "registers.council_minutes.model_read 1"
LANE = "council_minutes"
PROFILE = M.TEXT
TEXT_MODEL = os.environ.get("QV4_COUNCIL_MINUTES_TEXT_MODEL") or "qwen4exp"     # profiles.toml [profiles.text-reader]
URL = os.environ.get("QV4_MODEL_URL") or "http://127.0.0.1:8060/v1/chat/completions"
#: the councillor-interests measure (2 November 2026): answers run about as long as their text, and an answer past about
#: 14,500 characters is cut at the answer limit; 12,000 characters in and 8,192 tokens out stay inside the text-reader
#: profile's 16,384-token request
BUDGET_CHARS = 12000
SPLIT = "pages, then lines"
MAX_TOKENS = 8192
ATTEMPTS = 2
WAIT_TEXT = "waiting: text reader"
ATTENDANCE = ("present", "in attendance", "apology", "absent")
OUTCOMES = ("CARRIED", "LOST", "LAPSED", "WITHDRAWN", "ADJOURNED", "NOTED")
PROMPT = (
    "You read part of the minutes of one meeting of a New Zealand council, committee or community board. Answer with ONE "
    "JSON object and nothing else:\n"
    '{"attendance": [{"name": "<a person\'s name exactly as printed, without the title>", '
    '"role": "<Mayor, Deputy Mayor, Councillor, Chair, Member, ... as printed, or null>", '
    '"title": "<an officer\'s job title as printed, or null>", '
    '"attendance": "present" | "in attendance" | "apology" | "absent"}],\n'
    ' "declarations": [{"member": "<the member\'s name as printed, without the title>", "item": "<the item number, or '
    'null>", "text": "<the sentence that records the declaration, as printed>"}],\n'
    ' "resolutions": [{"item": "<the item number as printed, or null>", "item_title": "<the item\'s heading as printed, '
    'or null>", "number": "<the council\'s resolution number, or null>", "mover": "<as printed, or null>", '
    '"seconder": "<as printed, or null>", "text": "<the resolution or motion exactly as printed>", '
    '"outcome": "CARRIED" | "LOST" | "LAPSED" | "WITHDRAWN" | "ADJOURNED" | "NOTED" | null, '
    '"votes_for": "<names or a count as printed, or null>", "votes_against": "<as printed, or null>", '
    '"abstained": "<as printed, or null>"}]}\n'
    "Rules. attendance: the members present, the officers and others in attendance, the apologies and the absent, each "
    "once, as the minutes list them; never a member of the public, a submitter or a speaker from the public. "
    "declarations: only a declaration of interest or conflict of interest a member made at this meeting; none if the "
    "minutes record none. resolutions: every resolution, motion or recommendation the meeting decided, in order, with "
    "its text exactly as printed; the mover and seconder as printed (\"Cr Smith\" or \"Smith/Jones\"); the outcome as "
    "printed. Never copy a street address, a postal address, an email address or a telephone number into a name. Keep "
    "spelling and macrons as printed. Never add anything the text does not print. An empty list is right where the part "
    "has none.")
NUDGE = "Your answer held no JSON object. Answer again with the ONE JSON object described, and nothing else."
_JSON = re.compile(r"\{.*\}", re.S)
_CONTACT = re.compile(r"@|\b\d{3}[\s-]?\d{3,4}[\s-]?\d{3,4}\b|\bPO Box\b|\bRD\s?\d\b", re.I)
PUBLIC = re.compile(r"\b(member of the public|members of the public|public|submitter|resident|ratepayer)\b", re.I)


def profile_version(slug: str = PROFILE) -> int:
    held = [p for p in (profiles.profile(slug), profiles.profile(slug, path=PROPOSED) if os.path.exists(PROPOSED) else None) if p]
    if not held:
        raise LookupError(f"no document profile {slug}")
    return max(int(p["version"]) for p in held)


def settings(prompt: str = PROMPT, source: str = None) -> dict:
    """The reading's settings; `source` names the page reader's text when the document is a scan (scans.SOURCE), so
    a scan's pieces never share a key with a text layer's. A text layer's settings are as they were."""
    out = {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16], "budget_chars": BUDGET_CHARS, "split": SPLIT,
           "temperature": 0.0, "max_tokens": MAX_TOKENS, "thinking": False, "attempts": ATTEMPTS, "skips": "minutes.sections 2 (running heads dropped)"}
    if source:
        out["text"] = source
    return out


def key_for(sha256: str, piece: int, version: int, model: str = TEXT_MODEL, source: str = None) -> str:
    return rd.reading_key(sha256, piece, model, settings(source=source), PROFILE, version)


def texts_for(sha256: str, data: bytes, store: rd.Store = None) -> tuple:
    """(texts, source, why): a text layer's pages (source None); a scan's page-reader pages once every page is
    stored (source scans.SOURCE); or (None, None, why) for a scan still waiting on the page reader, or a PDF with no
    text layer that is no scan."""
    if not data[:5].startswith(b"%PDF"):
        return None, None, "not a PDF"
    layer = pages.text_pages(data)
    if pages.read_from(data, layer) != "pixels":
        return layer, None, ""
    prof, why = SC.recognise(data, layer)
    if prof != SC.PROFILE:
        return None, None, why
    got, _unread = SC.texts(sha256, data, store, layer=layer)
    if got is None:
        return None, None, M.WAIT_PAGES
    return got, SC.SOURCE, ""


def prepare(data: bytes, texts: dict = None) -> tuple:
    """(why, texts, kept lines, skipped): why is '' when the document is this profile's. `texts` may be a scan's
    page-reader pages (texts_for), recognised exactly as a text layer is."""
    if not data[:5].startswith(b"%PDF"):
        return "not a PDF", {}, [], {}
    texts = texts if texts is not None else pages.text_pages(data)
    prof, why = M.recognise(texts, pages.read_from(data, texts))
    if prof != PROFILE:
        return why or f"the {prof} profile, read deterministically", texts, [], {}
    kept, skipped = M.sections(texts)
    return "", texts, kept, dict(skipped)


def pieces(kept: list, thin: set, budget: int = BUDGET_CHARS) -> list:
    """[(first page, last page, text)]: the kept lines of whole pages packed in order up to the budget; a page over it
    cut at line ends. A thin page (no text layer) has no lines here and is named unread by the load."""
    by_page = {}
    for p, line in kept:
        if p not in thin:
            by_page.setdefault(p, []).append(line)
    out, cur, first, last, size = [], [], None, None, 0
    for p in sorted(by_page):
        t = "\n".join(by_page[p]).strip()
        if not t:
            continue
        if len(t) > budget:
            if cur:
                out.append((first, last, "\n\n".join(cur)))
                cur, size = [], 0
            part, n = [], 0
            for line in t.splitlines():
                line = line[:budget - 60]
                if part and n + len(line) + 1 > budget - 40:
                    out.append((p, p, f"[page {p}]\n" + "\n".join(part)))
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
    return out


def _clean(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "", "null") else None


def parse_answer(text: str):
    """The JSON object, checked and normalised, or None. Nothing the lane never keeps survives it."""
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        body = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    att, dec, res = [], [], []
    for a in body.get("attendance") or []:
        if not isinstance(a, dict) or not _clean(a.get("name")):
            continue
        name = _clean(a["name"])
        kind = str(a.get("attendance") or "").strip().lower()
        if kind not in ATTENDANCE or _CONTACT.search(name) or M.names_address(name) or PUBLIC.search(name) \
                or PUBLIC.search(_clean(a.get("role")) or "") or len(name.split()) > 6:
            continue
        att.append({"name": name, "role": _clean(a.get("role")), "title": _clean(a.get("title")), "attendance": kind})
    for d in body.get("declarations") or []:
        if isinstance(d, dict) and _clean(d.get("member")) and not _CONTACT.search(_clean(d["member"])):
            dec.append({"member": _clean(d["member"]), "item": _clean(d.get("item")), "text": (_clean(d.get("text")) or "")[:600]})
    for r in body.get("resolutions") or []:
        if not isinstance(r, dict) or not _clean(r.get("text")):
            continue
        out = str(r.get("outcome") or "").strip().upper()
        res.append({"item": _clean(r.get("item")), "item_title": _clean(r.get("item_title")), "number": _clean(r.get("number")),
                    "mover": _clean(r.get("mover")), "seconder": _clean(r.get("seconder")), "text": _clean(r["text"]),
                    "outcome": out if out in OUTCOMES else None, "votes_for": _clean(r.get("votes_for")),
                    "votes_against": _clean(r.get("votes_against")), "abstained": _clean(r.get("abstained"))})
    return {"attendance": att, "declarations": dec, "resolutions": res}


def ask(text: str, *, url: str, model: str, post=None, request: dict = None, timeout: float = 900.0) -> tuple:
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


def read_document(sha256: str, data: bytes, *, version: int = None, url: str = None, model: str = None,
                  store: rd.Store = None, post=None, request: dict = None) -> dict:
    """Every piece read once and stored (piece n as page n of the reading key); a stored piece is replayed."""
    store = store or rd.Store()
    model = model or TEXT_MODEL
    version = version or profile_version()
    texts, source, why = texts_for(sha256, data, store)
    if not why:
        why, texts, kept, skipped = prepare(data, texts)
    if why:
        return {"state": why, "pieces": 0, "read": 0, "replayed": 0, "resolutions": 0}
    parts = pieces(kept, set(pages.thin_pages(texts)))
    out = {"state": "read", "pieces": len(parts), "read": 0, "replayed": 0, "resolutions": 0, "unusable": 0}
    for n, (first, last, text) in enumerate(parts, 1):
        key = key_for(sha256, n, version, model, source)
        if store.has(key):
            got = store.get(key)
            out["replayed"] += 1
        else:
            now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            parsed, served, attempts, chars = ask(text, url=url or URL, model=model, post=post, request=request)
            checks = {"pages": [first, last], "attempts": attempts, "answer_chars": chars, "pieces": len(parts)}
            if parsed is None:
                got = rd.Reading(sha256, n, READER, served, settings(source=source), PROFILE, version, "text", "", rows=[],
                                 checks={**checks, "usable": False,
                                         "reason": f"no usable JSON object in the answer after {attempts} attempt(s)"},
                                 made_at=now)
            else:
                got = rd.Reading(sha256, n, READER, served, settings(source=source), PROFILE, version, "text",
                                 json.dumps(parsed, ensure_ascii=False, sort_keys=True), rows=[],
                                 checks={**checks, "usable": True, "resolutions": len(parsed["resolutions"])}, made_at=now)
            store.put(got)
            out["read"] += 1
        if not (got.checks or {}).get("usable", True) or not got.text:
            out["unusable"] += 1
        else:
            out["resolutions"] += len(json.loads(got.text)["resolutions"])
    return out


def replay(sha256: str, data: bytes, *, version: int = None, store: rd.Store = None, model: str = TEXT_MODEL,
           texts: dict = None, source: str = None) -> dict:
    """The load's side, never a call: {'state', 'attendance', 'declarations', 'resolutions', 'skipped', 'unread', 'model'}.
    `texts` and `source`: a scan's page-reader pages and scans.SOURCE (the load passes them); left out, the text layer's."""
    store = store or rd.Store()
    version = version or profile_version()
    why, texts, kept, skipped = prepare(data, texts)
    empty = {"attendance": [], "declarations": [], "resolutions": [], "skipped": skipped, "unread": [], "model": None}
    if why:
        return {**empty, "state": why}
    thin = set(pages.thin_pages(texts))
    parts = pieces(kept, thin)
    att, dec, res, unusable, model_seen = [], [], [], [], None
    for n, (first, last, _t) in enumerate(parts, 1):
        key = key_for(sha256, n, version, model, source)
        if not store.has(key):
            return {**empty, "state": WAIT_TEXT}
        got = store.get(key)
        if not (got.checks or {}).get("usable", True) or not got.text:
            unusable.append(n)
            continue
        model_seen = got.model
        body = json.loads(got.text)
        for x in body["attendance"]:
            att.append({**x, "page": first, "place": f"piece {n}"})
        for x in body["declarations"]:
            dec.append({**x, "role": None, "page": first})
        for x in body["resolutions"]:
            res.append({**x, "page": first, "place": f"piece {n}"})
    if parts and len(unusable) == len(parts):
        return {**empty, "state": "set aside: the text reader gave no usable answer"}
    seen, uniq = set(), []
    for a in att:
        k = (a["name"].lower(), a["attendance"])
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return {"state": "read", "attendance": uniq, "declarations": dec, "resolutions": res, "skipped": skipped,
            "unread": sorted(thin), "unusable_pieces": unusable, "model": model_seen}


# ── the job ────────────────────────────────────────────────────────────────────────────────────────────────────
def waiting(conn, store: rd.Store = None, version: int = None, read_bytes=None) -> list:
    """The landed minutes PDFs of this profile with a piece not yet stored, smallest first (sha256); a scan once the
    page reader has read every page of it."""
    from support.docstore.landing import read_bytes as rb
    read_bytes = read_bytes or rb
    store = store or rd.Store()
    version = version or profile_version()
    out = []
    for (sha,) in conn.execute("SELECT DISTINCT sha256 FROM council_minutes.capture_documents WHERE state = 'landed' "
                               "AND sha256 IS NOT NULL ORDER BY sha256").fetchall():
        data = read_bytes(sha)
        texts, source, why = texts_for(sha, data, store)
        if why:
            continue
        why, texts, kept, _sk = prepare(data, texts)
        if why:
            continue
        parts = pieces(kept, set(pages.thin_pages(texts)))
        if any(not store.has(key_for(sha, n, version, source=source)) for n in range(1, len(parts) + 1)):
            out.append((sum(len(p[2]) for p in parts), sha))
    return [sha for _n, sha in sorted(out)]


def piece(sha256: str, *, url: str, model: str, store: rd.Store = None, post=None, request: dict = None,
          wait_s: float = 0.0) -> dict:
    """One piece of `qv4-council-minutes-read`: the document's bytes from the store, every reading piece read."""
    from support.docstore.landing import read_bytes
    data = read_bytes(sha256)
    deadline = time.monotonic() + wait_s
    t0 = time.monotonic()
    while True:
        try:
            got = read_document(sha256, data, url=url, model=model, store=store, post=post, request=request)
            break
        except (urllib.error.URLError, ConnectionError, modelclient.WrongModel) as exc:
            if time.monotonic() >= deadline:
                raise
            print(f"council minutes read: the model is not answering ({type(exc).__name__}); waiting a minute", file=sys.stderr)
            time.sleep(60)
    return {**got, "document": sha256, "seconds": round(time.monotonic() - t0, 1)}


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
        print(f"council minutes read: {sha[:12]} {PROFILE}@{profile_version()}: {line['state']}, {line['pieces']} piece(s), "
              f"{line['read']} read now, {line['replayed']} replayed, {line['resolutions']} resolution(s), {line['seconds']} s")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
