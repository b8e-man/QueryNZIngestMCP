#!/usr/bin/env python3
"""Probe the /download/ and /api/data/{type}/{id} routes cracked from the
WASM assemblies, with real IDs from the corpora."""
import json
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(url, limit=2000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(limit)
            return r.status, r.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read(200)
    except Exception as e:
        return 0, "", str(e).encode()


def first_id(path, field="id"):
    for line in open(path):
        r = json.loads(line)
        if r.get(field):
            return r[field], r
    return None, None


scr_id, scr = first_id("/opt/data/parliament-scraper/data/api_queue/sc-reports.jsonl")
sop_id, sop = first_id("/opt/data/parliament-scraper/data/api_queue/SOPs.jsonl")
q_att, qrow = first_id("/opt/data/parliament-scraper/data/api_queue/questions.jsonl",
                       field="attachmentId")
q_id = qrow["id"] if qrow else None
pap_id, pap = first_id("/opt/data/parliament-scraper/data/api_queue/papers.jsonl")

print("ids:", scr_id, sop_id, q_att, q_id, pap_id)
print("sc-report title:", (scr or {}).get("title"))
print("sop title:", (sop or {}).get("title"))
print("paper title:", (pap or {}).get("title"))

tests = [
    f"https://bills.parliament.nz/download/selectcommitteereport/{scr_id}",
    f"https://bills.parliament.nz/api/data/selectcommitteereport/{scr_id}",
    f"https://bills.parliament.nz/download/sop/{sop_id}",
    f"https://bills.parliament.nz/download/amendmenttobill/{sop_id}",
    f"https://bills.parliament.nz/download/paper/{pap_id}",
    f"https://bills.parliament.nz/api/data/paper/{pap_id}",
    f"https://questions.parliament.nz/download/wq/{q_att}",
    f"https://questions.parliament.nz/download/writtenquestion/{q_id}",
    f"https://questions.parliament.nz/api/data/writtenquestion/{q_id}",
]
for u in tests:
    st, ct, body = get(u)
    print(f"\n{st} {ct[:40]} {u}")
    print("   ", body[:120])
