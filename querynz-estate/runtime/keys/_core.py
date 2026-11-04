"""Entity-key helpers, rebuilt for capture on this box.

The estate's `keys` package (its register-keying layer) was not part of the
handover; the lanes' read modules import these names and some captures call
the readers for listing shapes. These implementations keep the capture walks
running; when the estate reads the corpora its own keys module governs its
tables. Key formats here are stable but not canonical.
"""
import re

_STRIP = re.compile(r"[^a-z0-9]+")

_ORG_MARKERS = (
    "ltd", "limited", "inc", "incorporated", "trust", "board", "association",
    "society", "council", "committee", "cooperative", "co-operative", "charity",
    "foundation", "group", "holdings", "partners", "partnership", "company",
    "commission", "authority", "institute", "union", "club", "church", "school",
    "government", "department", "ministry", "agency", "public", "royal",
    "society", "association", "nz", "new zealand")


def _slug(s: str) -> str:
    return _STRIP.sub("-", (s or "").lower()).strip("-")


def is_organisation(name: str) -> bool:
    s = (name or "").lower()
    if not s.strip():
        return False
    if re.search(r"\b(ltd|limited|inc|trust|board|society|association|council|"
                 r"committee|co-?operative|charity|foundation|company|"
                 r"commission|authority|department|ministry|agency|"
                 r"incorporated|partnership|holdings)\b", s):
        return True
    words = s.split()
    if len(words) >= 3 and not re.search(r"\b(mr|mrs|ms|dr|miss)\b", s):
        return False
    return False


def organisation_key(name: str) -> str:
    return _slug(name)


def person_key(name: str) -> str:
    return _slug(name)


def charity_number(v) -> str:
    s = re.sub(r"[^0-9]", "", str(v or ""))
    return s


def nzbn(v):
    s = re.sub(r"[^0-9]", "", str(v or ""))
    return s if len(s) == 13 else None


def clean_address(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def filed_date(v):
    s = str(v or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        return None
    return s
