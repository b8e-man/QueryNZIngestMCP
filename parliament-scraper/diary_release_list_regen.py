#!/usr/bin/env python3
"""Regenerate diary_release_list.csv to reflect the true retention state.

- Preserves every existing row's core fields (pdf_url, file, ministers, months,
  meeting_rows) verbatim.
- Adds `release_sha256` (hash of the retained PDF bytes) to every row — the
  designated step-4 field.
- Corrects `retained`: a bare-name source_url that has a resolved_from ok entry
  flips error->ok (the step-2 flip); a not-fetched URL that now has a manifest
  ok entry flips to ok; anything still genuinely unresolved stays error/not-fetched
  with a `reason`.
- Appends one row per newly-landed release (manifest ok rows carrying
  `diary_month` — the Sep/Oct 2026 captures) with meeting_rows=0.

Idempotent. Append-only in spirit: existing rows are edited ONLY in `retained`,
`release_sha256` (and a `reason` when still failing).
"""
import csv
import json
import os
import re
import urllib.parse

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
CSV = os.path.join(DATA, "diary_release_list.csv")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")
LISTING = os.path.join(DATA, "diary_listing_2026.jsonl")

FIELDS = ["pdf_url", "file", "ministers", "months", "meeting_rows",
          "retained", "release_sha256", "reason"]


def load_manifest():
    by_url = {}          # url -> ok meta
    by_resolved = {}     # resolved_from name -> ok meta
    err = {}             # url -> error reason
    new_rows = []        # ok entries with diary_month (newly landed releases)
    for line in open(MANIFEST):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        u = m.get("url", "")
        if m.get("status") == "ok":
            meta = {"path": m.get("path", ""), "sha256": m.get("sha256", "")}
            by_url[u] = meta
            if m.get("resolved_from"):
                by_resolved[m["resolved_from"]] = meta
            if m.get("diary_month"):
                new_rows.append(m)
        elif m.get("status") == "error":
            err[u] = m.get("error", "")
    return by_url, by_resolved, err, new_rows


_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_STOP = set(_MONTHS + ["proactive", "ministerial", "diary", "summary", "release",
                       "final", "sept", "oct", "aug", "jan", "feb", "mar", "apr",
                       "jun", "jul", "nov", "dec", "minister", "prime"])


def _clean_name(s):
    words = []
    for w in s.split():
        w_clean = re.sub(r"_\d+$", "", w)
        wl = w_clean.lower().strip("_-()")
        if wl in _STOP or wl.isdigit() or re.fullmatch(r"20\d\d", wl):
            break
        words.append(w_clean)
    return " ".join(words).strip(" ,-\u2013\u2014")


def minister_from(text):
    """Best-effort minister label from a listing title; '' when generic."""
    t = re.sub(r"\.pdf$", "", text.strip(), flags=re.I)
    m = re.search(r"\b(?:Rt\s+)?Hon\.?\s+(.+?)(?=\s+-\s+|\s+\d{4}|$)", t)
    if m:
        n = _clean_name(m.group(1))
        if n and n.lower() not in ("prime", "prime minister"):
            return n
    m = re.match(r"^(.+?)\s+-\s+", t)
    if m:
        n = _clean_name(m.group(1))
        if n and n.lower() not in ("prime", "prime minister"):
            return n
    return ""


def main():
    by_url, by_resolved, err, new_rows = load_manifest()

    # preserve existing rows verbatim
    existing = []
    with open(CSV, newline="") as f:
        for r in csv.DictReader(f):
            existing.append(r)
    print(f"existing rows read: {len(existing)}")

    seen_urls = set(r["pdf_url"] for r in existing)
    out = []
    n_sha = n_ok = n_flip = 0
    still_err = still_nf = 0

    for r in existing:
        u = r["pdf_url"]
        meta = by_url.get(u) or by_resolved.get(u)
        if meta and meta.get("sha256"):
            r["release_sha256"] = meta["sha256"]
            n_sha += 1
        else:
            r["release_sha256"] = ""
        # retained: ok if we hold its bytes; else error (with reason) / not-fetched
        if meta and meta.get("sha256"):
            if r["retained"] != "ok":
                n_flip += 1
            r["retained"] = "ok"
            r["reason"] = ""
            n_ok += 1
        elif u in err:
            r["retained"] = "error"
            r["reason"] = err[u][:120]
            still_err += 1
        else:
            r["retained"] = "not-fetched"
            r["reason"] = ""
            still_nf += 1
        out.append(r)

    # append newly-landed releases (manifest ok + diary_month), not already present
    listing_text = {}
    if os.path.exists(LISTING):
        for line in open(LISTING):
            try:
                lr = json.loads(line)
                listing_text[lr["href"]] = lr.get("text", "")
            except ValueError:
                pass

    added = 0
    for m in new_rows:
        u = m["url"]
        if u in seen_urls:
            continue
        dm = m.get("diary_month", "")
        text = listing_text.get(u, "")
        out.append({
            "pdf_url": u,
            "file": urllib.parse.unquote(u.split("/")[-1])[:120],
            "ministers": minister_from(text),
            "months": dm,
            "meeting_rows": 0,
            "retained": "ok",
            "release_sha256": m.get("sha256", ""),
            "reason": "",
        })
        seen_urls.add(u)
        added += 1

    with open(CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    print(f"wrote {len(out)} rows "
          f"(sha256 filled: {n_sha}, retained ok: {n_ok}, flipped: {n_flip}, "
          f"still error: {still_err}, still not-fetched: {still_nf}, "
          f"new appended: {added})")


if __name__ == "__main__":
    main()
