"""The scanned declaration's own printed total, from a page reading.

The s 210C form prints, under "Total donation and date received", a
"Total amount" box and, beside it, a grid of the gifts that make it up.
The Commission prints the same amount in its table, so the two are two
statements by the Commission of one figure: the comparison costs nothing
and is the only check that does not depend on a reading being plausible
(old lesson, 8-reading-documents.md:638). The form's own boilerplate quotes
$20,000 in several places, so a figure is taken only from the lines just
under the label, never from anywhere on the page.

The box can hold more than one figure: a total struck through by hand and
its correction written beside it. A reading cannot see a strike, so every
figure in the box is kept (`figures`) and the check, not the reader,
decides (read.form_check).

Where the page reading holds no total, the scan's own text layer is read
the same way (`text_layer`): a form filled in on a computer carries its
typed values there. Measured 20 October 2026 on the 50 linked scans with
no total read: the page reading dropped the whole "Total amount" box on 49
(handwritten or typed alike), and 23 of those carry the figure in the text
layer; one was a bare "$20,000" this module took for boilerplate.

    total(pages) -> Total(amount, page, why, figures)   pages: {page: text}
    stored(sha256, profile, model)                      the held page readings of one scan
    text_layer(data)                                    {page: text} of the pages with a text layer

Readings are replayed, never made here: the fast tier calls no model. A
stored reading is taken under its own stamp (reader, settings, profile
version), whoever made it; step 3's trial made the first thirty.
"""
import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass

from support import reader as rd
from support.docread import pages as textpages
from registers.disclosures.listing import money

PROFILE = "ec-donation-disclosure-20k"
MODEL = "glm-ocr"

LABEL = re.compile(r"total\s+donation\s+and\s+date\s+received|total\s+amount", re.I)
BOILERPLATE = re.compile(r"exceed|more than|over \$|threshold|aggregat|\$20,000\b(?!\.\d)", re.I)
FIGURE_ONLY = re.compile(r"^[\s$]*[\d,]+(?:\.\d+)?[\s\-–—]*$")   # "$20,000" alone in the box is a figure, not boilerplate
NEXT_LABEL = re.compile(r"date\s+received|details\s+of|amount\s+date|contributions?\b", re.I)
BARE_MIN = 100                # a bare number under the label, no "$" (the form prints it outside the box), from $100
MONEY_ALL = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
WINDOW = 4
PICTURE_SHARE = 0.8


@dataclass
class Total:
    amount: float = None
    page: int = None
    why: str = ""
    figures: tuple = ()           # every figure in the box, in order; the first is `amount`


def _figures(line: str) -> list:
    out = []
    for m in MONEY_ALL.finditer(line):
        v = float(m.group(1).replace(",", "") or 0)
        if v > 0:
            out.append(v)
    if not out and FIGURE_ONLY.match(line):
        v = money("$" + line.strip(" $-–—"))
        if v and v >= BARE_MIN:
            out.append(v)
    return out


def _box(lines: list, i: int) -> list:
    """The figures under the label at line i: the label's own line and the
    WINDOW lines after it, stopping at the next label of the form (the
    grid of gifts below is not the total) and at the first blank line once
    a figure is in hand."""
    got = []
    for j, ln in enumerate(lines[i:i + 1 + WINDOW]):
        if got and not ln.strip():
            break
        if j and NEXT_LABEL.search(ln) and not LABEL.search(ln):
            break
        if BOILERPLATE.search(ln) and not FIGURE_ONLY.match(ln):
            continue
        got += _figures(LABEL.split(ln)[-1] if j == 0 else ln)
    return got


def total(pages: dict) -> Total:
    for page in sorted(pages):
        lines = (pages[page] or "").splitlines()
        for i, ln in enumerate(lines):
            if not LABEL.search(ln):
                continue
            got = _box(lines, i)
            if got:
                return Total(got[0], page, "", tuple(got))
    return Total(None, None, "no figure under the form's total label")


def text_layer(data: bytes) -> dict:
    """{page: text} of the scan's own text layer, on the pages a computer
    typed: a page too thin to be a layer is left out, and so is a page
    under a full-page picture, whose layer is a scanner's own OCR (measured
    20 October 2026: on such pages it gave the box's figure 18 times in 24
    and "$9", "$50" or "$77,017" the rest; on typed pages, 126 in 126).
    {} for a raster or a scan with none."""
    if not textpages.is_pdf(data):
        return {}
    pictures = picture_pages(data)
    return {p: t for p, t in textpages.text_pages(data).items() if not textpages.is_thin(t) and p not in pictures}


def picture_pages(data: bytes) -> set:
    """The pages that carry an image at least PICTURE_SHARE of the page's
    width: a scan, or a photograph of the form (pdfimages -list)."""
    try:
        info = subprocess.run(["pdfinfo", "-"], input=data, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        listing = subprocess.run(["pdfimages", "-list", "-"], input=data, capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return set()
    m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
    width = float(m.group(1)) / 72 if m else 8.27
    out = set()
    for ln in listing.splitlines()[2:]:
        f = ln.split()
        try:
            if f[2] == "image" and float(f[12]) > 0 and int(f[3]) / float(f[12]) >= PICTURE_SHARE * width:
                out.add(int(f[0]))
        except (IndexError, ValueError):
            continue
    return out


def stored(sha256: str, profile: str = PROFILE, model: str = MODEL, root: str = None) -> list:
    """[Reading] for every page of one scan the store holds under `profile`
    (any version) and `model`, one per page: the newest profile version,
    then the newest reading. [] when none is held."""
    folder = os.path.join(root or rd.STORE, sha256[:2], sha256)
    best = {}
    for path in glob.glob(os.path.join(folder, f"p*__{profile}@*__{model}__*.json")):
        with open(path, encoding="utf-8") as f:
            r = rd.Reading(**json.load(f))
        have = best.get(r.page)
        if have is None or (r.profile_version, r.made_at) > (have.profile_version, have.made_at):
            best[r.page] = r
    return [best[p] for p in sorted(best)]
