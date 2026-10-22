#!/usr/bin/env python3
"""Wayback snapshot download (ops scratch — not the ingest tool).

Download ONE document's best snapshot + optional siblings. Live HTML pages are
Radware-challenged from every tested path (VPS, proxies); Wayback holds REAL
HTML for parliament (unlike beehive). The `id_` flag serves the raw original
(200 or 302 follow), no Wayback rewriting — raw capture preserved verbatim.

  python3 scratch_ops.py download URL [TS ...] [DIR]

Writes HTML to DIR/downloaded.jsonl. Also self-checks the ingest tool:
  python3 scratch_ops.py check  -> runs ingest_wayback_docs.py --self-test
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
INGEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest_wayback_docs.py")


def fetch(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read(), r.status
        except Exception as e:
            if i == tries - 1:
                return None, str(e)[:80]
            time.sleep(3)


def download(url, ts_list, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out_f = os.path.join(out_dir, "downloaded.jsonl")
    with open(out_f, "a") as out:
        for ts in ts_list:
            snap = f"https://web.archive.org/web/{ts}id_/{url}"
            body, status = fetch(snap)
            rec = {"url": url, "ts": ts, "snap_url": snap,
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if body:
                rec.update(status="ok", bytes=len(body),
                           sha256=hashlib.sha256(body).hexdigest(),
                           looks_html=b"<html" in body[:2000].lower())
                print(f"OK {ts} {len(body)}B html={rec['looks_html']}")
            else:
                rec.update(status=f"failed: {status}")
                print(f"FAIL {ts}: {status}")
            out.write(json.dumps(rec) + "\n")
            time.sleep(1.2)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "check":
        rc = os.system(f"python3 {INGEST} --self-test")
        sys.exit(0 if rc == 0 else 1)
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    rest = sys.argv[2:]
    out_dir = os.path.join(os.path.dirname(INGEST), "data", "wayback_docs")
    ts_list = [a for a in rest if a.isdigit()]
    if rest and not rest[-1].isdigit():
        out_dir = rest[-1]
        ts_list = [a for a in rest[:-1] if a.isdigit()]
    if not ts_list:
        ts_list = ["2025"]
    download(url, ts_list, out_dir)
