"""Measure a change on every return, replay only (plan 4.1: a change to the
reading is measured on all the landed returns, never on the sample). Each
in-window return is read from the old folder, read-only; stored page
readings are replayed, never asked for, and any reading the run stores goes
to a folder of the caller's, never the shared reader store. No database.

    python -m registers.candidate_returns.replay run OUT.json [--store DIR]
    python -m registers.candidate_returns.replay compare BEFORE.json AFTER.json
    python -m registers.candidate_returns.replay shape SHA_PREFIX [PAGE ...]
    python -m registers.candidate_returns.replay rereads RUN.json

`run` writes one entry per document (its names, placement, status, the
declared figures, Part A's amounts and pages (never a donor's name), the
set-aside lines) and prints the catch log's
reconciliation and the outside check (check.py). `compare` prints every
document whose figures, route or set-aside stages changed. `shape` prints a
return's pages as the reading sees them (text layer, or the stored page
reading) with every word that is not the form's own, and every figure that
is not money, a date or a row number, turned to `x`: so a session can look
at a page's layout without a name or an address entering it (hard limit 11).
`rereads` lists, from a run, every return a page reading is owed for (ruling
62: the page reader is not queued in bulk until the build is done, so the
queue is this list): stage `read` (no stored reading of the declaration
page), stage `declaration` where the page is a scanner's text layer set aside
for want of its printed total, and stage `part-a` (Part A on image pages with
no stored reading),
each with its hash and pages, one line each, and the count of pages.
"""
import hashlib
import json
import os
import re
import sys

from support import reader as rd
from support.docread import pages
from registers.candidate_returns import capture, check, load, read

#: what `shape` leaves readable: money, dates, Yes/No, part labels, page marks, a row number at the margin
KEEP = re.compile(r"\$?\s*\d[\d,]*\.\d{2}|\d{1,2}/\d{1,2}/?\d{2,4}|\b(?:YES|NO|Yes|No|NIL|Nil)\b|PART\s+[A-H]\b|"
                  r"Page:?\s*\d+|^\s{0,3}\d{1,3}(?=\s|$)")
#: the form's own words, left readable
FORM_WORDS = set("""part a b c d e f g h donations donation donor donors donor's donor’s name names street address total
for of more than the and received date dates from another person yes no enter including gst page schedule attached
list party loans loan aggregated contributions contribution amount amounts nil lender lenders return candidate
candidates candidate's candidate’s election expenses expense electorate contested advertising advertisements shared
with other only overseas anonymous declare declaration step total complete if you have any to on in is a an by or
general dd/mm/yyyy does contain write""".split())


class Overlay(rd.Store):
    """The shared reader store for reading; `root` for writing."""

    def __init__(self, root: str):
        super().__init__(root)
        self.shared = rd.Store()

    def has(self, key):
        return super().has(key) or self.shared.has(key)

    def get(self, key):
        return super().get(key) if super().has(key) else self.shared.get(key)


def landed_from_old(files=None) -> dict:
    out = {}
    for path in files or capture.return_files():
        out.setdefault(_sha_of(path), []).append(path)
    return out


_SHA_CACHE = {}


def _sha_of(path: str) -> str:
    if path not in _SHA_CACHE:
        with open(path, "rb") as f:
            _SHA_CACHE[path] = hashlib.sha256(f.read()).hexdigest()
    return _SHA_CACHE[path]


def run(out_path: str, store_dir: str) -> dict:
    landed = landed_from_old()
    st = load.statements()

    def data_of(sha):
        with open(landed[sha][0], "rb") as f:
            return f.read()

    b = load.build(landed, st, Overlay(store_dir), data_of, loaded_at="replay")
    rows = {r["document"]: r for r in b.returns}
    out = {}
    for f in b.files:
        r = rows.get(f["document"])
        res = b.results[f["document"]]
        out[f["document"]] = {
            "names": f["names"], "placed_by": f["placed_by"], "status": f["status"], "year": f["year"],
            "route": res.route, "page": r["page"] if r else None,
            "row": {k: r[k] for k in ("donations", "expenses", "loans", "donations_check", "expenses_check",
                                      "loans_check", "read_from", "donors_check", "issue")} if r else None,
            "donors": [[d["amount"], d["page"]] for d in res.donors],
            "donors_issue": res.donors[0].get("issue") if res.donors else None,
            "set_aside": [(s, why) for d, s, why in b.set_aside if d == f["document"]]}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(load.counts(b))
    res = check.compare(b.files, b.returns, b.commission)
    print("outside check:", check.summary(res))
    print("issue rows (ruling 66):", check.issues(b.returns, b.donors))
    return out


def compare(a: dict, b: dict) -> list:
    out = []
    for s in sorted(set(a) | set(b)):
        x, y = a.get(s), b.get(s)
        if x is None or y is None:
            out.append(f"{s[:12]}: only in {'after' if x is None else 'before'}")
            continue
        if x.get("donors") != y.get("donors"):
            out.append(f"{s[:12]} {y['year']}: Part A rows {len(x.get('donors') or [])} -> {len(y.get('donors') or [])}")
        if x.get("donors_issue") != y.get("donors_issue"):
            out.append(f"{s[:12]} {y['year']}: Part A issue {x.get('donors_issue')} -> {y.get('donors_issue')}")
        if x["row"] != y["row"]:
            out.append(f"{s[:12]} {y['year']}: {x['row']} -> {y['row']}")
        if [t for t, _ in x["set_aside"]] != [t for t, _ in y["set_aside"]]:
            out.append(f"{s[:12]} {y['year']}: set aside {[t for t, _ in x['set_aside']]} -> {[t for t, _ in y['set_aside']]}")
        if x["status"] != y["status"] or x["placed_by"] != y["placed_by"]:
            out.append(f"{s[:12]} {y['year']}: {x['placed_by']}/{x['status']} -> {y['placed_by']}/{y['status']}")
    return out


READ_PAGES = re.compile(r"no stored page reading \(pages ([\d, ]+)\): ask for a re-read")
SCANNER_PAGE = re.compile(r"^page (\d+):")
PART_A_PAGES = re.compile(re.escape(read.REREAD) + r" [0-9a-f]{64} pages ([\d, ]+)")


def rereads(d: dict) -> list:
    """[(sha256, year, stage, [pages])] for every return a page reading is owed for, in hash order."""
    out = []
    for sha, v in sorted(d.items()):
        for stage, why in v["set_aside"]:
            m = (READ_PAGES if stage == "read" else PART_A_PAGES if stage == "part-a" else
                 SCANNER_PAGE if stage == "declaration" and read.SCANNER in why else None)
            m = m.search(why) if m else None
            if m:
                out.append((sha, v["year"], stage, [int(p) for p in re.findall(r"\d+", m.group(1))]))
    return out


def shape_line(line: str) -> str:
    out, last = [], 0
    for m in KEEP.finditer(line):
        out += [re.sub(r"\S", "x", line[last:m.start()]), m.group(0)]
        last = m.end()
    out.append(re.sub(r"\S", "x", line[last:]))
    res = list("".join(out))
    for w in re.finditer(r"\S+", line):
        if w.group(0).lower().strip("(),.:;‘’'") in FORM_WORDS:
            res[w.start():w.end()] = w.group(0)
    return "".join(res)


def shape(prefix: str, want=(), store_dir: str = None) -> None:
    store = Overlay(store_dir) if store_dir else rd.Store()
    for path in capture.return_files():
        sha = _sha_of(path)
        if not sha.startswith(prefix):
            continue
        with open(path, "rb") as f:
            texts = pages.text_pages(f.read())
        for p in want or sorted(texts):
            t, src = texts.get(p) or "", "text"
            if p in pages.thin_pages(texts):
                r = read.stored_page(store, sha, p)
                t, src = (r.text, "pixels") if r else ("", "no reading")
            print(f"===== {sha[:12]} page {p} of {len(texts)} ({src})")
            for line in t.splitlines():
                if line.strip():
                    print(shape_line(line))
        return


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["run"] and len(argv) >= 2:
        store = argv[argv.index("--store") + 1] if "--store" in argv else os.path.join(os.path.dirname(os.path.abspath(argv[1])), "store")
        d = run(argv[1], store)
        print(f"{len(d)} documents")
        return 0
    if argv[:1] == ["compare"] and len(argv) == 3:
        a, b = (json.load(open(p, encoding="utf-8")) for p in argv[1:])
        for line in compare(a, b):
            print("  " + line)
        return 0
    if argv[:1] == ["rereads"] and len(argv) == 2:
        got = rereads(json.load(open(argv[1], encoding="utf-8")))
        for sha, year, stage, pages_ in got:
            print(f"{sha} {year} {stage} pages {','.join(map(str, pages_))}")
        print(f"{len(got)} returns, {sum(len(p) for _, _, _, p in got)} pages")
        return 0
    if argv[:1] == ["shape"] and len(argv) >= 2:
        shape(argv[1], [int(p) for p in argv[2:]])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
