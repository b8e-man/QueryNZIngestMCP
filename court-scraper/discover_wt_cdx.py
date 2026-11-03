#!/usr/bin/env python3
"""Waitangi Tribunal CDX widen (2026-11-03).

The by-year/by-wai walk in discover_new_sources.py covers published
reports via forms.justice.govt.nz/search/Documents/WT/. This widens to
everything the Wayback CDX holds for waitangitribunal.govt.nz (any .pdf)
plus the forms.justice.govt.nz WT document tree — research papers,
appointments, kaupapa material outside the listings.

Resumable per prefix (wt_cdx_state.json). Idempotent against queue+done.
"""
import json, os, re, sys, time, urllib.parse, urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "wt_cdx_state.json")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
SLEEP = 1.5
TARGETS = [
    ("waitangitribunal.govt.nz/", "waitangitribunal.govt.nz/"),
    ("forms.justice.govt.nz/search/Documents/", "forms.justice.govt.nz/search/Documents/"),
]


def main():
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    t0 = time.time()
    state = {}
    if os.path.exists(STATE_F):
        state = json.load(open(STATE_F))
    seen = set()
    for path in (QUEUE_F, DONE_F):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    try:
                        seen.add(json.loads(line)["url"])
                    except Exception:
                        pass
    added = 0
    for label, prefix in TARGETS:
        for kind, res in (("report", "pdf"),):
            key = f"{label}{kind}"
            if state.get(key):
                continue
            if time.time() - t0 > budget:
                print(f"wt-cdx: +{added} (budget)", flush=True)
                return
            q = urllib.parse.urlencode({
                "url": prefix, "matchType": "prefix", "output": "json",
                "fl": "original", "collapse": "urlkey",
                "filter": "statuscode:200", "limit": "30000"})
            try:
                req = urllib.request.Request(CDX + "?" + q,
                                             headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=110) as r:
                    rows = json.loads(r.read())[1:]
            except Exception as e:
                print(f"wt-cdx {label}: {e}", flush=True)
                continue
            urls = set()
            for (u,) in rows:
                lu = u.lower()
                if ".pdf" not in lu and "/search/documents/" not in lu:
                    continue
                if "waitangi" in lu or "wt_doc" in lu or "/documents/" in lu:
                    # the forms.justice Documents tree holds many bodies —
                    # keep only the Waitangi (wt) subtree there (2026-11-03:
                    # a loose filter mis-tagged TT/ARLA rows as waitangi).
                    if "forms.justice.govt.nz" in lu and not re.search(
                            r"/documents/[^/]*wt/|wt_doc", lu):
                        continue
                    urls.add(u)
            with open(QUEUE_F, "a") as f:
                for u in sorted(urls):
                    if u in seen:
                        continue
                    seen.add(u)
                    f.write(json.dumps({"url": u, "court": "waitangi",
                                        "kind": kind,
                                        "discovered_via": "wt-cdx"},
                                       ensure_ascii=False) + "\n")
                    added += 1
            state[key] = True
            with open(STATE_F, "w") as f:
                json.dump(state, f)
            print(f"wt-cdx {label}: {len(urls)} urls, +{added} new", flush=True)
            time.sleep(SLEEP)
    print(f"wt-cdx: +{added} total", flush=True)


if __name__ == "__main__":
    main()
