"""How this lane's documents arrive: case 1 of plan 1.10. The old estate's
`ec-disclosures` job (a headed browser, rulings 242/243) is the only
fetcher until the public site is switched; this lane fetches nothing. It
copies, by hash, read-only, through the one landing wrapper, from the live
old folder's `var/staging/ec-donations/`:

  index/live-…-donations-exceeding-20000.html             the Commission's table, 2023 onward
  index/live-…-donations-exceeding-20000-donations-exceeding-30000.html
                                                           its table for 2008 to 2022
  residue/donations_20k/*                                  the scanned declarations the job downloaded
  archive/2026-20k+-donations__*                           the same tree from the archive replay

The job overwrites each listing at every firing, so each landing is a new
document only when the Commission's page changed (a document is its bytes).

Two kinds of file in those folders are not documents and are never landed:
the archive replay's challenge shells (an HTML page of a few hundred bytes
under a `.pdf` name) and its cuts at exactly 1 MiB. Each is a catch-log
line. `pageread/` and `index/*.links` beside them are derived output.

    candidate_files()       [(kind, old path)], sorted
    is_real_document(path)  '' or why not
    copy_all(conn)          [(kind, DocumentRef, old path, new)] and [(old path, why)] set aside
"""
import os
import re

from support.docstore.landing import copy_from_old

OLD_LIVE = os.environ.get("QV4_OLD_LIVE") or "/home/user/Git Repos/QueryNZ_V3"
FOLDER = os.path.join(OLD_LIVE, "var", "staging", "ec-donations")
LISTINGS = (
    "live-ns-nz-democracy-in-nz-political-parties-in-new-zealand-donations-exceeding-20000.html",
    "live-tical-parties-in-new-zealand-donations-exceeding-20000-donations-exceeding-30000.html",
)
ARCHIVE = re.compile(r"^2026-20k\+-donations__.+\.(pdf|jpe?g|png)$", re.I)
DECLARATION = re.compile(r"\.(pdf|jpe?g|png)$", re.I)
TRUNCATED_AT = 1_048_576
SOURCE = "disclosures"


def candidate_files(folder: str = None) -> list:
    folder = folder or FOLDER
    out = [("listing", os.path.join(folder, "index", n)) for n in LISTINGS
           if os.path.exists(os.path.join(folder, "index", n))]
    archive = os.path.join(folder, "archive")
    if os.path.isdir(archive):
        out += [("declaration", os.path.join(archive, f)) for f in os.listdir(archive) if ARCHIVE.match(f)]
    residue = os.path.join(folder, "residue", "donations_20k")
    if os.path.isdir(residue):
        out += [("declaration", os.path.join(residue, f)) for f in os.listdir(residue) if DECLARATION.search(f)]
    return sorted(out)


def is_real_document(path: str) -> str:
    """'' when the file is a document; else why not."""
    size = os.path.getsize(path)
    if size == TRUNCATED_AT:
        return "cut at exactly 1 MiB by the archive replay"
    if size < 2000:
        with open(path, "rb") as f:
            head = f.read(300).lower()
        if b"<html" in head or b"incapsula" in head:
            return "a challenge page saved under a document's name"
    return ""


def commission_name(path: str) -> str:
    """The Commission's own file name: the archive's `<tree>__` prefix off."""
    return os.path.basename(path).split("__", 1)[-1]


def copy_all(conn, folder: str = None, log=None) -> tuple:
    landed, aside = [], []
    for kind, path in candidate_files(folder):
        why = is_real_document(path)
        if why:
            aside.append((path, why))
            continue
        ref, new = copy_from_old(path, SOURCE, conn)
        landed.append((kind, ref, path, new))
        if log:
            log(f"disclosures: {'landed' if new else 'held'} {kind} {ref.sha256[:12]}")
    return landed, aside
