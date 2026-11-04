"""Party names as the disclosures lane keys them: (party, basis)."""
import re


def party_name(label: str):
    s = re.sub(r"\s+", " ", (label or "").strip())
    if not s:
        return "", "empty"
    return s, "label"
