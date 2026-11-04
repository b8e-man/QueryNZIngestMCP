"""The text reader's reading of a court document (ruling 128): every person
and body the document names with the role the text gives each (party,
counsel, witness, judge, company, agency), counsel for each party, and a
one-line summary. Flash-Next (profile `text-reader`, the standing server;
ruling 121) through the model client, which names the model and refuses an
answer from any other; one reading per document, stamped with the reader's
version, the served model and the prompt's hash, stored by the document's
hash in the reader store and replayed from there by every load (ruling 50:
the fast tier calls no model). A document without a stored reading is
"waiting: text reader" in `courts.documents`; this module's job reads it.

The whole document is read, never an excerpt (ruling 130). A document
longer than its profile's budget is read in pieces by the profile's split
rule (`pieces.py`: the caption first and whole, then runs of numbered
paragraphs; pages for a transcript), each piece one model call whose
answer is stored as its own reading (page = the piece's number), so a job
stopped at its deadline resumes at the next piece; the pieces' people are
joined under the one hash, a name listed once across them, and the
document's summary is made from the pieces' summaries in one more call.
The joined reading is stored as the document's and replayed by every load.
A document the rule cannot split never reaches here: the load sets it
aside at stage `read`, named.

    python -m registers.courts.model_read --pieces [--database D]   the documents waiting, one key a line (for the integrator's enqueue)
    python -m registers.courts.model_read --piece SHA256            one piece of qv4-courts-read (QV4_MODEL_URL, QV4_MODEL from the worker)
    python -m registers.courts.model_read --piece SHA256 --wait     from a session: wait for the standing server to come back

The reading's text goes to the model and nowhere else (hard limit 10: the
server is on this box; limit 11: no page text is printed or logged here).
An answer cut off at the token cap (a piece naming a hundred people) is
salvaged: the complete entries are kept and the reading is stamped
`truncated`. An answer with no JSON object at all is asked once more, for
the object alone; still none, and the piece's reading is stored `unusable`;
a document none of whose pieces answered is stored `unusable` with the
reason, so the job's piece ends done, the next load sets the document
aside at stage `read`, and no job loops on it.

The keep rule under a suppression (hard limit 16) is written once here:
`kept_under_suppression` for the load, `kept_sql` for the check and the
lever; `KEPT_ROLES` and caption.CROWN are the whole of it.
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
from support import reader as rd
from registers.courts import pieces as PC

READER = "registers.courts.model_read 3"
LANE = "courts"
TEXT_MODEL = os.environ.get("QV4_COURTS_TEXT_MODEL") or "qwen4exp"      # profiles.toml [profiles.text-reader] model
URL = os.environ.get("QV4_MODEL_URL") or "http://127.0.0.1:8060/v1/chat/completions"
MAX_TOKENS = 4096           # the answer's room inside the text-reader profile's 16,384-token context; the budget is the profile's
ROLES = ("party", "counsel", "witness", "judge", "company", "agency", "other")
KINDS = ("person", "body")
#: the roles a suppression never withholds: the court's officers and a public agency (the Crown is caption.CROWN)
KEPT_ROLES = ("judge", "counsel", "agency")
ATTEMPTS = 2
#: what the text reader's answer gives, field by field (the profiles' `by: model` items): field → the answer's keys that
#: carry it, a person's keys but `summary` (pinned to parse_answer by the lane's tests)
FIELDS = {"people": ("name", "kind"), "role": ("role", "role_text"), "for_party": ("for",), "summary": ("summary",),
          "details": ("details",)}
#: the kinds of detail the text reader is asked for per person (ruling 142); identifiers.KINDS is the closed vocabulary
DETAIL_KINDS = ("address", "place_of_residence", "age", "date_of_birth", "occupation", "employer", "email", "phone",
                "relationship", "other")
UNUSABLE = "the text reader answered with no usable JSON object in %d attempts"
PROMPT_WITH_SUMMARY = (
    "You read one New Zealand court document: a judgment, a media release, a hearing transcript, counsel's submissions, "
    "a case synopsis or a court's case web page. Answer with ONE JSON object and nothing else:\n"
    '{"summary": "<one sentence, at most 40 words, saying what the document is and what it decides or concerns>",\n'
    ' "people": [{"name": "<the name exactly as the document prints it>", "kind": "person" | "body", '
    '"role": "party" | "counsel" | "witness" | "judge" | "company" | "agency" | "other", '
    '"role_text": "<the role in the document\'s own words, e.g. appellant, counsel for the respondent, expert witness, sentencing judge>", '
    '"for": "<for counsel: the party acted for, as the document names it; otherwise null>"}]}\n'
    "Rules. List every person and every body (company, trust, iwi, public agency, court) the document names, each once, "
    "with the role the text gives it; a judge is role judge; a lawyer appearing is role counsel with the party in \"for\"; "
    "a company or incorporated body is kind body, role company; a government department, council, commission or police "
    "is kind body, role agency; a party to the case is role party whatever its kind. Keep initials, honorifics and "
    "spelling as printed; never expand an initial or a pseudonym; never add an address, an age or a date of birth; "
    "never name anyone the text does not name. The summary describes the document in neutral words and names nobody.")
#: the prompt from 1 November 2026 (Arthur): as before, with a role that says what it refers to (rd.ROLE_WORDS). From
#: 09:53 to the morning's release the summary was dropped and the name pass's names handed over; both were taken back
#: (the handed-over names came back with no role). Readings under the earlier prompt stand (rd.supersede).
PROMPT_ROLE_WORDS = PROMPT_WITH_SUMMARY + rd.ROLE_WORDS
#: the prompt from 4 November 2026 (ruling 142, Arthur: "we want everything"): the rule that left out an address, an age
#: and a date of birth is gone, and each person's identifying details are asked for, as printed. They land in
#: courts_private.identifiers only, tied to the person's people row. Readings under the two earlier prompts stand
#: (rd.supersede, key_for): a document read before today has its names and no details until it is read again.
DETAILS = (" For each person also give \"details\": every identifying detail the document prints about that person, each "
           "{\"kind\": \"address\" | \"place_of_residence\" | \"age\" | \"date_of_birth\" | \"occupation\" | "
           "\"employer\" | \"email\" | \"phone\" | \"relationship\" | \"other\", \"value\": \"<exactly as printed>\"}, "
           "[] when it prints none; a body's details are its address, email and phone. Leave nothing out the text prints.")
PROMPT = PROMPT_WITH_SUMMARY.replace("never add an address, an age or a date of birth; ", "") + rd.ROLE_WORDS + DETAILS
PART = ("This is part {i} of {n} of one document (part 1 holds its caption; a later part opens with the document's first lines for "
        "context). List every person and body THIS PART names, each once, with the role the document gives it; the summary is of this part.")
SUMMARY_PROMPT = ("You are given the one-sentence summaries of the parts of one New Zealand court document, in order. Answer with ONE JSON "
                  'object and nothing else: {"summary": "<one sentence, at most 40 words, saying what the whole document is and what it '
                  'decides or concerns, in neutral words, naming nobody>"}')
_JSON = re.compile(r"\{.*\}", re.S)


def settings(rule: dict, prompt: str = PROMPT, used: str = None) -> dict:
    """What the reading was made under: the prompt, the profile's budget
    and split rule, the context head, the decoding. Part of the key. A
    reading the rule's fallback cut (`used`, pieces.plan_how) says so; one
    the rule's own split cut carries exactly the settings it always did,
    so its key does not move."""
    out = {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
           "summary_prompt_sha": hashlib.sha256(SUMMARY_PROMPT.encode()).hexdigest()[:16],
           "budget_chars": rule["budget_chars"], "split": rule["split"], "context_chars": PC.CONTEXT_CHARS,
           "temperature": 0.0, "max_tokens": MAX_TOKENS, "thinking": False}
    if used is not None and used != rule["split"]:
        out["fallback"] = used
    return out


def key_for(sha256: str, profile: str, version: int, model: str = TEXT_MODEL, rule: dict = None, used: str = None) -> str:
    rule = rule or PC.rule_of(profile)
    for earlier in (PROMPT_ROLE_WORDS, PROMPT_WITH_SUMMARY):
        rd.supersede(settings(rule, used=used), settings(rule, earlier, used=used))
    return rd.reading_key(sha256, 1, model, settings(rule, used=used), profile, version)


def piece_key(sha256: str, profile: str, version: int, model: str, rule: dict, i: int, n: int, used: str = None) -> str:
    """A piece's own reading: page = its number, the settings saying which of how many."""
    for earlier in (PROMPT_ROLE_WORDS, PROMPT_WITH_SUMMARY):
        rd.supersede({**settings(rule, used=used), "piece": i, "of": n}, {**settings(rule, earlier, used=used), "piece": i, "of": n})
    return rd.reading_key(sha256, i, model, {**settings(rule, used=used), "piece": i, "of": n}, profile, version)


def parse_answer(text: str):
    """The JSON object in the model's answer, checked: None when there is no
    usable object. An object cut off before its end (the answer hit the
    token cap) is salvaged to its last complete entry, and the result says
    so (`truncated`)."""
    body, truncated = _object(text or "")
    if body is None:
        return None
    people, seen = [], set()
    for item in body["people"]:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()
        if not name:
            continue
        role = str(item.get("role") or "other").strip().lower()
        role = role if role in ROLES else "other"
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in KINDS:
            kind = "body" if role in ("company", "agency") else "person"
        for_party = item.get("for")
        for_party = re.sub(r"\s+", " ", str(for_party)).strip() if for_party not in (None, "", "null") else None
        if (name.upper(), role) in seen:        # each once (the prompt's rule); a model that loops repeats a name
            continue
        seen.add((name.upper(), role))
        entry = {"name": name, "kind": kind, "role": role,
                 "role_text": (re.sub(r"\s+", " ", str(item.get("role_text") or "")).strip() or None),
                 "for": for_party, "details": _details(item.get("details"))}
        if isinstance(item.get("part"), int):
            entry["part"] = item["part"]
        people.append(entry)
    summary = re.sub(r"\s+", " ", str(body.get("summary") or "")).strip() or None
    return {"summary": summary, "people": people, "truncated": truncated, "parts": body.get("parts") or 1}


def _details(raw) -> list:
    """A person's identifying details as the reader gave them: [{kind, value}], the kind in DETAIL_KINDS (else
    `other`), the value as printed, each once."""
    out, seen = [], set()
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        value = re.sub(r"\s+", " ", str(d.get("value") or "")).strip()
        if not value or value.lower() in ("null", "none", "n/a"):
            continue
        kind = str(d.get("kind") or "").strip().lower().replace(" ", "_")
        kind = kind if kind in DETAIL_KINDS else "other"
        if (kind, value) not in seen:
            seen.add((kind, value))
            out.append({"kind": kind, "value": value})
    return out


def _object(text: str):
    """(the answer's object with a `people` list, whether it was salvaged)
    or (None, False). A whole object first; failing that, the text from its
    first brace cut at each closing brace from the end, the people list and
    the object closed after it, until one parses: the entries before the cut
    are complete, the cut one is dropped."""
    m = _JSON.search(text)
    if m:
        try:
            body = json.loads(m.group(0))
            if isinstance(body, dict) and isinstance(body.get("people"), list):
                return body, False
        except ValueError:
            pass
    start = text.find("{")
    if start < 0 or '"people"' not in text:
        return None, False
    cut = len(text)
    for _ in range(400):
        cut = text.rfind("}", start + 1, cut)
        if cut < 0:
            break
        for tail in ("]}", "}"):
            try:
                body = json.loads(text[start:cut + 1] + tail)
            except ValueError:
                continue
            if isinstance(body, dict) and isinstance(body.get("people"), list):
                return body, True
    return None, False


def _chat(system: str, user: str, *, url: str, model: str, post=None, request: dict = None, timeout: float = 900.0,
          max_tokens: int = MAX_TOKENS) -> tuple:
    extra = {"temperature": 0.0, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    for k, v in (request or {}).items():
        if k not in ("temperature", "max_tokens"):
            extra.setdefault(k, v)
    out = modelclient.chat(url, lane=LANE, model=model,
                           messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                           extra=extra, timeout=timeout, post=post)
    return (out["choices"][0]["message"]["content"] or "").strip(), out.get("model") or model


def ask(text: str, *, url: str, model: str, post=None, request: dict = None, timeout: float = 900.0,
        attempt: int = 1, part: tuple = (1, 1)) -> tuple:
    """(parsed answer or None, served model) for one piece's text. One call;
    the client reads the served model back and refuses another. The second
    attempt, after an answer with no object, sends the same piece and asks
    for the object alone; there is no third."""
    i, n = part
    lead = (PART.format(i=i, n=n) + "\n\n") if n > 1 else ""
    if attempt > 1:
        lead = "Answer with the one JSON object only: no words before or after it, no code fence.\n\n" + lead
    answer, served = _chat(PROMPT, lead + "DOCUMENT TEXT:\n\n" + text, url=url, model=model, post=post, request=request, timeout=timeout)
    return parse_answer(answer), served


def summarise(summaries: list, *, url: str, model: str, post=None, request: dict = None, timeout: float = 300.0):
    """One sentence for the whole from its parts' sentences, or None."""
    user = "\n".join(f"Part {i}: {s}" for i, s in enumerate(summaries, 1) if s)
    if not user:
        return None
    answer, _ = _chat(SUMMARY_PROMPT, user, url=url, model=model, post=post, request=request, timeout=timeout, max_tokens=256)
    m = _JSON.search(answer or "")
    if not m:
        return None
    try:
        body = json.loads(m.group(0))
    except ValueError:
        return None
    s = re.sub(r"\s+", " ", str((body or {}).get("summary") or "")).strip() if isinstance(body, dict) else ""
    return s or None


def _read_piece(sha256: str, text: str, i: int, n: int, *, profile: str, version: int, rule: dict, url: str, model: str,
                store: rd.Store, post, request, used: str = None) -> tuple:
    """(parsed or None, served model, calls made: 0 for a replay). A piece's
    reading is stored under its own key and never remade; an unusable piece
    is stored too, so nothing asks it again."""
    key = piece_key(sha256, profile, version, model, rule, i, n, used)
    if store.has(key):
        got = store.get(key)
        return (None if (got.checks or {}).get("unusable") else parse_answer(got.text)), got.model, 0
    parsed = served = None
    for attempt in range(1, ATTEMPTS + 1):
        parsed, served = ask(text, url=url, model=model, post=post, request=request, attempt=attempt, part=(i, n))
        if parsed is not None:
            break
    made = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    piece_settings = {**settings(rule, used=used), "piece": i, "of": n}
    if parsed is None:
        reading = rd.Reading(sha256, i, READER, served or model, piece_settings, profile, version, "text", "",
                             checks={"people": 0, "summary": False, "unusable": UNUSABLE % ATTEMPTS, "attempts": ATTEMPTS, "chars": len(text)}, made_at=made)
    else:
        reading = rd.Reading(sha256, i, READER, served, piece_settings, profile, version, "text",
                             json.dumps(parsed, ensure_ascii=False, sort_keys=True), rows=parsed["people"],
                             checks={"people": len(parsed["people"]), "summary": bool(parsed["summary"]),
                                     "truncated": bool(parsed.get("truncated")), "attempts": attempt, "chars": len(text)}, made_at=made)
    store.put(reading)
    return parsed, served, attempt


def read_one(sha256: str, texts: dict, *, profile: str, version: int, url: str = None, model: str = None,
             store: rd.Store = None, post=None, request: dict = None, rule: dict = None) -> dict:
    """The document read once and stored; a stored reading is replayed, never
    remade. The whole document, in pieces by the profile's rule where it is
    longer than the budget; the pieces' people joined, a name once across
    them; the summary from the parts' summaries in one more call. After
    ATTEMPTS answers with no usable object on every piece an `unusable`
    reading is stored (the load sets the document aside); nothing raises
    but for a document the rule cannot split (the load never sends one)."""
    store = store or rd.Store()
    model = model or TEXT_MODEL
    url = url or URL
    rule = rule or PC.rule_of(profile)
    parts, why, used = PC.plan_how(texts, rule)     # pure and cheap: the key says which split cut the document
    key = key_for(sha256, profile, version, model, rule, used)
    if store.has(key):
        return {**_unpack(store.get(key)), "replayed": True}
    if parts is None:
        raise ValueError(f"{sha256[:12]}: the text reader cannot read it: {why}")
    n = len(parts)
    answers, served, calls, replayed = [], None, 0, 0
    for i, text in enumerate(parts, 1):
        parsed, got_model, made = _read_piece(sha256, text, i, n, profile=profile, version=version, rule=rule, url=url,
                                              model=model, store=store, post=post, request=request, used=used)
        served = got_model or served
        replayed += made == 0
        calls += made
        answers.append(parsed)
    made = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    answered = [a for a in answers if a is not None]
    if not answered:
        reading = rd.Reading(sha256, 1, READER, served or model, settings(rule, used=used), profile, version, "text", "",
                             checks={"people": 0, "summary": False, "unusable": UNUSABLE % ATTEMPTS, "attempts": ATTEMPTS, "pieces": n}, made_at=made)
        store.put(reading)
        return {**_unpack(reading), "replayed": False, "pieces": n, "calls": calls}
    people, seen = [], set()
    for i, a in enumerate(answers, 1):
        for p in (a or {"people": []})["people"]:
            if (p["name"].upper(), p["role"]) in seen:
                # the same person in a later part: the name once, every detail any part printed kept
                first = next(q for q in people if (q["name"].upper(), q["role"]) == (p["name"].upper(), p["role"]))
                first["details"] = _details((first.get("details") or []) + (p.get("details") or []))
                continue
            seen.add((p["name"].upper(), p["role"]))
            people.append({**p, "part": i})
    if n == 1:
        summary = answered[0]["summary"]
    else:
        summary = summarise([a["summary"] if a else None for a in answers], url=url, model=model, post=post, request=request)
        calls += 1
        if not summary:
            summary = next((a["summary"] for a in answered if a["summary"]), None)
    joined = {"summary": summary, "people": people, "truncated": any(a.get("truncated") for a in answered), "parts": n,
              "parts_unusable": n - len(answered)}
    reading = rd.Reading(sha256, 1, READER, served, settings(rule, used=used), profile, version, "text",
                         json.dumps(joined, ensure_ascii=False, sort_keys=True), rows=people,
                         checks={"people": len(people), "summary": bool(summary), "truncated": joined["truncated"], "pieces": n,
                                 "parts_unusable": joined["parts_unusable"]}, made_at=made)
    store.put(reading)
    return {**_unpack(reading), "replayed": False, "pieces": n, "calls": calls, "pieces_replayed": replayed}


def _unpack(reading: rd.Reading) -> dict:
    parsed = parse_answer(reading.text) or {"summary": None, "people": [], "truncated": False, "parts": 1}
    return {"summary": parsed["summary"], "people": parsed["people"], "model": reading.model, "reader": reading.reader,
            "made_at": reading.made_at, "key": reading.key, "parts": parsed.get("parts") or 1,
            "truncated": bool(parsed.get("truncated") or (reading.checks or {}).get("truncated")),   # the stored object is whole
            "unusable": (reading.checks or {}).get("unusable")}


def stored(sha256: str, profile: str, version: int, store: rd.Store, model: str = TEXT_MODEL, rule: dict = None,
           used: str = None):
    """The stored reading, unpacked, or None: the load replays and never asks. `used`: the split that cut the
    document (read.text_reading), the rule's own by default."""
    key = key_for(sha256, profile, version, model, rule, used)
    if not store.has(key):
        return None
    return _unpack(store.get(key))


def people_rows(sha256: str, reading: dict, doc: dict, profile: str, version: int, now: str) -> list:
    """One row per person or body the reading names, in the reading's order;
    the place names the part of a document read in pieces."""
    from registers.courts.read import KIND_OF
    out = []
    parts = reading.get("parts") or 1
    for n, p in enumerate(reading["people"], 1):
        place = f"text reader, name {n}" if parts == 1 else f"text reader, part {p.get('part') or 1} of {parts}, name {n}"
        out.append({"key": f"{sha256}/person/{n}", "name": p["name"], "kind": p["kind"], "role": p["role"],
                    "role_text": p.get("role_text"), "for_party": p.get("for"), "citation": doc.get("citation"),
                    "case_slug": doc.get("case_slug"), "document_kind": KIND_OF.get(profile, "document"),
                    "dated": doc.get("dated"), "withheld": False, "document": sha256, "page": 1,
                    "place": place, "read_from": "text", "reader": reading["reader"],
                    "model": reading["model"], "profile": profile, "profile_version": version, "loaded_at": now})
    return out


def detail_rows(sha256: str, reading: dict, doc: dict, profile: str, version: int, now: str) -> list:
    """courts_private.identifiers rows for the details the text reader gave per person (ruling 142), `person` the
    people row's key (people_rows numbers the same way), keyed `<sha256>/person/<n>/detail/<m>`. A reading made
    under an earlier prompt has none."""
    out = []
    parts = reading.get("parts") or 1
    for n, p in enumerate(reading["people"], 1):
        for m, d in enumerate(p.get("details") or [], 1):
            out.append({"key": f"{sha256}/person/{n}/detail/{m}", "person": f"{sha256}/person/{n}", "document": sha256,
                        "kind": d["kind"], "value": d["value"], "page": 1,
                        "place": f"text reader, name {n}" if parts == 1 else f"text reader, part {p.get('part') or 1} of {parts}, name {n}",
                        "read_from": "text", "reader": reading["reader"], "model": reading["model"], "profile": profile,
                        "profile_version": version, "loaded_at": now})
    return out


def kept_under_suppression(row: dict) -> bool:
    """Under a suppression every name is withheld but the court's officers
    (judges, counsel), a public agency and the Crown (hard limit 16: the row
    stays, the name goes). The same rule as `kept_sql`."""
    from registers.courts.caption import CROWN
    if row["role"] in KEPT_ROLES:
        return True
    return bool(CROWN.match((row.get("name") or "").upper()))


def kept_sql(alias: str = "") -> str:
    """The same rule for a `people` row in SQL: one boolean expression,
    complete in itself (the pattern is a literal, so no caller orders
    arguments around it). `alias` is the table's, with its dot."""
    from registers.courts.caption import CROWN
    assert "%" not in CROWN.pattern and "'" not in CROWN.pattern, "the pattern is inlined as a literal"
    roles = ", ".join(f"'{r}'" for r in KEPT_ROLES)
    return f"({alias}role IN ({roles}) OR upper({alias}name) ~ '{CROWN.pattern}')"


# ── the job ───────────────────────────────────────────────────────────────────────────────────────────────────
def waiting(conn, schema: str = "courts") -> list:
    """The documents waiting on the text reader, the kinds people ask about
    first: judgments and determinations, releases, transcripts, submissions,
    synopses, then case pages. [(sha256, profile, profile_version, url)]."""
    from registers.courts.read import WAIT_TEXT, JUDGMENT_SLUGS, RELEASE, TRANSCRIPT, SUBMISSION, SYNOPSIS, CASE_PAGE
    rank = {**{s: 0 for s in JUDGMENT_SLUGS}, RELEASE: 1, TRANSCRIPT: 2, SUBMISSION: 3, SYNOPSIS: 4, CASE_PAGE: 5}
    rows = conn.execute(f"SELECT DISTINCT document, profile, profile_version, url FROM {schema}.documents "
                        "WHERE outcome = %s AND document IS NOT NULL", (WAIT_TEXT,)).fetchall()
    return sorted(rows, key=lambda r: (rank.get(r[1], 9), r[3]))


def piece(sha256: str, *, url: str, model: str, store: rd.Store = None, conn=None, post=None, request: dict = None,
          wait_s: float = 0.0) -> dict:
    """One piece of `qv4-courts-read`: the document's text (text layer, or
    its stored page readings), its profile as the load recognised it, one
    call per part of the document, one stored reading. Counts and the hash
    only."""
    from support.docstore.landing import read_bytes
    from registers.courts import read as R
    store = store or rd.Store()
    data = read_bytes(sha256)
    row = None
    if conn is not None:
        row = conn.execute("SELECT key, url, kind, case_slug, profile, profile_version FROM courts.documents WHERE document = %s "
                           "ORDER BY loaded_at DESC LIMIT 1", (sha256,)).fetchone()
    entry = {"url": row[1] if row else "", "kind": row[2] if row else None, "case_slug": row[3] if row else None}
    if data.startswith(b"%PDF"):
        texts, how, unread = R._texts_of(data, sha256, store, R.profile_version(R.SCANNED))
        slug, why = R.recognise(entry, data, texts)
    else:
        page = R.case_page(data, entry["url"])
        slug, why = R.recognise(entry, data)
        texts = R._page_text_for_model(page) if page else {}
    if slug is None or slug == R.SCANNED:
        raise RuntimeError(f"{sha256[:12]}: not readable by the text reader: {why}")
    _, _, version, _ = R.text_reading(slug, texts)     # a document only the rule's fallback cuts: the fallback's version
    rule = PC.rule_of(slug)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            got = read_one(sha256, texts, profile=slug, version=version, url=url, model=model, store=store, post=post,
                           request=request, rule=rule)
            break
        except (urllib.error.URLError, ConnectionError, modelclient.WrongModel) as exc:
            if time.monotonic() >= deadline:
                raise
            print(f"courts read: the model is not answering ({type(exc).__name__}); waiting a minute", file=sys.stderr)
            time.sleep(60)
    return {"document": sha256, "profile": f"{slug}@{version}", "model": got["model"], "people": len(got["people"]),
            "summary": bool(got["summary"]), "replayed": got["replayed"], "chars": sum(len(t) for t in texts.values()),
            "pieces": got.get("pieces") or got.get("parts") or 1, "calls": got.get("calls", 0),
            "truncated": got.get("truncated", False), "unusable": got.get("unusable")}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    database = argv[argv.index("--database") + 1] if "--database" in argv else "querynz_v4"
    from support import db
    if "--pieces" in argv:
        with db.connect(db.READ_KEY, database) as conn:
            conn.execute("SET statement_timeout = '60s'")
            for sha, slug, version, url in waiting(conn):
                print(sha)
        return 0
    if "--piece" in argv:
        sha = argv[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            print("--piece takes the document's sha256 as the last argument", file=sys.stderr)
            return 2
        request = json.loads(os.environ.get("QV4_MODEL_REQUEST") or "{}")
        try:
            conn = db.connect(db.OWNER_KEY, database)
            conn.execute("SET statement_timeout = '60s'")
        except Exception:  # noqa: BLE001 — a piece without the database still reads: the profile comes from the bytes
            conn = None
        try:
            line = piece(sha, url=os.environ.get("QV4_MODEL_URL") or URL, model=os.environ.get("QV4_MODEL") or TEXT_MODEL,
                         conn=conn, request=request, wait_s=5400 if "--wait" in argv else 0)
        finally:
            if conn is not None:
                conn.close()
        print(f"courts read: {line['document'][:12]} {line['profile']} by {line['model']}: {line['people']} name(s), "
              f"summary {line['summary']}, {'replayed' if line['replayed'] else 'read now'}, {line['chars']} chars in "
              f"{line['pieces']} piece(s), {line['calls']} call(s)"
              + (", an answer cut at the token cap: the complete entries kept" if line["truncated"] else "")
              + (f"; UNUSABLE: {line['unusable']}; the next load sets the document aside" if line["unusable"] else ""))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
