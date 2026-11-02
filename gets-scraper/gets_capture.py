#!/usr/bin/env python3
"""GETS capture tick — queue drain for tender detail pages.

Byte-exact capture of gets.govt.nz detail pages with full provenance
(fetch time, sha256, HTTP status). No extraction — row metadata (title,
type, buyer, dates) carried from discovery rows is classification only.

Conventions mirror court_scraper.py:
  queue.jsonl  pending rows ({"url","source","rfx_id",...meta})
  done.jsonl   per-URL attempts/status (3 strikes = terminal; 404/410
               terminal on first sight)
  records.jsonl one line per captured page
  data/pages/  raw bytes: gets-<rfx_id>.html
Race-safe flush: merges rows appended by discoverers mid-run.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/gets-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
RECORDS_F = os.path.join(BASE, "records.jsonl")
PAGES = os.path.join(BASE, "data", "pages")
LOGS = os.path.join(BASE, "logs", "tick.log")

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SLEEP = 1.0
TERMINAL = ("ok", "http_404", "http_410")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=80)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    t0 = time.time()
    deadline = t0 + args.time_budget

    done = {}
    if os.path.exists(DONE_F):
        with open(DONE_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done[r["url"]] = r
                except Exception:
                    pass
    queued = []
    queued_set = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec["url"] not in queued_set:
                        queued.append(rec)
                        queued_set.add(rec["url"])
                except Exception:
                    pass

    def terminal(url):
        r = done.get(url)
        return bool(r) and (r.get("status") in TERMINAL
                            or r.get("attempts", 0) >= 3)

    def record_done(url, status, **extra):
        r = done.get(url, {"url": url, "attempts": 0})
        r["attempts"] = r.get("attempts", 0) + 1
        r.update(status=status, last_try=now_iso(), **extra)
        done[url] = r
        with open(DONE_F, "a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def flush_queue():
        # merge with rows appended by discoverers mid-run; known rows win
        known = {r["url"] for r in queued}
        merged = list(queued)
        try:
            with open(QUEUE_F) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("url") and r["url"] not in known:
                        known.add(r["url"])
                        merged.append(r)
        except FileNotFoundError:
            pass
        with open(QUEUE_F, "w") as f:
            for rec in merged:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def record_doc(url, body, content_type, path, rec, case_name):
        sha = hashlib.sha256(body).hexdigest()
        out = {
            "url": url, "kind": "tender_notice", "fetched_at": now_iso(),
            "http_status": 200, "sha256": sha, "path": path,
            "bytes": len(body), "content_type": content_type,
            "case_slug": str(rec.get("rfx_id", "")), "court": "gets",
            "case_name": case_name,
            "discovered_via": rec.get("source", ""),
        }
        # row-metadata classification (from list rows at discovery time)
        for k in ("tender_type", "buyer_org", "reference_no", "close_date"):
            if rec.get(k):
                out[k] = rec[k]
        with open(RECORDS_F, "a") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return sha

    ok = failed = 0
    fails = []
    os.makedirs(PAGES, exist_ok=True)
    batch = [r for r in queued if not terminal(r["url"])][:args.limit]

    for rec in batch:
        url = rec["url"]
        if time.time() > deadline:
            break
        time.sleep(SLEEP)
        try:
            status, body, ctype = fetch(url)
            if status in (404, 410):
                record_done(url, f"http_{status}")
                continue
            if status != 200:
                failed += 1
                fails.append(f"{url}: http_{status}")
                record_done(url, f"http_{status}")
                continue
            rfx = rec.get("rfx_id", url.split("id=")[-1])
            rel = os.path.join("pages", f"gets-{rfx}.html")
            with open(os.path.join(BASE, "data", rel), "wb") as f:
                f.write(body)
            m = TITLE_RE.search(body.decode("utf-8", errors="replace"))
            title = rec.get("title", "")
            if m and not title:
                # "GETS | <Org> - <Title> - ..." — classification metadata
                title = re.sub(r"\s+", " ", m.group(1)).strip()
                title = re.sub(r"^GETS\s*\|\s*", "", title)
            record_doc(url, body, ctype, rel, rec, title[:300])
            record_done(url, "ok", sha256=hashlib.sha256(body).hexdigest())
            ok += 1
        except Exception as e:
            failed += 1
            fails.append(f"{url}: {str(e)[:80]}")
            record_done(url, f"failed: {str(e)}"[:100])

    flush_queue()

    os.makedirs(os.path.dirname(LOGS), exist_ok=True)
    with open(LOGS, "a") as f:
        f.write(f"{now_iso()} pages_ok={ok} pages_failed={failed} "
                f"queue={len(queued)} secs={time.time()-t0:.0f}\n")

    if not ok and failed and fails:
        print(f"GETS capture: 0 captured, {failed} failures. "
              f"Errors: {'; '.join(fails[:5])}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
