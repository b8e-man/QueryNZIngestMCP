#!/usr/bin/env python3
"""Hansard debates corpus — one record per sitting day.

Source: Hansard daily PDFs at hansard.parliament.nz (static assets — they
bypass the Radware bot check; plain urllib is fine). A 404 means the House
did not sit that day (it rose 23 Sep 2026). Back run starts 2024-11-20.

Record per sitting day, appended to data/hansard_debates.jsonl (append-only):
  url          PDF URL as fetched
  sitting_date YYYY-MM-DD
  title        "Hansard <date>"
  sha256       hash of the raw PDF as received
  fetched_at   when the bytes landed here (fetch time; file mtime if the
               raw PDF was reused from the earlier probe)
  http_status  200
  raw_file     relative path of the stored PDF
  bytes        size of the raw PDF
  page_count   pdfinfo Pages
  text         pdftotext -layout output, VERBATIM (speaker labels keep
               their position)
  word_count   words in text

Text tool: real poppler pdftotext/pdfinfo, user-space install under
/opt/data/tools/poppler (no sudo). Whole-day text only — no section or
speech splits, so nothing is marked derived.

Usage:
  python3 hansard_debates.py                    # back run 2024-11-20 .. today
  python3 hansard_debates.py --from 2026-09-01  # narrower window
  python3 hansard_debates.py --time-budget 90   # cron tick (stops cleanly)

Silent when nothing new. Idempotent: dates already recorded, known
non-sitting days, and already-downloaded raw PDFs are all handled.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE, "raw")
OUT_F = os.path.join(BASE, "data", "hansard_debates.jsonl")
STATE_F = os.path.join(BASE, "data", "hansard_debates_state.json")
POPPLER_BIN = "/opt/data/tools/poppler/usr/bin"
POPPLER_LIB = "/opt/data/tools/poppler/usr/lib/x86_64-linux-gnu"
URL = "https://hansard.parliament.nz/api/resources/daily/related/{d}/{d}-daily.pdf"
UA = "nz-parliament-research-scraper/1.0 (personal research; low rate)"
DEFAULT_FROM = "2024-11-20"
RETRIES = 2


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_from_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path, default):
    try:
        with open(path) as f:
            c = f.read().strip()
            return json.loads(c) if c else default
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def done_urls():
    out = set()
    if os.path.exists(OUT_F):
        with open(OUT_F) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    u = json.loads(line).get("url")
                    if u:
                        out.add(u)
                except ValueError:
                    pass
    return out


def fetch_pdf(url):
    """(status, body). PDFs bypass the WAF — no browser needed."""
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
            last = e
        except Exception as e:  # noqa: BLE001 — transient network, retry
            last = e
        if attempt < RETRIES:
            time.sleep(3)
    return 0, str(last).encode()


def extract_text(path):
    """(verbatim pdftotext -layout output, page_count)."""
    env = dict(os.environ, LD_LIBRARY_PATH=POPPLER_LIB)
    txt = subprocess.run(
        [os.path.join(POPPLER_BIN, "pdftotext"), "-layout", path, "-"],
        capture_output=True, env=env, timeout=300)
    pages = subprocess.run(
        [os.path.join(POPPLER_BIN, "pdfinfo"), path],
        capture_output=True, env=env, timeout=60)
    page_count = 0
    for line in pages.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("Pages:"):
            page_count = int(line.split()[1])
            break
    return txt.stdout.decode("utf-8", "replace"), page_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_", default=DEFAULT_FROM)
    ap.add_argument("--to", default=date.today().isoformat())
    ap.add_argument("--time-budget", type=float, default=0)
    args = ap.parse_args()
    t0 = time.time()

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_F), exist_ok=True)
    state = load_json(STATE_F, {"not_sitting": []})
    done = done_urls()

    d = date.fromisoformat(args.from_)
    end = date.fromisoformat(args.to)
    added = []
    while d <= end:
        if args.time_budget and time.time() - t0 > args.time_budget:
            break
        ds = d.isoformat()
        url = URL.format(d=ds)
        d += timedelta(days=1)
        if url in done or ds in state["not_sitting"]:
            continue

        raw_path = os.path.join(RAW_DIR, f"hansard_{ds}.pdf")
        fetched_at, body = "", b""
        if os.path.exists(raw_path):
            with open(raw_path, "rb") as f:
                body = f.read(5)
            if body == b"%PDF-":
                with open(raw_path, "rb") as f:
                    body = f.read()
                fetched_at = iso_from_ts(os.path.getmtime(raw_path))
        if not fetched_at:
            st, body = fetch_pdf(url)
            if st == 404:
                state["not_sitting"].append(ds)
                save_json(STATE_F, state)
                continue
            if st != 200 or body[:5] != b"%PDF-":
                print(f"hansard ERR {ds}: status={st} "
                      f"{body[:80].decode('utf-8', 'replace')}")
                continue
            with open(raw_path, "wb") as f:
                f.write(body)
            fetched_at = now_iso()

        text, page_count = extract_text(raw_path)
        rec = {
            "url": url,
            "sitting_date": ds,
            "title": f"Hansard {ds}",
            "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_at": fetched_at,
            "http_status": 200,
            "raw_file": f"raw/hansard_{ds}.pdf",
            "bytes": len(body),
            "page_count": page_count,
            "text": text,
            "word_count": len(text.split()),
        }
        with open(OUT_F, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added.append(ds)

    if added:
        print(f"hansard: +{len(added)} records ({added[0]} .. {added[-1]})")


if __name__ == "__main__":
    sys.exit(main())
