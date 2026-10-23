#!/usr/bin/env python3
"""Tier-2 page-body fetcher for Beehive — run on a HOME-IP machine (e.g. one of
Arthur's Fedora boxes). The VPS cannot fetch HTML pages (Incapsula JS challenge
on all datacenter IPs); a residential IP is served normally.

Zero-LLM, stdlib-only. Consumes the queue the VPS collector produces.

Usage:
  1. on the home machine, get the queue:
       scp vps:/opt/data/beehive-scraper/pending_pages.jsonl .
  2. fetch bodies:
       python3 beehive_pagefetch.py --queue pending_pages.jsonl --out ./beehive-pages
  3. push results back:
       scp beehive-pages/done.jsonl vps:/opt/data/beehive-scraper/
       rsync -a beehive-pages/ vps:/opt/data/beehive-scraper/data/pages/

Raw only: saves the served HTML verbatim. If a page comes back challenged even
from the home IP, it is recorded with status="challenged" — never bypassed.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
CHALLENGE_MARKERS = (b"_Incapsula_Resource", b"Incapsula incident", b"SWUDNSAI",
                     b"SWJIYLWA", b"Request unsuccessful", b"distil_referrer")
SLEEP = 1.5  # politeness between page fetches


def item_type(url):
    for t in ("release", "speech", "feature"):
        if f"/{t}/" in url:
            return t
    return "page"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True, help="pending_pages.jsonl from the VPS")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    done_path = os.path.join(args.out, "done.jsonl")
    done_urls = set()
    if os.path.exists(done_path):
        with open(done_path) as f:
            for line in f:
                try:
                    done_urls.add(json.loads(line)["url"])
                except Exception:
                    pass

    entries = []
    with open(args.queue) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec["url"] not in done_urls:
                entries.append(rec)

    ok = fail = 0
    for rec in entries[: args.limit]:
        url = rec["url"]
        status, path, sha = "failed", "", ""
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-NZ,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            if any(m in body[:2048] for m in CHALLENGE_MARKERS):
                status = "challenged"
            else:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                d = os.path.join(args.out, day)
                os.makedirs(d, exist_ok=True)
                slug = url.rstrip("/").split("/")[-1] or "index"
                fname = f"{datetime.now(timezone.utc).strftime('%H%M%S')}-{item_type(url)}-{slug}.html"
                path = os.path.join(day, fname)
                with open(os.path.join(args.out, path), "wb") as f:
                    f.write(body)
                sha = hashlib.sha256(body).hexdigest()
                status = "ok"
                ok += 1
        except Exception as e:
            status = f"failed: {e}"[:120]
            fail += 1

        with open(done_path, "a") as f:
            f.write(json.dumps({
                "url": url, "kind": rec.get("kind", ""),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": status, "path": path, "sha256": sha,
            }, ensure_ascii=False) + "\n")
        time.sleep(SLEEP)

    print(f"pagefetch: {ok} ok, {fail} failed/challenged, "
          f"{max(0, len(entries) - args.limit)} left in queue")


if __name__ == "__main__":
    main()
