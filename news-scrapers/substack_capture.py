#!/usr/bin/env python3
"""substack_capture.py — estate-substack collector (ask estate-substack@2026-11-18).

13 Substack publications, FORWARD ONLY (posts published on or after
2026-11-18 NZ). Free posts only ("audience": "everyone"): land the whole
post JSON and the whole comments response as their own records, linked to
the post's address. Paid posts are never landed as articles — they are
listed in the archive record (id, title, date, audience).

Record kinds (corpus estate-substack):
  substack_post      free post JSON whole (/api/v1/posts/<slug>)
  substack_comments  comments response whole
                     (/api/v1/post/<id>/comments?all_comments=true
                      &sort=oldest_first), fields as Substack serves them
  substack_archive   the archive listing per publication: every free post
                     (id, title, date, audience) and every paid post
                     (id, title, date, audience) we do not hold

Falling re-capture schedule for comments: first ASAP, then d3 / d7 / d30.
Every capture kept, append-only. Slow polite pace; failures gap-listed and
moved on.

Landing: /opt/data/news-scrapers/data-substack/<pub>/manifest.jsonl +
store/<2>/<sha256>.

Mangle-safe: no scheme-ful URL literals (scheme assembled at runtime).
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
POLITE = 4.0
ROOT = "/opt/data/news-scrapers/data-substack"
GAPS = "/opt/data/querynz-estate/gaps/substack_gap_ledger.jsonl"
FORWARD = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)  # 2026-11-18 NZ
MILESTONES = ("first", "d3", "d7", "d30")
AGE_DAYS = {"d3": 3, "d7": 7, "d30": 30}

PUBS = ["thekaka.substack.com", "democracyproject.org.nz",
        "newzealandloyal.substack.com", "aniobrien.substack.com",
        "primefuture.substack.com", "justthebusinessjennyruth.substack.com",
        "theasiaeconomist.substack.com", "southlandtribune.substack.com",
        "robayson.substack.com", "nzglobaleconomicscontext.substack.com",
        "grantduncanphd.substack.com", "nzae.substack.com",
        "tradenotes.substack.com"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s):
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_last_fetch = [0.0]


def fetch(addr, timeout=30):
    wait = POLITE - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(addr, headers={"User-Agent": UA,
                                                "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            _last_fetch[0] = time.time()
            return r.status, r.geturl(), body
    except urllib.error.HTTPError as e:
        _last_fetch[0] = time.time()
        return e.code, addr, (e.read() or b"")
    except Exception as e:  # noqa: BLE001
        _last_fetch[0] = time.time()
        return 0, addr, str(e).encode()


def store_raw(pub, body):
    h = hashlib.sha256(body).hexdigest()
    d = os.path.join(ROOT, pub, "store", h[:2])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, h)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(body)
    return h, p


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def gap_row(pub, addr, reason, status="open"):
    append_jsonl(GAPS, {"source": pub, "url": addr, "reason": reason,
                        "status": status, "at": now_iso()})


def read_state():
    st = {}
    p = os.path.join(ROOT, ".state.jsonl")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            st[(r.get("post"), r.get("milestone"))] = r
    return st


def land(pub, kind, post_addr, captured_at, raw, extra):
    sha, path = store_raw(pub, raw)
    rid = hashlib.sha256(
        f"{kind}|{post_addr}|{captured_at}".encode()).hexdigest()[:32]
    row = {
        "record_id": rid,
        "source": pub,
        "kind": kind,
        "post": post_addr,
        "captured_at": captured_at,
        "url": extra.pop("_addr"),
        "fetched_at": captured_at,
        "http_status": extra.pop("_status"),
        "sha256": sha,
        "bytes": len(raw),
        "file": path,
        "landed_at": now_iso(),
        **extra,
    }
    append_jsonl(os.path.join(ROOT, pub, "manifest.jsonl"), row)
    return rid


def comments_milestones(post_addr, published_at, state):
    if published_at is None or published_at < FORWARD:
        return []
    age = (datetime.now(timezone.utc) - published_at).total_seconds() / 86400.0
    out = []
    for m in MILESTONES:
        rec = state.get((post_addr, m))
        if rec and rec.get("status") in ("captured", "challenge"):
            continue
        if m == "first" or age >= AGE_DAYS[m]:
            out.append(m)
        if out and m != out[0]:
            break
    return out[:1]


def run_pub(pub, budget):
    state = read_state()
    # 1) archive sweep — the listing that says what exists (free + paid).
    # The public endpoint serves only the newest 25 (limit max, no offset)
    # — plenty for a forward-only window; noted in the readiness report.
    addr = SCHEME + pub + "/api/v1/archive?sort=new&limit=25"
    st, final, body = fetch(addr)
    if st != 200:
        gap_row(pub, addr, f"archive http {st}",
                "challenge" if st in (401, 403) else "open")
        return {"pub": pub, "error": f"archive http {st}"}
    try:
        arch = json.loads(body)
    except ValueError:
        gap_row(pub, addr, "archive bad json", "open")
        return {"pub": pub, "error": "archive bad json"}
    if not isinstance(arch, list):
        arch = arch.get("posts") or arch.get("archive") or []
    fresh, paid, boundary_met = [], [], False
    for p in arch:
        pub_d = parse_iso(p.get("post_date"))
        if pub_d is None:
            continue
        if pub_d < FORWARD:
            boundary_met = True
            continue
        item = {"id": p.get("id"), "title": p.get("title"),
                "date": p.get("post_date"), "audience": p.get("audience"),
                "slug": p.get("slug"), "canonical_url": p.get("canonical_url")}
        if p.get("audience") == "everyone":
            fresh.append(item)
        else:
            paid.append(item)
    cap_at = now_iso()
    # the archive record lands when the in-window listing CHANGES (or at
    # first sight) — not on every sweep; the raw listing is append-only
    ids_hash = hashlib.sha256(
        json.dumps(sorted(str(p.get("id")) for p in arch)).encode()
    ).hexdigest()[:16]
    arch_addr = SCHEME + pub + "/archive"
    arch_state = state.get((arch_addr, "archive"))
    if not (arch_state and arch_state.get("ids_hash") == ids_hash):
        land(pub, "substack_archive", arch_addr, cap_at, body,
             {"_addr": addr, "_status": st, "published_at": "",
              "free_posts": fresh, "paid_posts": paid,
              "total_at_capture": len(arch)})
        append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                     {"post": arch_addr, "milestone": "archive",
                      "captured_at": cap_at, "record_id": None,
                      "status": "captured", "ids_hash": ids_hash})
        state[(arch_addr, "archive")] = {"status": "captured",
                                         "ids_hash": ids_hash}

    did = errs = 0
    for item in fresh:
        if did >= budget:
            break
        slug = item.get("slug")
        pid = item.get("id")
        post_addr = item.get("canonical_url") or (SCHEME + pub + "/p/" + str(slug))
        published = parse_iso(item.get("date"))
        # 2) the free post JSON whole (one record; no re-capture per ask)
        if not state.get((post_addr, "post")):
            p_addr = SCHEME + pub + "/api/v1/posts/" + urllib.parse.quote(str(slug))
            st, final, raw = fetch(p_addr)
            if st != 200:
                gap_row(pub, p_addr, f"post http {st}",
                        "challenge" if st in (401, 403) else "open")
                errs += 1
            else:
                land(pub, "substack_post", post_addr, now_iso(), raw,
                     {"_addr": p_addr, "_status": st,
                      "post_id": pid, "slug": slug, "title": item.get("title"),
                      "published_at": item.get("date") or "",
                      "audience": item.get("audience") or "",
                      "milestone": "first"})
                append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                             {"post": post_addr, "milestone": "post",
                              "captured_at": now_iso(), "record_id": None,
                              "status": "captured"})
                state[(post_addr, "post")] = {"status": "captured"}
                did += 1
        # 3) comments on the falling schedule (first ASAP)
        for m in comments_milestones(post_addr, published, state):
            c_addr = (SCHEME + pub + "/api/v1/post/" + str(pid)
                      + "/comments?all_comments=true&sort=oldest_first")
            st, final, raw = fetch(c_addr)
            cap_at = now_iso()
            if st != 200:
                gap_row(pub, c_addr, f"comments http {st}",
                        "challenge" if st in (401, 403) else "open")
                append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                             {"post": post_addr, "milestone": m,
                              "captured_at": cap_at, "record_id": None,
                              "status": "failed", "reason": f"http {st}"})
                errs += 1
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            # as-served shape: {"comments": [trees...],
            #                  "automod_hidden_comments": [...]}
            if isinstance(data, dict):
                crows = data.get("comments") or []
                hidden = data.get("automod_hidden_comments") or []
            elif isinstance(data, list):
                crows, hidden = data, []
            else:
                crows, hidden = [], []
            n = sum(1 for _ in _walk_comments(crows))
            rid = land(pub, "substack_comments", post_addr, cap_at, raw,
                       {"_addr": c_addr, "_status": st, "post_id": pid,
                        "slug": slug, "title": item.get("title"),
                        "published_at": item.get("date") or "",
                        "milestone": m, "total_at_capture": n,
                        "comments": crows,
                        "automod_hidden_comments": hidden})
            append_jsonl(os.path.join(ROOT, ".state.jsonl"),
                         {"post": post_addr, "milestone": m,
                          "captured_at": cap_at, "record_id": rid,
                          "status": "captured"})
            state[(post_addr, m)] = {"status": "captured"}
            print(f"  {pub} {m} {slug} -> {rid} ({n} comments)")
            did += 1
    return {"pub": pub, "captured": did, "errors": errs,
            "free": len(fresh), "paid": len(paid), "boundary": boundary_met}


def _walk_comments(rows):
    for c in rows:
        yield c
        ch = c.get("children")
        if isinstance(ch, list):
            yield from _walk_comments(ch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pub")
    ap.add_argument("--budget", type=int, default=20)
    args = ap.parse_args()
    pubs = [args.pub] if args.pub else PUBS
    tot = {"captured": 0, "errors": 0}
    for pub in pubs:
        r = run_pub(pub, args.budget)
        if "error" in r:
            print(f"  {pub}: {r['error']}")
        else:
            print(f"  {pub}: free={r['free']} paid={r['paid']} "
                  f"records={r['captured']} errors={r['errors']}")
        tot["captured"] += r.get("captured", 0)
        tot["errors"] += r.get("errors", 0)
    print(f"substack capture: records={tot['captured']} errors={tot['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
