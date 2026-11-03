#!/usr/bin/env python3
"""Crack the attachment download URL pattern:
1. Fetch blazor.boot.json from questions.parliament.nz → assembly list
2. String-hunt the main WASM .dll for API/media routes
3. Probe candidate attachment URL patterns
"""
import re
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

ATT_ID = "0bd63f61-5147-4afc-961f-2dbafb0ef782"
ATT_NAME = "WQ_41284_2026.pdf"


def get(url, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(limit or 50_000_000)
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000), {}
    except Exception as e:
        return 0, str(e).encode(), {}


for base in ("https://questions.parliament.nz", "https://bills.parliament.nz"):
    for path in ("/blazor.boot.json", "/_framework/blazor.boot.json"):
        st, body, _ = get(base + path, 500_000)
        print(base + path, "->", st, len(body))
        if st == 200 and b"assembly" in body[:2000].lower() or st == 200 and b".dll" in body:
            print(body[:1500].decode(errors="replace"))
            break

# candidate attachment URL patterns
cands = [
    f"https://questions.parliament.nz/api/data/attachment/{ATT_ID}",
    f"https://questions.parliament.nz/api/data/attachments/{ATT_ID}",
    f"https://questions.parliament.nz/api/attachment/{ATT_ID}/{ATT_NAME}",
    f"https://questions.parliament.nz/attachments/{ATT_ID}/{ATT_NAME}",
    f"https://questions.parliament.nz/media/{ATT_ID}/{ATT_NAME}",
    f"https://www.parliament.nz/media/{ATT_ID}/{ATT_NAME}",
    f"https://www.parliament.nz/api/attachment/{ATT_ID}",
    f"https://questions.parliament.nz/api/data/download/{ATT_ID}",
    f"https://questions.parliament.nz/api/download/{ATT_ID}",
]
for u in cands:
    st, body, hdrs = get(u, 300)
    ct = hdrs.get("Content-Type", "")
    head = body[:80]
    print(f"{st} {ct[:30]} {u}")
    if st == 200 and ("pdf" in ct or body[:4] == b"%PDF"):
        print("   >>> PDF HIT:", head)
