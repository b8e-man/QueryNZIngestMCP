"""The elections.nz capture: candidate returns and donation disclosures.

The estate's v4 lanes for these two sources only adopted its old browser's
downloads; this is the live walk, built from the URLs the handover's manifests
record. A genuinely headed Chromium reads the site (Xvfb :99); per the fetch
gate's rules a page shown a challenge stops the run at once and nothing is
solved or routed around. Pace: one request at a time, PAUSE_S apart; a 403,
429 or 5xx on anything stops the run (the next nightly run may ask again).

    python elections_nz.py --lane candidate_returns --budget-s 3600
    python elections_nz.py --lane disclosures --budget-s 3600

Listing pages and their PDFs land through the one landing wrapper: store
bytes, docs rows, manifest row -> the estate-* corpus grows live. A URL
already in the source manifest or the store's names is not asked again
unless its document is missing.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import db, jobrun            # noqa: E402
from support.docstore.landing import land  # noqa: E402

SOURCES_ROOT = os.environ.get("QV4_SOURCES") or "/opt/data/querynz-estate/sources"
CHALLENGE_MARKS = ("captcha", "just a moment", "access denied", "cf-chl",
                   "are you a human", "pardon our interruption", "attention required")
PAUSE_S = 5.0

LISTINGS = {
    "candidate_returns": [
        "https://elections.nz/democracy-in-nz/historical-events/2020-general-election-and-referendums/candidate-expenses-and-donations-for-the-2020-general-election?Year=2020&start={n}",
        "https://elections.nz/democracy-in-nz/historical-events/2023-general-election/candidate-expenses-donations-and-loans?Year=2023&start={n}",
        # backwalk (Arthur 2026-11-05: "let's get them all"): the 2017
        # historical-events listing, PDFs under /assets/candidate-returns/2017/
        "https://elections.nz/democracy-in-nz/historical-events/2017-general-election/candidate-expenses-and-donations-for-the-2017-general-election?Year=2017&start={n}",
    ],
    "disclosures": [
        "https://elections.nz/democracy-in-nz/political-parties-in-new-zealand/donations-exceeding-20000/",
        "https://elections.nz/democracy-in-nz/political-parties-in-new-zealand/donations-exceeding-20000/donations-exceeding-30000",
    ],
}
PAGE_STEP = 100          # the listings page 100 rows at a time (start=N)


def manifest_urls(lane: str) -> set:
    p = os.path.join(SOURCES_ROOT, lane, "manifest.jsonl")
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
    except OSError:
        pass
    return {u for u in out if u}


def challenged(page) -> bool:
    try:
        html = page.content().lower()
    except Exception:                     # noqa: BLE001
        return True
    return any(m in html for m in CHALLENGE_MARKS)


def link_urls(page) -> list:
    out = []
    for href in page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href)"):
        if "/assets/" in href and ".pdf" in href.lower():
            out.append(href.split("#")[0])
        elif href.endswith((".xlsx", ".xls", ".csv")) and "/assets/" in href:
            out.append(href.split("#")[0])
    return out


def run(lane: str, budget_s: float, log) -> dict:
    from playwright.sync_api import sync_playwright
    started = jobrun.now()
    conn = db.connect(db.OWNER_KEY, "querynz_v4")
    t0 = time.monotonic()
    held = manifest_urls(lane)
    out = {"requests": 0, "pages": 0, "files": 0, "new": 0, "already": 0,
           "failed": 0, "stopped": "end"}

    def time_left():
        return time.monotonic() - t0 < budget_s

    def land_url(pg, url, kind_name):
        out["requests"] += 1
        if kind_name == "file" and url in held:
            out["already"] += 1
            return True
        if kind_name == "page":
            resp = pg.goto(url, timeout=45000)
            time.sleep(PAUSE_S)
            if resp is None:
                out["failed"] += 1
                out["stopped"] = f"transport failure at {url}"
                return False
            if resp.status >= 400:
                out["failed"] += 1
                if resp.status in (403, 429) or resp.status >= 500:
                    out["stopped"] = f"refused: HTTP {resp.status} on {url}"
                    return False
                held.add(url)          # a 404: asked, nothing there
                return True
            if challenged(pg):
                out["stopped"] = f"challenge shown at {url}"
                return False
            body = pg.content().encode("utf-8", "replace")
            ref, new = land(body, name=url, source=lane, name_kind="url",
                            content_type="text/html", conn=conn)
            out["pages"] += 1
        else:
            r = pg.context.request.get(url, timeout=60000)
            time.sleep(PAUSE_S)
            if r.status >= 400:
                out["failed"] += 1
                if r.status in (403, 429) or r.status >= 500:
                    out["stopped"] = f"refused: HTTP {r.status} on {url}"
                    return False
                held.add(url)
                return True
            body = r.body()
            head = body[:200].lstrip().lower()
            if not body:
                out["failed"] += 1
                out["stopped"] = f"empty body on file {url}"
                return False
            if head.startswith((b"<!doctype", b"<html", b"<head", b"<body")):
                # a file URL must never answer HTML. Bare Incapsula
                # interstitials carry no challenge wording (212-byte stubs),
                # and a PDF viewer shell (271 bytes) is silent too — both
                # landed as "files" when only known CHALLENGE_MARKS were
                # checked. HTML here means blocked or wrong body: stop the
                # run (take it easy) and land nothing.
                out["stopped"] = f"HTML body on file (blocked?): {url}"
                return False
            ref, new = land(body, name=url, source=lane, name_kind="url",
                            content_type=r.headers.get("content-type", ""), conn=conn)
            out["files"] += 1
        held.add(url)
        if new:
            out["new"] += 1
        return True

    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        pg = b.new_page()
        # Round-robin over the listings (2026-11-05): one page of each
        # template per round, so a surface with new files is never starved
        # behind another's cheap re-pagination.
        states = [{"template": t, "n": 0, "empty": 0, "done": False}
                  for t in LISTINGS[lane]]
        while time_left() and not all(s["done"] for s in states):
            for s in states:
                if s["done"] or not time_left():
                    continue
                template = s["template"]
                url = template.format(n=s["n"]) if "{n}" in template else template
                ok = land_url(pg, url, "page")
                if not ok:
                    break
                links = link_urls(pg) if "{n}" in template or s["n"] == 0 else []
                for u in sorted(set(links)):
                    if not time_left():
                        break
                    if not land_url(pg, u, "file"):
                        break
                if out["stopped"] != "end":
                    break
                if "{n}" not in template:
                    s["done"] = True
                    continue
                s["empty"] = 0 if links else s["empty"] + 1
                if s["empty"] >= 2:
                    s["done"] = True
                    continue
                s["n"] += PAGE_STEP
            if out["stopped"] != "end":
                break
        b.close()
    conn.close()
    detail = (f"{lane}: {out['requests']} requests, {out['pages']} pages, "
              f"{out['files']} files ({out['new']} new, {out['already']} already held), "
              f"{out['failed']} failed; {out['stopped']}")
    print(detail)
    jobrun.record(f"qv4-{lane.replace('_', '-')}-capture",
                  out["stopped"] == "end", detail, started, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="elections_nz")
    ap.add_argument("--lane", required=True, choices=sorted(LISTINGS))
    ap.add_argument("--budget-s", type=float, default=3600)
    a = ap.parse_args(argv)
    out = run(a.lane, a.budget_s, print)
    return 0 if out["stopped"] == "end" else 1


if __name__ == "__main__":
    sys.exit(main())
