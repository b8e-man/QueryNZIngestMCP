#!/usr/bin/env python3
"""Written-questions attachment fetcher.

Pulls the 44,585 WQ attachment PDFs via the cracked route

    https://questions.parliament.nz/download/writtenquestion/{attachmentId}

through the rotating IPRoyal residential pool (our VPS IP is blackholed on
questions.parliament.nz). Queue = data/api_queue/questions.jsonl rows with a
non-null attachmentId, minus whatever the manifest says is done. Lands raw
bytes at data/wq_pdfs/<uuid8>_<attachmentName>, provenance appended to
data/wq_pdfs_manifest.jsonl. Resume-safe; size mismatches land anyway
(raw-first) with status recorded. Take-it-easy: backoff + new session on
refusal, abort the run on sustained refusals -- never hammer.

Usage: wq_attach_fetch.py [--budget-s N] [--limit N] [--pace S]
"""
import base64
import hashlib
import json
import os
import random
import secrets
import sys
import time
import urllib.error
import urllib.request

DATA = "/opt/data/parliament-scraper/data"
SRC = os.path.join(DATA, "api_queue", "questions.jsonl")
OUT = os.path.join(DATA, "wq_pdfs")
MANIFEST = os.path.join(DATA, "wq_pdfs_manifest.jsonl")
PROXY_CFG = "/opt/data/beehive-scraper/proxy.json"
URL_BASE = "https://questions.parliament.nz/download/writtenquestion/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def make_opener():
    cfg = json.load(open(PROXY_CFG))
    u = base64.b64decode(cfg["username_b64"]).decode()
    p = base64.b64decode(cfg["password_base_b64"]).decode() \
        + "_country-nz_session-" + secrets.token_hex(5) + "_lifetime-10m"
    pr = "http://" + u + ":" + p + "@geo.iproyal.com:12321"
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": pr, "https": pr}))


def load_done():
    done = set()
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("attachment_id"):
                done.add(r["attachment_id"])
    return done


def iter_queue(done):
    seen = set()
    for line in open(SRC):
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        aid = r.get("attachmentId")
        if not aid or aid in done or aid in seen:
            continue
        seen.add(aid)
        yield r


def append_manifest(row, path, sha, n, status, fetched_at):
    rec = {
        "row_id": row.get("id"),
        "wq_doc": row.get("writtenQuestionsDocumentId"),
        "attachment_id": row.get("attachmentId"),
        "attachment_name": row.get("attachmentName"),
        "expected_size": row.get("attachmentSize"),
        "download_url": URL_BASE + row["attachmentId"],
        "path": path,
        "sha256": sha,
        "bytes": n,
        "status": status,
        "fetched_at": fetched_at,
    }
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    budget_s = None
    limit = None
    pace = 4.0
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--budget-s":
            budget_s = float(argv[i + 1]); i += 2
        elif argv[i] == "--limit":
            limit = int(argv[i + 1]); i += 2
        elif argv[i] == "--pace":
            pace = float(argv[i + 1]); i += 2
        else:
            raise SystemExit("unknown arg " + argv[i])

    os.makedirs(OUT, exist_ok=True)
    lockf = open(os.path.join(DATA, "wq_pdfs_fetch.lock"), "w")
    try:
        import fcntl
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("already running; not started", flush=True)
            return 0
    except ImportError:
        pass
    done = load_done()
    started = time.time()
    landed = 0
    failed = 0
    skip = 0
    consec_fail = 0
    consec_refuse = 0
    op = make_opener()

    for row in iter_queue(done):
        if limit is not None and landed + failed >= limit:
            break
        if budget_s is not None and time.time() - started > budget_s:
            break
        aid = row["attachmentId"]
        name = row.get("attachmentName") or (aid + ".pdf")
        fname = aid[:8] + "_" + name
        path = os.path.join(OUT, fname)
        url = URL_BASE + aid
        ok = False
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                r = op.open(req, timeout=90)
                data = r.read()
                if not data.startswith(b"%PDF-"):
                    raise ValueError("not a pdf: " + repr(data[:40]))
                sha = hashlib.sha256(data).hexdigest()
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                status = "ok"
                if row.get("attachmentSize") and row["attachmentSize"] != len(data):
                    status = "size_mismatch"
                append_manifest(row, path, sha, len(data), status,
                                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                landed += 1
                consec_fail = 0
                consec_refuse = 0
                ok = True
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    consec_refuse += 1
                    print("refused", e.code, aid, "attempt", attempt + 1, flush=True)
                    if consec_refuse >= 3:
                        print("ABORT: sustained refusals", flush=True)
                        print("SUMMARY landed", landed, "failed", failed,
                              "skipped", skip, flush=True)
                        return 2
                    op = make_opener()
                    time.sleep(60 + random.random() * 60)
                elif e.code == 404:
                    append_manifest(row, path, "", 0, "missing",
                                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                    skip += 1
                    ok = True
                    break
                else:
                    print("http", e.code, aid, "attempt", attempt + 1, flush=True)
                    op = make_opener()
                    time.sleep(5 + random.random() * 10)
            except Exception as exc:  # noqa: BLE001
                print("err", type(exc).__name__, aid, "attempt", attempt + 1, flush=True)
                op = make_opener()
                time.sleep(5 + random.random() * 10)
        if not ok:
            failed += 1
            consec_fail += 1
            consec_refuse += 1
            if consec_fail >= 10:
                print("ABORT: 10 consecutive failures", flush=True)
                print("SUMMARY landed", landed, "failed", failed,
                      "skipped", skip, flush=True)
                return 2
        else:
            if not ok:
                pass
        if (landed + failed + skip) % 25 == 0:
            print("progress landed", landed, "failed", failed, "skipped", skip,
                  "elapsed", int(time.time() - started), flush=True)
        time.sleep(pace + random.random() * 2)

    print("SUMMARY landed", landed, "failed", failed, "skipped", skip,
          "elapsed", int(time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
