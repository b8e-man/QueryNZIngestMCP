#!/usr/bin/env python3
"""GETS (Government Electronic Tenders Service) discovery.

Walks the three public lists on gets.govt.nz (open / closed / awarded),
extracts tender detail page URLs + row metadata, dedupes against
queue.jsonl/done.jsonl, appends to queue.jsonl.

Capture-only lane: byte-exact detail pages via gets_capture.py. No login
(search + attachments sit behind free registration; untouched).

Canonical detail URL: https://www.gets.govt.nz/ExternalTenderDetails.htm?id=N
(agency-prefixed variants 302-redirect; always canonicalise.)

Budget-aware (cron hard-kills ~120s). State: state/lists_state.json
{"done_pages": {"<list>:<page>": true}} — pages already walked are skipped
on the next run; list totals shift slowly so re-walking is cheap anyway.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

BASE = "/opt/data/gets-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "state", "lists_state.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SLEEP = 1.0  # politeness between requests

LISTS = {
    "open": "https://www.gets.govt.nz/ExternalIndex.htm?page={p}&orderBy=date",
    "closed": "https://www.gets.govt.nz/ExternalClosedTenderList.htm?page={p}",
    "awarded": "https://www.gets.govt.nz/ExternalAwardedTenderList.htm?page={p}",
}

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
ID_RE = re.compile(r"ExternalTenderDetails\.htm\?id=(\d+)")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def cells(row_html):
    """Visible cell texts of one table row (metadata classification)."""
    out = []
    for td in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S | re.I):
        t = re.sub(r"<[^>]+>", " ", td)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t)
    return out


def parse_rows(html):
    """-> dict rfx_id -> row metadata from one list page."""
    found = {}
    for row in ROW_RE.findall(html):
        m = ID_RE.search(row)
        if not m:
            continue
        rfx = int(m.group(1))
        if rfx in found:
            continue
        c = cells(row)
        # known column order: RFx ID | Reference # | Title | Tender Type |
        #                     Close Date | Organisation
        meta = {"title": "", "reference_no": "", "tender_type": "",
                "close_date": "", "buyer_org": ""}
        if len(c) >= 6:
            meta["reference_no"] = c[1] if c[1] not in ("[None]", "None") else ""
            meta["title"] = c[2]
            meta["tender_type"] = c[3]
            meta["close_date"] = c[4]
            meta["buyer_org"] = c[5]
        elif len(c) >= 2:
            meta["title"] = c[1] if len(c) > 1 else c[0]
        found[rfx] = meta
    return found


def load_known():
    known = set()
    for path in (QUEUE_F, DONE_F):
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                u = r.get("url", "")
                m = ID_RE.search(u)
                if m:
                    known.add(int(m.group(1)))
    return known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=250,
                    help="max pages per list (25/page)")
    args = ap.parse_args()
    t0 = time.time()
    deadline = t0 + args.time_budget

    os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
    state = {}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except ValueError:
            state = {}
    done_pages = state.get("done_pages", {})

    known = load_known()
    added_total = 0
    walked = 0
    fails = []

    for name, tmpl in LISTS.items():
        empty_streak = 0
        prev_ids = set()
        for p in range(1, args.max_pages + 1):
            if time.time() > deadline:
                break
            key = f"{name}:{p}"
            if key in done_pages and name != "open":
                # re-walk pages after 6 days so in-place list changes on
                # already-walked pages are eventually seen
                from datetime import datetime, timezone
                try:
                    walked_at = datetime.fromisoformat(done_pages[key])
                    age_h = (datetime.now(timezone.utc) - walked_at).total_seconds() / 3600
                    if age_h < 144:
                        continue
                except (TypeError, ValueError):
                    pass
            try:
                st, body = fetch(tmpl.format(p=p))
                if st != 200:
                    fails.append(f"{name} p{p}: http_{st}")
                    break
                html = body.decode("utf-8", errors="replace")
                rows = parse_rows(html)
                page_ids = set(rows)
                if not rows or (page_ids == prev_ids and prev_ids):
                    empty_streak += 1
                    if empty_streak >= 2:
                        break  # list end, or page=N clamps to a repeat
                else:
                    empty_streak = 0
                prev_ids = page_ids
                new = 0
                for rfx, meta in rows.items():
                    if rfx in known:
                        continue
                    known.add(rfx)
                    rec = {
                        "url": (f"https://www.gets.govt.nz/"
                                f"ExternalTenderDetails.htm?id={rfx}"),
                        "source": f"gets_list:{name}",
                        "rfx_id": rfx,
                        "court": "gets",
                    }
                    rec.update({k: v for k, v in meta.items() if v})
                    with open(QUEUE_F, "a") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    new += 1
                added_total += new
                walked += 1
                from datetime import datetime, timezone
                done_pages[key] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                time.sleep(SLEEP)

            except Exception as e:
                fails.append(f"{name} p{p}: {str(e)[:80]}")
                empty_streak += 1
                if empty_streak >= 3:
                    break

    state["done_pages"] = done_pages
    with open(STATE_F, "w") as f:
        json.dump(state, f)

    msg = f"GETS lists: pages={walked} added={added_total} queue_known={len(known)}"
    if fails:
        msg += f" fails={len(fails)} ({'; '.join(fails[:3])})"
    print(msg)
    # watchdog semantics: silent (exit 0) when nothing new and no failures
    return 0


if __name__ == "__main__":
    sys.exit(main())
