"""How this lane's documents arrive: case 1 of plan 1.10. The old estate
holds the Commission's candidate returns as captured files under the live
old folder's `var/staging/ec-donations/` (its README):

- `archive/candidate-returns__<year>__<party or electorate>__<file>.pdf`,
  the Internet Archive's replay of the Commission's asset tree;
- `archive/Uploads__<file>.pdf`, the amended returns the Commission
  republished under `/assets/Uploads/` (lesson: an amended candidate return
  has a different file-name pattern: `Kilari-S-Manurewa-amended-070324`);
- `residue/candidate_returns_2020/<file>.pdf`, Arthur's browser download.

And the Commission's own statements about them, which are documents too:
the per-election listing pages the old estate's headed browser kept under
`index/live-…candidate-…start-N.html`, and the summary spreadsheets
(`2020-Candidate-Returns.xlsx`; for 2023 the dated
`2023-candidate-returns-updated-DDMMYYYY` versions, csv and xlsx).

Every file is copied by hash, read-only, through the one landing wrapper;
the lane never writes under the old folder and fetches nothing.

Scope: the 2020 and 2023 general elections and the 2022 Tauranga
by-election, the elections inside the window (ruling 347: 2019 onward).
The 2011, 2014 and 2017 returns are held and left where they are.

    return_files()        the old paths of every in-window return, sorted
    listing_files()       {year: [old path of each listing page]}
    spreadsheet_files()   {year: [old path of each summary spreadsheet, oldest version first]}
    old_index()           sha256 → old path, for finding a sample item (hashes every file)
    manifest_index()      sha256 → [old path], from the old folder's two MANIFEST.jsonl (quick; verified on landing)
    held_name(path)       the file's own name as the Commission published it (the archive prefix cut)
    copy_all(conn)        land every return: [(DocumentRef, old path, new)]
    copy_one(path, conn)  land one file (a listing page, a spreadsheet)
"""
import os
import re

from support.docstore import sha256_file
from support.docstore.landing import copy_from_old

OLD_LIVE = os.environ.get("QV4_OLD_LIVE") or "/home/user/Git Repos/QueryNZ_V3"
FOLDER = os.path.join(OLD_LIVE, "var", "staging", "ec-donations")
SOURCE = "candidate_returns"
YEARS = (2020, 2022, 2023)                       # ruling 347: the elections from 2019
ARCHIVE = re.compile(r"^(?:candidate-returns__(?P<year>\d{4})__[^_].*|Uploads__.*)\.pdf$", re.I)
RESIDUE = os.path.join("residue", "candidate_returns_2020")
LISTING = {2020: re.compile(r"^live-.*expenses-and-donations-for-the-2020-general-election-year-2020-start-\d+\.html$"),
           2023: re.compile(r"^live-.*2023-general-election-candidate-expenses-donations-and-loans-year-2023-start-\d+\.html$")}
SPREADSHEET = {2020: re.compile(r"^(?:candidate-returns__2020__Amended__)?2020-Candidate-Returns\.xlsx$"),
               2023: re.compile(r"^pagecomponent-file-files__2023-candidate-returns-updated-(\d{2})(\d{2})(\d{4})(?:-v\d)?\.(csv|xlsx)$")}


def held_name(path: str) -> str:
    """The name the Commission published the file under: the archive's
    `<tree>__<year>__<folder>__` prefix cut."""
    return os.path.basename(path).split("__")[-1]


def return_files(folder: str = None) -> list:
    folder = folder or FOLDER
    out = []
    archive = os.path.join(folder, "archive")
    if os.path.isdir(archive):
        for f in os.listdir(archive):
            m = ARCHIVE.match(f)
            if m and (m.group("year") is None or int(m.group("year")) in YEARS):
                out.append(os.path.join(archive, f))
    residue = os.path.join(folder, RESIDUE)
    if os.path.isdir(residue):
        out += [os.path.join(residue, f) for f in os.listdir(residue) if f.lower().endswith(".pdf")]
    return sorted(out)


def listing_files(folder: str = None) -> dict:
    index = os.path.join(folder or FOLDER, "index")
    names = sorted(os.listdir(index)) if os.path.isdir(index) else []
    return {y: [os.path.join(index, f) for f in names if rx.match(f)] for y, rx in LISTING.items()}


def _version(name: str) -> tuple:
    m = SPREADSHEET[2023].match(name)
    return (m.group(3), m.group(2), m.group(1), name) if m else ("", "", "", name)


def spreadsheet_files(folder: str = None) -> dict:
    folder = folder or FOLDER
    out = {}
    for sub in ("archive", RESIDUE):
        d = os.path.join(folder, sub)
        for f in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
            for y, rx in SPREADSHEET.items():
                if rx.match(f):
                    out.setdefault(y, []).append(os.path.join(d, f))
    return {y: sorted(ps, key=lambda p: _version(os.path.basename(p))) for y, ps in out.items()}


def old_index(folder: str = None) -> dict:
    return {sha256_file(p): p for p in return_files(folder)}


def manifest_index(folder: str = None) -> dict:
    """The old folder's own record of each file's hash (`archive/MANIFEST.jsonl`, `residue/MANIFEST.jsonl`), for
    the in-window returns only. Quick, and only as good as the manifest: `copy_from_old` hashes the bytes it lands,
    and a caller compares."""
    import json
    folder = folder or FOLDER
    wanted = {os.path.normpath(p) for p in return_files(folder)}
    out = {}
    for sub in ("archive", "residue"):
        path = os.path.join(folder, sub, "MANIFEST.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not e.get("sha256") or not e.get("file"):
                    continue
                p = os.path.normpath(os.path.join(folder, sub, e["file"]))
                if p in wanted:
                    out.setdefault(e["sha256"], []).append(p)
    return out


def copy_one(path: str, conn):
    ref, _ = copy_from_old(path, SOURCE, conn)
    return ref


def copy_all(conn, folder: str = None, log=None) -> list:
    out = []
    for path in return_files(folder):
        ref, new = copy_from_old(path, SOURCE, conn)
        out.append((ref, path, new))
        if log:
            log(f"candidate_returns: {'landed' if new else 'held'} {ref.sha256[:12]} {os.path.basename(path)}")
    return out
