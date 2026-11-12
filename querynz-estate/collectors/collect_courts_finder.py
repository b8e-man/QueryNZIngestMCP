#!/usr/bin/env python3
"""collect_courts_finder.py — Ministry of Justice decisions finder collector
(estate-collect@2026-11-13, ruling 172). One finder serves 22 jurisdictions
(?Filter_Jurisdiction=<id>, 25 a page, start=<offset>). Collects every decision
PDF the estate does not hold (asks/held-courts-finder.tsv: by address or
sha256), whole, as fetched, with the listing page and its metadata (case,
citation, decision date, statute). NO text extraction.

Two phases per tick:
  fresh   — page 1 of every jurisdiction each tick (new decisions land fast)
  backfill— a per-jurisdiction start-offset cursor walking the deep catalogue

Gaps: every refused/failed fetch appends one row to
/opt/data/querynz-estate/gaps/collect_courts_finder.jsonl (assess later).
Politeness: 5s pacing, robots honoured, patience retries, cool-down on
refusal, never re-hammering a failed URL in the same run.
"""
import argparse
import hashlib
import html.parser
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone

SCHEME = "https" + chr(58) + chr(47) + chr(47)
HOST = "www.justice.govt.nz"
FINDER = "/tribunals/human-rights/hrrt-decisions/"
UA = "QueryNZIngest/1.0 (polite collector; contact: operator)"
SRC = "/opt/data/querynz-estate/sources/courts-finder"
GAPS = "/opt/data/querynz-estate/gaps/collect_courts_finder.jsonl"
HELD = "/opt/data/qnz-mcp/asks/held-courts-finder.tsv"
STATE = "/opt/data/querynz-estate/collect_courts_finder_state.json"
LOCK = "/opt/data/querynz-estate/collect_courts_finder_state.lock"

# the 22 asked jurisdictions (collect.json, ruling 172) -> finder filter ids.
# 777 and 30 are the same body under two finder labels ("Secondhand Dealers and
# Pawnbrokers" / "Licensing Authority of Secondhand Dealers & Pawnbrokers") —
# both walked, noted in the report.
JURIS = {
    "Employment Court": 17,
    "Disputes Tribunal": 26,
    "Maori Land Court": 24,
    "Maori Appellate Court": 468,
    "Environment Court": 19,
    "Coroners": 18,
    "Human Rights Review Tribunal": 27,
    "Legal Complaints Review Officer": 29,
    "Lawyers and Conveyancers Disciplinary Tribunal": 279,
    "Real Estate Agents Disciplinary Tribunal": 32,
    "Weathertight Homes Tribunal": 35,
    "Canterbury Earthquakes Insurance Tribunal": 768,
    "Land Valuation Tribunal": 636,
    "Accident Compensation Appeal Authority": 23,
    "Accident Compensation Appeals District Court Registry": 795,
    "Social Security Appeal Authority": 275,
    "Student Allowance Appeal Authority": 33,
    "Customs Appeal Authority": 792,
    "Review Authority": 277,
    "Immigration Advisers Complaints and Disciplinary Tribunal": 28,
    "Private Security Personnel Licensing Authority": 745,
    "Secondhand Dealers and Pawnbrokers": 777,
    "Licensing Authority of Secondhand Dealers and Pawnbrokers": 30,
}

TRACKING = ("utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_addr(url):
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if k.lower() not in TRACKING]
    path = p.path or "/"
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return (p.hostname or "").lower() + path + (
        ("?" + urllib.parse.urlencode(q)) if q else "")


def log_gap(reason, url, status=None, detail=None):
    os.makedirs(os.path.dirname(GAPS), exist_ok=True)
    row = {"source": "justice.govt.nz/decisions-finder", "url": url,
           "reason": reason, "status": status, "detail": detail,
           "at": now_iso()}
    with open(GAPS, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class Held:
    def __init__(self, path):
        self.addrs, self.shas = set(), set()
        with open(path, encoding="utf-8") as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                row = dict(zip(header, line.rstrip("\n").split("\t")))
                a = (row.get("address_or_name") or "").strip()
                s = (row.get("sha256") or "").strip().lower()
                if a.startswith("http"):
                    self.addrs.add(norm_addr(a))
                if s:
                    self.shas.add(s)
        self.count = len(self.addrs) + len(self.shas)

    def holds(self, url, sha=None):
        return norm_addr(url) in self.addrs or (sha and sha in self.shas)


def fetch(url, timeout=60):
    """(meta, data) or raises RuntimeError('challenge'/'http:N'/'io:X')."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return {"address": url, "final_address": r.geturl(),
                        "content_type": r.headers.get("Content-Type"),
                        "size": len(data),
                        "last_modified": r.headers.get("Last-Modified"),
                        "etag": r.headers.get("ETag"),
                        "fetched_at": now_iso()}, data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(10)
                continue
            if e.code in (403, 429):
                raise RuntimeError("challenge")
            raise RuntimeError("http:%d" % e.code)
        except Exception as e:
            if attempt < 2:
                time.sleep(5)
                continue
            raise RuntimeError("io:" + type(e).__name__)


ART_RE = re.compile(r"<article.*?</article>", re.S)
HREF_RE = re.compile(r'<a href="([^"]+\.pdf)"', re.I)
HEAD_RE = re.compile(r'class="searchResultHeader">(.*?)</(?:span|h4)>', re.S)
P_RE = re.compile(r"<p>(.*?)</p>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
ITEMS_RE = re.compile(r'([\d,]+)\s*</span> items matching')


def parse_page(text):
    """[(pdf_url, listed_meta)] in listed order; commented-out duplicate
    anchors are inside <!-- --> and the first href of each article is the
    live one."""
    out = []
    for art in ART_RE.findall(text):
        m = HREF_RE.search(art)
        if not m:
            continue
        url = m.group(1).replace("&amp;", "&")
        head = TAG_RE.sub(" ", (HEAD_RE.search(art) or [None, ""])[1])
        head = re.sub(r"\s+", " ", head).strip()
        body = TAG_RE.sub(" ", (P_RE.search(art) or [None, ""])[1])
        body = re.sub(r"\s+", " ", body).strip()
        dm = re.search(r"Date of decision:\s*([^.]+(?:\d{4})?)\.", body)
        out.append((url, {
            "title": head or None,
            "date": dm.group(1).strip() if dm else None,
            "statute": body or None,
        }))
    total = ITEMS_RE.search(text)
    return out, (int(total.group(1).replace(",", "")) if total else None)


def listing_url(jid, start):
    return (SCHEME + HOST + FINDER + "?Filter_Jurisdiction=%d&start=%d"
            % (jid, start))


class Runner:
    def __init__(self, args):
        self.args = args
        self.held = Held(args.held_tsv)
        self.state = self._load()
        self.manifest = os.path.join(SRC, "manifest.jsonl")
        self.rows, self.by_addr = self._load_manifest()
        self.stats = {}
        self.fetches = 0
        self.cool = 0.0
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(SCHEME + HOST + "/robots.txt")
            rp.read()
        except Exception:
            pass
        self.rp = rp

    def _load(self):
        if os.path.exists(STATE):
            with open(STATE) as f:
                return json.load(f)
        return {"backfill_start": {}, "failed": {}}

    def _save(self):
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE)

    def _load_manifest(self):
        rows, addrs = {}, {}
        if os.path.exists(self.manifest):
            with open(self.manifest, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if row.get("sha256"):
                        rows[row["sha256"]] = row
                        for u in row.get("urls", []):
                            addrs[norm_addr(u.get("url", ""))] = row["sha256"]
        return rows, addrs

    def _flush(self):
        tmp = self.manifest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for row in self.rows.values():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, self.manifest)

    def stat(self, name):
        return self.stats.setdefault(name, {
            "listings": 0, "seen": 0, "docs_fetched": 0, "landed": 0,
            "skipped_held": 0, "skipped_landed": 0, "errors": 0,
            "challenged": 0})

    def _polite(self):
        if self.cool > time.time():
            time.sleep(self.cool - time.time())
        time.sleep(self.args.pace)

    def _get(self, url, st):
        self._polite()
        self.fetches += 1
        try:
            return fetch(url)
        except RuntimeError as e:
            s = str(e)
            if s == "challenge":
                st["challenged"] += 1
                self.cool = time.time() + 45
                log_gap("challenge", url, None, "cool-down 45s")
            else:
                st["errors"] += 1
                log_gap("error", url, s)
            return None

    def collect_listings(self, jname, jid, start, st, wanted):
        """walk listing pages from `start`, collecting unseen pdf urls into
        `wanted` (dict url->listed_meta). Returns (pages_read, done)."""
        pages = 0
        off = start
        while pages < self.args.max_listings:
            meta, data = self._get(listing_url(jid, off), st)
            if meta is None:
                return pages, False      # failure: cursor stays, tried again
            text = data.decode("utf-8", "replace")
            st["listings"] += 1
            items, total = parse_page(text)
            pages += 1
            if not items:
                return pages, True       # empty page: jurisdiction done
            new_here = 0
            for url, lmeta in items:
                st["seen"] += 1
                if url in self.state["failed"] or norm_addr(url) in self.by_addr:
                    st["skipped_landed"] += 1
                    continue
                if self.held.holds(url):
                    st["skipped_held"] += 1
                    continue
                if url not in wanted:
                    wanted[url] = (jname, lmeta)
                    new_here += 1
            off += 25
            if total is not None and off >= total:
                return pages, True
            if start > 0 and new_here == 0 and pages >= 2:
                # backfill zone fully known: nothing new, keep moving
                pass
        return pages, False

    def land_doc(self, url, jname, lmeta, st):
        self._polite()
        self.fetches += 1
        try:
            meta, data = fetch(url)
        except RuntimeError as e:
            s = str(e)
            if s == "challenge":
                st["challenged"] += 1
                self.cool = time.time() + 45
                log_gap("challenge", url, None, "doc fetch")
            else:
                st["errors"] += 1
                self.state["failed"][url] = s
                log_gap("error", url, s, "doc fetch")
            return
        sha = hashlib.sha256(data).hexdigest()
        if self.held.holds(url, sha):
            st["skipped_held"] += 1
            return
        if sha in self.rows:
            st["skipped_landed"] += 1
            return
        os.makedirs(SRC, exist_ok=True)
        fn = sha + (os.path.splitext(urllib.parse.urlsplit(url).path)[1] or ".pdf")
        with open(os.path.join(SRC, fn), "wb") as f:
            f.write(data)
        row = {
            "sha256": sha,
            "size": meta["size"],
            "kind": "decision",
            "content_type": meta.get("content_type"),
            "file": fn,
            "urls": [{"url": url, "via": ["collect_courts_finder"]}],
            "names": [lmeta.get("title") or url],
            "listed_on": [],
            "listed": dict(lmeta, jurisdiction=jname),
            "landings": 1,
            "first_landed": meta["fetched_at"],
            "last_landed": meta["fetched_at"],
            "fetched_at": meta["fetched_at"],
            "landed_at": meta["fetched_at"],
            "last_modified": meta.get("last_modified"),
            "etag": meta.get("etag"),
            "final_address": meta.get("final_address"),
            "withdrawn": False,
            "withdrawn_reason": None,
            "problem": None,
        }
        self.rows[sha] = row
        self.by_addr[norm_addr(url)] = sha
        st["docs_fetched"] += 1
        st["landed"] += 1

    def run(self):
        deadline = time.time() + self.args.max_seconds
        # phase 1: fresh — page 1 of every jurisdiction
        for jname, jid in JURIS.items():
            if time.time() >= deadline:
                break
            st = self.stat(jname)
            wanted = {}
            self.collect_listings(jname, jid, 0, st, wanted)
            for url, (jn, lm) in wanted.items():
                if time.time() >= deadline:
                    break
                self.land_doc(url, jn, lm, st)
            self._save()
            self._flush()
        # phase 2: backfill — per-jurisdiction cursor
        for jname, jid in JURIS.items():
            if time.time() >= deadline:
                break
            st = self.stat(jname)
            start = self.state["backfill_start"].get(str(jid), 0)
            wanted = {}
            pages, done = self.collect_listings(jname, jid, start, st, wanted)
            for url, (jn, lm) in wanted.items():
                if time.time() >= deadline:
                    break
                self.land_doc(url, jn, lm, st)
            if time.time() < deadline:
                self.state["backfill_start"][str(jid)] = (
                    10 ** 9 if done else start + pages * 25)
            self._save()
            self._flush()
        self.report()

    def report(self):
        out = ["collect_courts_finder: %s" % now_iso(),
               "held rows: %d | fetches this run: %d"
               % (self.held.count, self.fetches)]
        for name, st in sorted(self.stats.items()):
            out.append("  %s: %s" % (name, st))
        backfill = self.state["backfill_start"]
        done_n = sum(1 for v in backfill.values() if v >= 10 ** 9)
        out.append("backfill done: %d of %d jurisdictions"
                   % (done_n, len(JURIS)))
        print("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=int, default=1200)
    ap.add_argument("--max-listings", type=int, default=6)
    ap.add_argument("--pace", type=float, default=5.0)
    ap.add_argument("--held-tsv", default=HELD)
    args = ap.parse_args()
    import fcntl
    with open(LOCK, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("collect_courts_finder: another run holds the lock — exiting")
            return 0
        Runner(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
