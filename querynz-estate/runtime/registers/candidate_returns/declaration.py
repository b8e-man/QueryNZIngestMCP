"""The declaration page of an electorate candidate's return, read from a
page's text (the text layer with layout kept, or the page reader's stored
reading). Pure; no file, no database.

The form since 2020 ("Return of Electorate Candidate Donations and
Expenses for the 2020 General Election"; 2023 adds "Loans") prints, on its
first page:

    1. Candidate name / Party name (if applicable) / Electorate contested
    2. TOTAL CANDIDATE DONATIONS     the step cell ('NIL' or a figure)
       Part A: Candidate donations of more than $1,500
       Part C: Anonymous candidate donations of more than $1,500
       Part D: Overseas candidate donations of more than $50
                                       Total (A + C + D)
    3. TOTAL CANDIDATE ELECTION EXPENSES   the step cell
       Part F: Candidate only election advertising
       Part G: Election advertisements shared with the party and/or other candidates
                                       Total (F + G)
    4. TOTAL CANDIDATE LOANS (2023)  the step cell
       Part H: Candidate loans
    5. I declare … DATE: DD / MM / YYYY

What the layout does (measured on every text-layer return, 2020 and
2023): a figure sits on its label's line, or alone on a line between its
label and the next (above a label's wrapped second line, as `Part G`'s
often is); the step cell's figure stands before the section's first
part. The form's own thresholds (`more than $1,500`, `than $50`) are its
text, never a figure. The right-hand column is the form's checklist and
filing guidance (`PO Box 3220`, `34-42 Manners Street`), cut off at the
column where the checklist starts on that page.

Within each section the step cell is any figure from the section's
heading to the end of its sentence ("Write 'NIL' if you have NO donations
… to declare"); every other figure is given to a label. Of the ways to
give the figures to the labels in order (one figure a label; a zero may be
left over, being the form's printed default under a typed figure, as in
`0 $8,800.00`; a figure that is not zero never), the one taken is
the one under which the section's own arithmetic holds (the parts read
sum to the printed total) with the figures nearest their labels; a figure
below its label is preferred to one above. Two ways that hold equally
well with different figures is an ambiguity, reported. A part left blank
is a part with nothing declared in it and is recorded as blank. A
section whose parts and total are all zero, with one figure typed in its
step cell, declares the step cell's figure (the Commission's own reading;
check `step-cell`). A page
whose arithmetic does not hold is reported, never published. Ruling 66
(`reconcile.py`): the pairing is sought to the cent first, and only where
none holds is one sought whose parts fall short of or over the printed
total by less than $100 (the smallest difference, then the nearest
figures); such a section is published on its printed total with an issue
naming the difference (`issues`). A difference of $100 or more is still a
problem.

The page reader's stored reading of a scanned page (GLM-OCR) is plain:
each figure on its label's line after one space, no columns, the step
sentence on one line with its quoted 'NIL', and sometimes table markup.
`read(text, layout=False)` reads that: a figure is a money token after the
label (the threshold cut out), after the step sentence, or on a line of
figures alone; markup becomes spacing.

    read(text, layout=True) -> Declaration
"""
import re
from decimal import ROUND_HALF_UP, Decimal
from dataclasses import dataclass, field

from registers.candidate_returns import reconcile

MONEY = re.compile(r"(?<![\w.,/-])(?:\$\s*)?(?:(?P<nil>NIL|Nil|nil)\b|(?P<num>\d{1,3}(?:\s?,\s?\d{3})+|\d+)(?:\.(?P<cents>\d{1,4})|(?<=\d)-(?P<hcents>\d{2})(?!\d))?)(?![\d,/]|\.\d|\s?%)")
THRESHOLD = re.compile(r"(?:\bthan|\bup\s+to)\s{0,2}\$\s?[\d,]+", re.I)      # the form's `more than $1,500`, never a filed figure
TITLE = re.compile(r"for\s+the\s+(\d{4})\s+General\s+Election|(\d{4})\s+(?:\w+\s+){0,2}By-?\s?election|By-?\s?election\s+(\d{4})", re.I)
SECTIONS = (("donations", re.compile(r"TOTAL\s+CANDIDATE\s+DONATIONS", re.I)),
            ("expenses", re.compile(r"TOTAL\s+CANDIDATE\s+(?:ELECTION\s+)?EXPENSES", re.I)),
            ("loans", re.compile(r"TOTAL\s+CANDIDATE\s+LOANS", re.I)))
END = re.compile(r"^\s*\d?\.?\s*I\s+declare\b", re.I)
LABELS = (("A", re.compile(r"^\s*Part\s*A\s*[:.]", re.I)), ("C", re.compile(r"^\s*Part\s*C\s*[:.]", re.I)),
          ("D", re.compile(r"^\s*Part\s*D\s*[:.]", re.I)), ("F", re.compile(r"^\s*Part\s*F\s*[:.]", re.I)),
          ("G", re.compile(r"^\s*Part\s*G\s*[:.]", re.I)), ("H", re.compile(r"^\s*Part\s*H\s*[:.]", re.I)),
          ("total", re.compile(r"\bTotal\s*\(\s*[A-H](?:\s*\+\s*[A-H])+\s*\)", re.I)))
#: where the right-hand checklist starts: its first words on the page
GUIDE = re.compile(r"Parts?\s+A\s+to\s+E\s+completed|Parts?\s+F\s+and\s+G\s+completed|Declaration\s+signed|FILING\s+THE\s+RETURN|CHECKLIST|"
                   r"Part\s+H\s+completed|You\s+can\s+complete\s+the\s+return|or\s+by\s+hand", re.I)
GUIDE_DEFAULT = 92
FIELD = {"candidate": re.compile(r"Candidate\s+name\s*:?", re.I), "party": re.compile(r"Party\s+name(?:\s*\(if\s+applicable\))?\s*:?", re.I),
         "electorate": re.compile(r"Electorate(?:\s+contested)?\s*:", re.I)}
SIGNED = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})(?!\d)")
EXPECTED = {"donations": ("A", "C", "D"), "expenses": ("F", "G"), "loans": ("H",)}


@dataclass
class Section:
    step: list = field(default_factory=list)         # figures in the step cell (NIL is 0.0)
    step_nil: bool = False
    parts: dict = field(default_factory=dict)        # letter → figure
    blank: list = field(default_factory=list)        # labels with no figure
    total: float = None
    labels: list = field(default_factory=list)       # (label, line)
    pool: list = field(default_factory=list)         # (figure, nil, line, before the first part)
    unpaired: list = field(default_factory=list)
    ambiguous: bool = False
    step_done: bool = False                          # the step sentence has ended: what follows belongs to the labels


@dataclass
class Declaration:
    year: int = None
    candidate: str = None
    party_label: str = None
    electorate: str = None
    signed: str = None                                # the date as printed
    sections: dict = field(default_factory=dict)      # donations | expenses | loans → Section

    def figure(self, name: str):
        """A section's declared figure: its printed total; Part H for loans (the form prints no loans total); the
        parts' sum where the total line is blank; 0.00 for a section declared NIL with no figures."""
        s = self.sections.get(name)
        if s is None:
            return None
        nonnil = sorted({f for f in s.step if f})
        if len(nonnil) == 1 and not s.total and not any(s.parts.values()):
            return nonnil[0]                          # the figure typed in the step cell, the form's $0.00 left in the parts
        if s.total is not None:
            return s.total
        if s.parts:
            return round(sum(s.parts.values()), 2) if name != "loans" else s.parts.get("H")
        if len(nonnil) == 1:
            return nonnil[0]
        if s.step_nil or (s.step and not nonnil):
            return 0.0
        return None

    def check(self, name: str) -> str:
        s = self.sections.get(name)
        if s is None:
            return ""
        nonnil = {f for f in s.step if f}
        if len(nonnil) == 1 and not s.total and not any(s.parts.values()):
            return "step-cell"
        if s.total is not None and s.parts:
            return "parts-sum"
        if s.total is not None:
            return "total"
        if s.parts:
            return "parts" if name != "loans" else "part-h"
        return "declared-nil" if self.figure(name) == 0.0 else "step-cell"

    def issues(self, name: str) -> list:
        """Ruling 66: a section published on its printed total whose parts differ from it by less than $100."""
        s = self.sections.get(name)
        if s is None or name == "loans" or s.total is None or not s.parts or self.check(name) != "parts-sum":
            return []
        what = f"{name} Parts {' + '.join(sorted(s.parts))} against the printed total"
        got = reconcile.issue(round(sum(s.parts.values()), 2), s.total, what)
        return [got] if got and reconcile.within(sum(s.parts.values()), s.total) else []

    def problems(self, name: str) -> list:
        s = self.sections.get(name)
        if s is None:
            return [f"no {name} section on the page"]
        out = []
        fig = self.figure(name)
        if fig is None:
            return [f"{name}: no declared figure"]
        if s.ambiguous:
            out.append(f"{name}: two pairings of the figures with the labels hold equally well")
        if self.check(name) == "step-cell":
            return out + ([f"{name}: {len(s.unpaired)} figure(s) paired with no label"] if s.unpaired else [])
        if name != "loans" and s.total is not None and s.parts and not reconcile.within(sum(s.parts.values()), s.total):
            out.append(f"{name}: parts sum to {sum(s.parts.values()):.2f} but the total is {s.total:.2f}")
        for f in s.step:
            if f and abs(f - fig) > 0.011:
                out.append(f"{name}: the step cell says {f:.2f} but the section declares {fig:.2f}")
        if s.unpaired:
            out.append(f"{name}: {len(s.unpaired)} figure(s) paired with no label")
        return out


def amount(m) -> float:
    """A token's value. A hyphen for the point (`$2915-82`, handwriting through the page reader) counts only after a
    `$`; otherwise the token is not money (`34-42 Manners Street`) and the caller drops it (None)."""
    if m.group("nil"):
        return 0.0
    if m.group("hcents") and not m.group(0).startswith("$"):
        return None
    whole = re.sub(r"[\s,]", "", m.group("num"))
    cents = m.group("cents") or m.group("hcents") or ""
    if len(cents) > 2:                                # a form field's own arithmetic (`16112.988`, `1271.3005`): to the cent, as the Commission rounds
        return float(Decimal(f"{whole}.{cents}").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return float(f"{whole}.{cents.ljust(2, '0')}")


def guide_column(lines: list) -> int:
    cols = [m.start() for l in lines for m in [GUIDE.search(l)] if m and m.start() >= 60]
    return min(cols) if cols else GUIDE_DEFAULT


def _label(line: str):
    for name, rx in LABELS:
        m = rx.search(line)
        if m and (name == "total" or m.start() < 20):
            return name, m.end()
    return None, 0


def _field(lines: list, i: int, m) -> str:
    rest = lines[i][m.end():70].strip()
    if rest:
        return re.split(r"\s{3,}", rest)[0].strip()
    for nxt in lines[i + 1:i + 4]:
        c = nxt[:70].strip()
        if c and not any(rx.search(c) for rx in FIELD.values()) and not re.match(r"^\d?\.?\s*TOTAL", c):
            return re.split(r"\s{3,}", c)[0].strip()
    return None


TAG = re.compile(r"</?\w+[^>]*>")
STEP_WORDS = re.compile(r"Write\s+.?NIL.?\s+if\s+you\s+have\s+NO.*?to\s+declare(?:\s+under\s+Parts?\s+A,?\s*C\s+or\s+D)?", re.I)
FIGURES_ONLY = re.compile(r"^[\s$|]*(?:(?:\$\s*)?(?:NIL|Nil|nil|\d[\d,]*(?:\.\d{1,4})?)[\s|]*)+$")


def _plain_figures(line: str, start: int, label: bool) -> list:
    seg = THRESHOLD.sub(lambda m: " " * len(m.group(0)), line)
    step = STEP_WORDS.search(seg)
    if step:
        start = max(start, step.end())
    elif not label and not FIGURES_ONLY.match(seg):
        return []                                     # prose: `pages 2 to 6`, `sections 205K and 209`
    return [(amount(m), bool(m.group("nil"))) for m in MONEY.finditer(seg, start) if amount(m) is not None]


def _figures(line: str, start: int, guide: int) -> list:
    seg = THRESHOLD.sub(lambda m: " " * len(m.group(0)), line[:guide])
    out = []
    for m in MONEY.finditer(seg, start):
        if m.start() < 40:
            continue                                  # the step number and the label's own text
        before = seg[:m.start()]
        if before.rstrip() and before.rstrip()[-1].isalpha() and len(before) - len(before.rstrip()) < 2:
            continue                                  # a figure follows a gap, never a word (a printed `0` is not one)
        if amount(m) is not None:
            out.append((amount(m), bool(m.group("nil"))))
    return out


def _cost(fig_line: int, label_line: int) -> float:
    d = fig_line - label_line
    return d if d >= 0 else 1.5 * -d                  # below or on its label's line before above it


SKIP_ZERO = 4.0          # leaving a printed zero unpaired
TO_STEP = 2.0            # giving a figure between the step sentence and the first part to the step cell
NO_TOTAL = 6.0           # leaving a total line with no figure while figures are paired


def _off(sec_name: str, got: dict) -> int:
    """How far, in cents, the parts paired fall from the total paired; 0 where there is nothing to sum."""
    if sec_name == "loans" or "total" not in got:
        return 0
    parts = [v for k, v in got.items() if k != "total"]
    return abs(reconcile.difference(round(sum(parts), 2), got["total"])) if parts else 0


def assign(sec_name: str, sec: Section) -> None:
    """Give the pool's figures to the labels in order, the arithmetic deciding (see the module's note). A figure on
    a label's own line goes to that label or nowhere."""
    labels, pool = sec.labels, sec.pool
    own = {line: l for l, (_, line) in enumerate(labels)}
    has_total = any(n == "total" for n, _ in labels)
    best = []                                         # ((cents off, cost), {label index: figure index}, [figure index to the step cell])
    tolerance = [1]                                   # to the cent; then, where nothing holds, ruling 66's

    def walk(fi, li, chosen, step, cost):
        if fi == len(pool):
            got = {labels[l][0]: pool[f][0] for l, f in chosen.items()}
            off = _off(sec_name, got)
            if off < tolerance[0]:
                if has_total and "total" not in got and any(v for v in got.values()):
                    cost += NO_TOTAL
                best.append(((off, round(cost, 3)), dict(chosen), list(step)))
            return
        fig, _, line, pre = pool[fi]
        if fig == 0.0:                                # a printed default under a typed figure (`0 $8,800.00`)
            walk(fi + 1, li, chosen, step, cost + SKIP_ZERO)
        if pre:
            walk(fi + 1, li, chosen, step + [fi], cost + TO_STEP)
        targets = [own[line]] if line in own else range(li, len(labels))
        for l in targets:
            if l < li:
                continue
            chosen[l] = fi
            walk(fi + 1, l + 1, chosen, step, cost + _cost(line, labels[l][1]))
            del chosen[l]

    if sum(1 for f in pool if f[0]) <= len(labels) + sum(1 for f in pool if f[3]) and len(pool) <= 12:
        walk(0, 0, {}, [], 0.0)
        if not best:
            tolerance[0] = reconcile.RECONCILE_TOLERANCE_CENTS
            walk(0, 0, {}, [], 0.0)
    if not best:                                      # no way holds: the nearest pairing, reported by problems()
        chosen, used = {}, set()
        for fi, (_, _, line, _) in enumerate(pool):
            options = [l for l in range(len(labels)) if l not in used and all(l > u for u in used)]
            if line in own:
                options = [l for l in options if l == own[line]]
            if not options:
                sec.unpaired.append(pool[fi][0])
                continue
            l = min(options, key=lambda l: _cost(line, labels[l][1]))
            chosen[l] = fi
            used.add(l)
        best = [((0, 0.0), chosen, [])]
    best.sort(key=lambda b: b[0])
    top = best[0]
    view = lambda b: ({labels[l][0]: pool[f][0] for l, f in b[1].items()}, sorted(pool[f][0] for f in b[2]))
    if any(view(r) != view(top) for r in best[1:] if r[0] == top[0]):
        sec.ambiguous = True
    for f in top[2]:
        sec.step.append(pool[f][0])
    for l, (name, _) in enumerate(labels):
        if l in top[1]:
            fig = pool[top[1][l]][0]
            if name == "total":
                sec.total = fig
            else:
                sec.parts[name] = fig
        elif name != "total":
            sec.blank.append(name)


STEP_SENTENCE = re.compile(r"Write\s+.?NIL.?\s+if\s+you\s+have\s+NO", re.I)


def read(text: str, layout: bool = True) -> Declaration:
    d = Declaration()
    lines = (text or "").splitlines() if layout else [TAG.sub("  ", l).replace("|", "  ") for l in (text or "").splitlines()]
    guide = guide_column(lines) if layout else 10 ** 6
    figs = (lambda line, start, lab: _figures(line, start, guide)) if layout else _plain_figures
    t = TITLE.search(" ".join(l.strip() for l in lines[:8]))
    if t:
        d.year = int(next(g for g in t.groups() if g))
    current, in_step = None, False
    for i, line in enumerate(lines):
        for k, rx in FIELD.items():
            attr = k if k != "party" else "party_label"
            m = rx.search(line[:70])
            if m and current is None and getattr(d, attr) is None:
                setattr(d, attr, _field(lines, i, m))
        if END.search(line):
            current = "signed"
            continue
        if current == "signed":
            m = SIGNED.search(line)
            if m and d.signed is None:
                d.signed = m.group(0).replace(" ", "")
            continue
        sec_name = next((n for n, rx in SECTIONS if rx.search(line)), None)
        if sec_name:
            current, in_step = sec_name, False
            d.sections[current] = Section()
            continue
        if current is None:
            continue
        sec = d.sections[current]
        lab, end = _label(line)
        if STEP_SENTENCE.search(line):
            in_step = True
        if (in_step or (not sec.labels and not sec.step_done)) and not lab:
            for f, nil in figs(line, 0, False):
                sec.step.append(f)
                sec.step_nil = sec.step_nil or nil
            if in_step and re.search(r"\bdeclare\b", line, re.I):
                in_step, sec.step_done = False, True  # the sentence ends at its "to declare"
            continue
        in_step = False
        if lab:
            sec.labels.append((lab, i))
        pre = sec.step_done and not sec.labels       # between the step sentence and the first part
        sec.pool += [(f, nil, i, pre) for f, nil in figs(line, end if lab else 0, bool(lab))]
    for name, sec in d.sections.items():
        assign(name, sec)
    return d
