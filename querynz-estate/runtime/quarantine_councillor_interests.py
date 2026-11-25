"""Quarantine the non-register rows from sources/councillor_interests (the
labels-are-contract correction committed 2026-11-21 for 2026-11-21, plus the
Gisborne 404-seed rows found 2026-11-25).

Rule: a row STAYS if it is a register document or the page that lists one
(the capture contract carries the listing page); it moves to
manifest-quarantine-2026-11-25.jsonl (bytes kept, rows annotated) otherwise.

Classes quarantined (the consumer's audit named the first three):
  - registered-premises / food / hairdressers / beauticians pages (Dunedin)
  - dog registration forms (application-to-register-a-dog, Deceased Dog Form)
  - creative-registration-of-interest (ara-toi)
  - do-it-online/apply/registration-of-interest (an application form)
  - road-name-register (a road naming register, not of interests)
  - secure.ePathway Register.aspx (the registrations portal)
  - Library Strategy Report, Taharoa Domain Reveg Plan (Kaipara)
  - GDC rows: 404 pages of a seeded address that never served a register
"""
import json
import os
import re

BASE = "/opt/data/querynz-estate/sources/councillor_interests"
MANIFEST = os.path.join(BASE, "manifest.jsonl")
QUAR = os.path.join(BASE, "manifest-quarantine-2026-11-25.jsonl")

SCOPED_HOSTS = ("gdc.govt.nz", "dunedin.govt.nz", "kaipara.govt.nz")
KEEP_RE = re.compile(
    r"(registers?-of-interest|pecuniary-interest"
    r"|KDC%20Members%20Interests|KDC Members Interests)", re.I)
KEEP_URLS = {"https://www.kaipara.govt.nz/council/Mayor-and-councillors-5"}


def row_urls(row):
    return [u.get("url", "") for u in row.get("urls", [])]


def classify(row, kept_urls):
    us = row_urls(row)
    if not any(any(h in u for h in SCOPED_HOSTS) for u in us):
        return True, None          # outside the audited sets: untouched
    for u in us:
        if "gdc.govt.nz" in u:
            return False, "404 page - the seeded Registers-of-Interest address has never served a register (measured 2026-11-25: site search 0 results for 'pecuniary'; not published online)"
        if u in KEEP_URLS:
            return True, None      # listing-parent page (not flagged by the audit)
        if KEEP_RE.search(u):
            return True, None
        # the page that LISTED a kept document rides with it (capture contract)
        for listed in row.get("listed_on") or []:
            if listed in kept_urls:
                return True, None
    return False, "non-register page mixed in by the word-matching walk (the labels-are-contract correction)"


def main():
    rows = [json.loads(l) for l in open(MANIFEST) if l.strip()]
    kept_urls = set()
    for r in rows:
        for u in row_urls(r):
            if KEEP_RE.search(u):
                kept_urls.add(u)
    keep, quar = [], []
    for r in rows:
        ok, reason = classify(r, kept_urls)
        if ok:
            keep.append(r)
        else:
            r["withdrawn"] = True
            r["withdrawn_reason"] = reason
            r["quarantined_at"] = "2026-11-25T23:10:00+00:00"
            quar.append(r)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, MANIFEST)
    with open(QUAR, "a", encoding="utf-8") as f:
        for r in quar:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("kept:", len(keep), "| quarantined:", len(quar), "(->", os.path.basename(QUAR) + ")")
    from collections import Counter
    c = Counter()
    for r in keep:
        for u in row_urls(r):
            c[u.split("/")[2]] += 1
    print("kept by host:", dict(c))
    for r in quar[:6]:
        print("  q:", row_urls(r)[0][:95])


if __name__ == "__main__":
    main()
