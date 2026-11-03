#!/usr/bin/env python3
"""Re-verify pass + change events feed (provider ask: suppression/takedown
semantics, 2026-11-03).

Captured URLs are never re-fetched by the tick — so a judgment that is
later suppressed, taken down, or silently replaced was invisible. This
pass samples captured records oldest-checked-first and emits explicit
events to change_events.jsonl:

  removed          200 -> 404/410 (suppression or takedown)
  restored         previously removed -> 200 again
  content_changed  200 -> 200, different bytes (new capture appended as
                   a fresh record via the tick's store_bytes convention;
                   here we record both shas and the new record row)

Every event carries url, detected_at, prev_sha256, new_sha256 and the
record's citation/court where known. The MCP `changes` tool surfaces
these alongside the updated_at feed — a removal is a first-class event,
not silence.

Politeness: courtsofnz / justice.govt.nz at the tick's cadence; sample
size bounded per run (--limit). State: reverify_state.json (url ->
last_checked).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/court-scraper"
RECORDS_F = os.path.join(BASE, "records.jsonl")
EVENTS_F = os.path.join(BASE, "change_events.jsonl")
STATE_F = os.path.join(BASE, "reverify_state.json")
sys.path.insert(0, BASE)
from court_scraper import UA, SLEEP, POLITE_SLEEP, store_bytes  # noqa: E402

TERMINAL_STATUS = ("http_404", "http_410")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def semantic_sha(body):
    """Compare hash with per-request noise stripped (ASP.NET __VIEWSTATE /
    eventvalidation hidden inputs, clock ticks). Raw bytes are stored
    byte-exact and raw sha stays the artifact hash; this hash exists only
    so 'content_changed' means the PAGE changed, not the token."""
    t = body.decode("utf-8", errors="replace")
    t = re.sub(r'<input[^>]*type="hidden"[^>]*>', "", t, flags=re.I)
    t = re.sub(r'name="(?:__VIEWSTATE|__EVENTVALIDATION|__VIEWSTATEGENERATOR'
               r'|__EVENTTARGET|__EVENTARGUMENT)"[^>]*', "", t, flags=re.I)
    t = re.sub(r"\d{1,2}:\d{2}:\d{2}", "TIME", t)
    t = re.sub(r"\s+", " ", t)
    return hashlib.sha256(t.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--time-budget", type=int, default=100)
    args = ap.parse_args()
    t0 = time.time()

    state = {}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except ValueError:
            state = {}

    # latest record per URL (records.jsonl is append-only; last row wins)
    latest = {}
    with open(RECORDS_F) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("url") and r.get("sha256"):
                    latest[r["url"]] = r

    # oldest-checked first; deterministic sample so coverage spreads
    urls = sorted(latest, key=lambda u: state.get(u, ""))
    random.Random(42).shuffle(urls)
    urls.sort(key=lambda u: state.get(u, ""))
    urls = urls[:args.limit]

    events = []
    for u in urls:
        if time.time() - t0 > args.time_budget:
            break
        rec = latest[u]
        host = urllib.parse.urlparse(u).netloc
        time.sleep(POLITE_SLEEP.get(host, SLEEP))
        try:
            status, body = fetch(u)
        except Exception as e:
            events.append({"url": u, "event": "reverify_error",
                           "detail": str(e)[:100], "detected_at": now_iso(),
                           "corpus": "courts"})
            state[u] = now_iso()
            continue
        prev = rec.get("sha256")
        # semantic comparison against the stored artifact — token churn is
        # not a content change
        stored_path = os.path.join(BASE, "data", rec.get("path", ""))
        if status == 200 and rec.get("path") and os.path.exists(stored_path):
            with open(stored_path, "rb") as f:
                if semantic_sha(f.read()) == semantic_sha(body):
                    state[u] = now_iso()
                    continue
        if status in (404, 410):
            events.append({"url": u, "event": "removed",
                           "http_status": status, "detected_at": now_iso(),
                           "prev_sha256": prev, "corpus": "courts",
                           "citation": rec.get("citation", ""),
                           "court": rec.get("court", "")})
        elif status == 200:
            new = hashlib.sha256(body).hexdigest()
            if new != prev:
                if rec.get("removed_at"):
                    events.append({"url": u, "event": "restored",
                                   "detected_at": now_iso(),
                                   "new_sha256": new, "corpus": "courts"})
                else:
                    tag = hashlib.sha1(u.encode()).hexdigest()[:10]
                    rel = store_bytes(
                        os.path.join("pages", f"reverify-{tag}.html")
                        if not u.lower().endswith(".pdf") else
                        os.path.join("pdfs", "reverify", f"reverify-{tag}.pdf"),
                        body)
                    events.append({"url": u, "event": "content_changed",
                                   "detected_at": now_iso(),
                                   "prev_sha256": prev, "new_sha256": new,
                                   "path": rel, "corpus": "courts",
                                   "citation": rec.get("citation", ""),
                                   "court": rec.get("court", "")})
        else:
            events.append({"url": u, "event": "reverify_http",
                           "http_status": status, "detected_at": now_iso(),
                           "corpus": "courts"})
        state[u] = now_iso()

    if events:
        with open(EVENTS_F, "a") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(STATE_F, "w") as f:
        json.dump(state, f)

    kinds = {}
    for e in events:
        kinds[e["event"]] = kinds.get(e["event"], 0) + 1
    print(f"reverify: checked={len(urls)} events={len(events)} {kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
