"""The document store's contract (plan 1.9; docs/contracts/document-store.md).
Step 1.10 builds the landing wrapper on it.

A document is its bytes. It is keyed by the sha256 of those bytes; its
names (the file name it arrived under, the URL, the folder) are attributes,
of which it may have several. The old estate held 424 returns under two
names each, and renamed rows broke every citation.

For a web page the bytes change on every fetch (a nonce, a timestamp, an
advert), so a page has two hashes: `sha256` of the bytes as fetched, and
`content_sha256` of its canonical text, which is what says "the same page
again". The canonical text is the page's readable text: tags, scripts,
styles, comments and whitespace runs removed. It is a fingerprint for
sameness, not the reading of the page; the reader reads the bytes.

This module holds the shape and the hashing. Landing (writing bytes to the
store and the row to the `docs` schema) is 1.10's.
"""
import datetime as dt
import hashlib
import html
import re
from dataclasses import dataclass, field

_SCRIPT = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
KINDS = ("pdf", "image", "spreadsheet", "web-page", "text", "csv", "other")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_text(page: str) -> str:
    """The readable text of a web page: scripts, styles, comments and tags
    out, entities decoded, whitespace collapsed."""
    s = _SCRIPT.sub(" ", page or "")
    s = _COMMENT.sub(" ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def content_sha256(page_bytes: bytes, encoding: str = "utf-8") -> str:
    """The sameness hash of a web page."""
    return sha256_bytes(canonical_text(page_bytes.decode(encoding, errors="replace")).encode("utf-8"))


def kind_of(name: str, content_type: str = "") -> str:
    n = (name or "").lower()
    ct = (content_type or "").lower()
    if n.endswith(".pdf") or "pdf" in ct:
        return "pdf"
    if n.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp")) or ct.startswith("image/"):
        return "image"
    if n.endswith((".xlsx", ".xls", ".ods")) or "spreadsheet" in ct or "excel" in ct:
        return "spreadsheet"
    if n.endswith(".csv") or "csv" in ct:
        return "csv"
    if n.endswith((".html", ".htm")) or "html" in ct:
        return "web-page"
    if n.endswith((".txt", ".md")) or ct.startswith("text/"):
        return "text"
    return "other"


@dataclass(frozen=True)
class DocumentRef:
    """What every row cites and every reading is keyed by."""
    sha256: str
    size: int
    kind: str
    names: tuple = field(default_factory=tuple)       # file names and URLs it arrived under
    source: str = ""                                   # the lane or the old folder it came from
    fetched_at: str = ""                               # ISO time of the capture
    content_sha256: str = ""                           # web pages only: the sameness hash

    def __post_init__(self):
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be 64 hex characters")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if self.size < 0:
            raise ValueError("size")


def describe(data: bytes, name: str = "", content_type: str = "", source: str = "", fetched_at: str = None) -> DocumentRef:
    """A DocumentRef for bytes in hand; a web page also gets its content hash."""
    kind = kind_of(name, content_type)
    return DocumentRef(
        sha256=sha256_bytes(data), size=len(data), kind=kind, names=(name,) if name else (), source=source,
        fetched_at=fetched_at or dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        content_sha256=content_sha256(data) if kind == "web-page" else "")
