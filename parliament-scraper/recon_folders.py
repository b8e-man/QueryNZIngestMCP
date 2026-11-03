#!/usr/bin/env python3
"""Enumerate valid /download/{folder}/ values via the validation oracle,
find detail-API routes for each document type, and crack the WQ shape."""
import json
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DUMMY = "00000000-0000-0000-0000-000000000000"


def get(url, limit=500):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read(limit)
            return r.status, r.headers.get("Content-Type", ""), b
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read(limit)
    except Exception as e:
        return 0, "", str(e).encode()


print("=== FOLDER ENUM (bills.parliament.nz/download/{folder}/{dummy}) ===")
folders = ["sop", "sops", "amendmenttobill", "supplementaryorderpaper",
           "bill", "billdocument", "bills", "paper", "papers",
           "selectcommitteereport", "selectcommitteereports", "scr",
           "submission", "scsubmission", "evidence", "scevidence",
           "writtenquestion", "wq", "oralquestion", "oq", "question",
           "attachment", "document", "hansard", "orderpaper",
           "governmentresponse", "petition", "memberbill", "billstage"]
valid = []
for f in folders:
    st, ct, b = get(f"https://bills.parliament.nz/download/{f}/{DUMMY}")
    body = b.decode(errors="replace")
    if "not valid" in body:
        verdict = "INVALID-folder"
    elif st == 404:
        verdict = "folder-ok (id 404)"
        valid.append(f)
    elif st == 200:
        verdict = "200 ??"
        valid.append(f)
    else:
        verdict = f"{st} {body[:80]}"
    print(f"  {f:28} {verdict}")
print("VALID FOLDERS:", valid)

print("\n=== QUESTIONS FOLDER ENUM ===")
for f in ["wq", "writtenquestion", "attachment", "document", "question"]:
    st, ct, b = get(f"https://questions.parliament.nz/download/{f}/{DUMMY}")
    body = b.decode(errors="replace")
    print(f"  {f:20} {st} {body[:100]}")

print("\n=== DETAIL API ROUTES (SOP + evidence) ===")
sop_id = json.loads(open(
    "/opt/data/parliament-scraper/data/api_queue/SOPs.jsonl").readline())["id"]
for t in ("sop", "amendmenttobill", "billdocument", "sops",
          "scevidence", "submission", "scsubmission"):
    st, ct, b = get(f"https://bills.parliament.nz/api/data/{t}/{sop_id}", 300)
    print(f"  api/data/{t:20} {st} {b[:120]}")
