#!/usr/bin/env python3
"""The wayback rescue: the LEGITIMATE backfill for the hosts whose WAFs
refuse us (gap-ledger 2026-11-05). The Wayback Machine holds copies of the
documents those sites served publicly; we fetch the archived originals
(`id_` raw bytes), never re-encode. One request every PAUSE_S seconds.

Each land carries the ORIGINAL URL as its name (so it joins the same
document the live lane will land if a wall ever lifts) and the snapshot
timestamp as `fetched_at`. A snapshot URL is kept as a second name.

    python wayback_rescue.py --budget-s 3600 [--max-requests 300] [--only fma]

Surfaces are the blocked sources' document URL shapes, enumerated through
the CDX API (which is web.archive.org's own index, not the blocked host).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from support import db, jobrun                    # noqa: E402
from support.docstore.landing import land          # noqa: E402

SOURCES_ROOT = os.environ.get("QV4_SOURCES") or "/opt/data/querynz-estate/sources"
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
PAUSE_S = 5.0

#: (source, cdx url pattern, cdx filter) — the blocked hosts' document shapes
SURFACES = {
    "local_elections": [
        ("www.dunedin.govt.nz/__data/assets/pdf_file/*",
         "original:.*(expense|return|donation).*\\.pdf$"),
        ("www.gdc.govt.nz/*", "original:.*(expense|return|donation).*\\.(pdf|csv|xlsx?)$"),
        ("www.fndc.govt.nz/*", "original:.*(expense|return|donation).*\\.(pdf|csv|xlsx?)$"),
        ("www.ashburtondc.govt.nz/*", "original:.*(expense|return|donation).*\\.(pdf|csv|xlsx?)$"),
    ],
    "councillor_interests": [
        ("www.dunedin.govt.nz/*", "original:.*(interest|pecuniary).*\\.(pdf|csv|xlsx?)$"),
        ("www.gdc.govt.nz/*", "original:.*(interest|pecuniary).*\\.(pdf|csv|xlsx?)$"),
    ],
    "fma": [
        ("www.fma.govt.nz/library/warnings-and-alerts/*", None),
        ("www.fma.govt.nz/about-us/enforcement/cases/*", None),
    ],
    "grants": [
        ("www.communitymatters.govt.nz/*", "original:.*(grant|record|lottery|cogs).*"),
        ("communitymatters.govt.nz/*", "original:.*(grant|record|lottery|cogs).*"),
    ],
}


def cdx_rows(pattern: str, filt: str = None) -> dict:
    """{original_url: newest snapshot timestamp} for every archived URL."""
    q = {"url": pattern, "output": "json", "limit": "20000",
         "filter": "statuscode:200"}
    if filt:
        q["filter"] += "|" + filt
    u = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(u, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        rows = json.load(r)
    if not rows:
        return {}
    header = rows[0]
    i_ts, i_orig = header.index("timestamp"), header.index("original")
    out = {}
    for row in rows[1:]:
        orig, ts = row[i_orig], row[i_ts]
        if orig not in out or ts > out[orig]:
            out[orig] = ts
    return out


def manifest_names(source: str) -> set:
    p = os.path.join(SOURCES_ROOT, source, "manifest.jsonl")
    out = set()
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                for u in row.get("urls", []):
                    out.add(u.get("url"))
                out.update(row.get("names", []))
    except OSError:
        pass
    return {n for n in out if n}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-s", type=float, default=3600)
    ap.add_argument("--max-requests", type=int, default=200)
    ap.add_argument("--only", help="a source name from SURFACES")
    a = ap.parse_args(argv)
    started = jobrun.now()
    conn = db.connect(db.OWNER_KEY, "querynz_v4")
    t0 = time.monotonic()
    out = {"enumerated": 0, "skipped_held": 0, "requests": 0, "landed": 0,
           "failed": 0, "stopped": "end"}

    def time_left():
        return time.monotonic() - t0 < a.budget_s

    for source, patterns in SURFACES.items():
        if a.only and source != a.only:
            continue
        held = manifest_names(source)
        wanted = {}
        for pattern, filt in patterns:
            try:
                rows = cdx_rows(pattern, filt)
            except Exception as exc:            # noqa: BLE001 — record and move on
                out["failed"] += 1
                print(f"{source}: CDX {pattern}: {type(exc).__name__}: {exc}")
                continue
            wanted.update({u: ts for u, ts in rows.items() if u not in held})
        out["enumerated"] += len(wanted)
        for orig, ts in sorted(wanted.items(), key=lambda kv: kv[1]):
            if not time_left() or out["requests"] >= a.max_requests:
                out["stopped"] = "budget"
                break
            snap = f"https://web.archive.org/web/{ts}id_/{orig}"
            req = urllib.request.Request(snap, headers={"User-Agent": UA})
            out["requests"] += 1
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    body = r.read()
            except Exception as exc:            # noqa: BLE001
                out["failed"] += 1
                print(f"{source}: FAIL {orig[:90]}: {type(exc).__name__}")
                time.sleep(PAUSE_S)
                continue
            fetched = dt.datetime.strptime(ts, "%Y%m%d%H%M%S") \
                .replace(tzinfo=dt.timezone.utc).isoformat()
            ref, new = land(body, name=orig, source=source, conn=conn,
                            name_kind="url", fetched_at=fetched,
                            content_type="")
            with conn.transaction():
                conn.execute(
                    "INSERT INTO docs.names (sha256, name, kind) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING", (ref.sha256, snap, "wayback"))
            out["landed"] += 1 if new else 0
            time.sleep(PAUSE_S)
        if out["stopped"] != "end":
            break

    conn.close()
    detail = (f"wayback_rescue: enumerated {out['enumerated']}, requests "
              f"{out['requests']}, landed {out['landed']}, failed {out['failed']}; "
              f"{out['stopped']}")
    print(detail)
    jobrun.record("qv4-wayback-rescue", out["stopped"] in ("end", "budget"),
                  detail, started, out)


if __name__ == "__main__":
    main()
