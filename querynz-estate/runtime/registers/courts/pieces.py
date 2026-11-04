"""A document held to the text reader's context, by its profile's rule
(ruling 130, 31 October 2026: "some of the bigger docs may need a bigger
context window … it should be a document profile check").

The text-reader profile serves 16,384 tokens a request, the answer's room
(`model_read.MAX_TOKENS`) reserved inside it; measured on 5,679 courts
calls of 30 and 31 October the model's text ran 3.3 to 4.6 characters a
token (median 3.96), so a piece of `budget_chars` characters of document
text plus the system prompt fits with room to spare at the worst ratio
seen. Each courts profile carries, in its `reading` field, the budget and
the split rule; a document the rule cannot split is set aside at read,
named, never excerpted (the reader of 30 October sent the head and tail of
a long document, so more than half the judgments' names were read from an
excerpt; this module replaces that).

Rules:
  whole        the document fits or is set aside (case pages, media releases, synopses)
  paragraphs   a judgment or determination: the caption first and whole (everything before paragraph 1), then
               runs of numbered paragraphs ([1], [2], … in sequence; an older determination's "1.", "2.", a
               submission's "1.1", "2.1" by their first number, or a bare "1", "2" two spaces before its text, as
               counsel's submissions print, indented up to 40 spaces); a run longer than the budget is cut at its page
               breaks; a page longer than the budget, or fewer than two numbered paragraphs in a document over the
               budget, cannot be split
  numbered     counsel's submissions: the same rule (the name says what the markers usually are)
  pages        a hearing transcript: runs of whole pages; a page longer than the budget is cut at its speaker turns

Every piece after the first opens with the document's first lines (its
court line, citation and parties) for context, inside the budget.

The fallback (Arthur, 3 November 2026: "read them page by page"): a rule may
name `fallback: pages`. Where its own split cannot cut the document (no
numbered paragraphs to split at, a page in a run too long), a page is a
valid piece boundary: runs of whole pages within the budget, each a piece,
the readings joined under the one hash as any pieces are. A page longer
than the budget still cannot be split (no cut inside a page), and the
document is set aside, named. A document the rule's own split cuts is
planned exactly as before, so its reading's key does not move
(support.profiles.reading_version keeps the version for it).

    rule_of(slug)                      the profile's reading rule {budget_chars, split[, fallback]}
    plan(texts, rule)                  (pieces: [str], None) or (None, why)
    plan_how(texts, rule)              (pieces, None, the split that cut it) or (None, why, None)
    count(texts, rule)                 the number of pieces, or None
"""
import re

from registers.courts import caption

CONTEXT_CHARS = 800          # the head of page 1 repeated at the top of every later piece
SPLITS = ("whole", "paragraphs", "numbered", "pages")
#: the splits a rule may fall back to where its own cannot cut the document, and the rules that may carry one
FALLBACKS = ("pages",)
FALLS_BACK = ("paragraphs", "numbered")
NUMBERED = re.compile(r"^\s{0,40}(\d{1,3})(?:\.(?:\d{1,2}\.?)?\s+|\s{2,})\S")   # "1.", "1.1", or a bare "1  "; submissions indent theirs up to 32
PAGE_MARK = "[page {p}]\n"


def rule_of(slug: str, profile_of=None) -> dict:
    """The reading rule of the profile's newest line that carries one: a
    courts profile without a rule is a fault (the profile test holds it)."""
    from registers.courts import read as R
    p = (profile_of or R.profile_of)(slug)
    rule = (p or {}).get("reading")
    if not rule or rule.get("split") not in SPLITS or not isinstance(rule.get("budget_chars"), int) or rule["budget_chars"] < 2000:
        raise LookupError(f"document profile {slug} carries no reading rule (budget_chars, split one of {SPLITS})")
    out = {"budget_chars": int(rule["budget_chars"]), "split": rule["split"]}
    if rule.get("fallback") is not None:
        if rule["fallback"] not in FALLBACKS or rule["split"] not in FALLS_BACK:
            raise LookupError(f"document profile {slug}: a fallback is one of {FALLBACKS}, on a split of {FALLS_BACK}")
        out["fallback"] = rule["fallback"]
    return out


def body_of(texts: dict) -> str:
    """Every page in order, each under its marker (the model cites a page)."""
    return "\n".join(PAGE_MARK.format(p=p) + (texts[p] or "").rstrip() for p in sorted(texts) if (texts[p] or "").strip())


def _lines(texts: dict) -> list:
    """[(page, line)] in order, a marker line opening each page."""
    out = []
    for p in sorted(texts):
        if not (texts[p] or "").strip():
            continue
        out.append((p, PAGE_MARK.format(p=p).rstrip("\n")))
        out.extend((p, ln) for ln in (texts[p] or "").rstrip().splitlines())
    return out


def _blocks(lines: list, marker) -> list:
    """Runs of lines cut where `marker(line)` names the next number in
    sequence (1, 2, 3 …): the first block is everything before [1]."""
    blocks, cur, want = [], [], 1
    for p, ln in lines:
        n = marker(ln)
        if n == want and cur:
            blocks.append(cur)
            cur = []
            want += 1
        elif n == want:
            want += 1
        cur.append((p, ln))
    if cur:
        blocks.append(cur)
    return blocks


def _para_marker(ln: str):
    m = caption.PARA.match(ln)
    return int(m.group(2)) if m else None


def _numbered_marker(ln: str):
    """[n], "n.", "n.m" or a bare "n  " at the margin: the paragraph's first number."""
    m = caption.PARA.match(ln)
    if m:
        return int(m.group(2))
    m = NUMBERED.match(ln)
    return int(m.group(1)) if m else None


def _by_pages(block: list) -> list:
    out, cur = [], []
    for p, ln in block:
        if cur and p != cur[-1][0]:
            out.append(cur)
            cur = []
        cur.append((p, ln))
    if cur:
        out.append(cur)
    return out


def _by_speakers(block: list) -> list:
    from registers.courts.read import SPEAKER, SPEAKER_COLUMN
    out, cur = [], []
    for p, ln in block:
        if cur and (SPEAKER.match(ln + " ") or SPEAKER_COLUMN.match(ln)):
            out.append(cur)
            cur = []
        cur.append((p, ln))
    if cur:
        out.append(cur)
    return out


def _size(block: list) -> int:
    return sum(len(ln) + 1 for _, ln in block)


def _text(block: list) -> str:
    return "\n".join(ln for _, ln in block)


def context_of(texts: dict, chars: int = CONTEXT_CHARS) -> str:
    first = (texts.get(min(texts)) if texts else "") or ""
    head = first.strip()[:chars]
    return head[:head.rfind("\n")] if "\n" in head else head


def plan(texts: dict, rule: dict) -> tuple:
    """(the pieces as the model receives them, None) or (None, why the rule
    cannot split the document). One piece when the whole fits."""
    got, why, _ = plan_how(texts, rule)
    return got, why


def plan_how(texts: dict, rule: dict) -> tuple:
    """`plan`, and the split that cut the document: the rule's own, or its
    fallback where the rule's own cannot (None when neither can)."""
    got, why = _plan(texts, rule["budget_chars"], rule["split"])
    if got is not None:
        return got, None, rule["split"]
    fallback = rule.get("fallback")
    if not fallback:
        return None, why, None
    got, why2 = _plan(texts, rule["budget_chars"], fallback, finer=False)
    if got is not None:
        return got, None, fallback
    return None, f"{why}; the fallback by {fallback}: {why2}", None


def _plan(texts: dict, budget: int, split: str, finer: bool = True) -> tuple:
    """One split's plan. `finer=False`: a block over the budget is not cut
    finer (the fallback by pages never cuts inside a page)."""
    body = body_of(texts)
    if len(body) <= budget:
        return [body], None
    if split == "whole":
        return None, f"{len(body):,} characters over the budget of {budget:,}; the rule for this profile is whole"
    lines = _lines(texts)
    if split == "pages":
        blocks = _by_pages(lines)
        finer, finer_name = (_by_speakers if finer else (lambda b: [b])), ("speaker turn" if finer else "page")
    else:
        blocks = _blocks(lines, _para_marker)
        if len(blocks) < 3:
            blocks = _blocks(lines, _numbered_marker)      # no [n] paragraphs: "1.", "1.1" at the margin
        if len(blocks) < 3:   # the caption, [1], and at least [2]
            return None, (f"{len(body):,} characters over the budget of {budget:,} and fewer than two numbered paragraphs to split at; "
                          f"the rule is {split}")
        finer, finer_name = _by_pages, "page"
    context = context_of(texts)
    room = budget - len(context) - 120     # every piece after the first opens with the context; one limit for all
    units = []
    for b in blocks:
        if _size(b) <= room:
            units.append(b)
            continue
        for u in finer(b):
            if _size(u) > room:
                return None, (f"a {finer_name} of {_size(u):,} characters exceeds the budget of {budget:,} less the context "
                              f"(the document has {len(body):,}); the rule is {split}")
            units.append(u)
    pieces, cur, size = [], [], 0
    for u in units:
        if cur and size + _size(u) > room:
            pieces.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += _size(u)
    if cur:
        pieces.append(cur)
    n = len(pieces)
    out = []
    for i, blocks in enumerate(pieces, 1):
        text = "\n".join(_text(b) for b in blocks)
        if i > 1:
            text = f"[part {i} of {n} of the document; its first lines, for context:]\n{context}\n[…]\n\n" + text
        if len(text) > budget:
            return None, f"piece {i} of {n} came to {len(text):,} characters over the budget of {budget:,}; the rule is {split}"
        out.append(text)
    return out, None


def count(texts: dict, rule: dict):
    got, _ = plan(texts, rule)
    return len(got) if got else None
