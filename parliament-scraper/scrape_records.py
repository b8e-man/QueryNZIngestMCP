#!/usr/bin/env python3
"""
parliament.nz / beehive current-records tick — written questions, bills,
ministerial diaries.

Diff-based (newest-first): each tick pulls the head of each feed and
records only entries not seen before. No archive backfill — freshness
is the point.

Sources (verified 2026-10-17):
  - Written questions: POST https://questions.parliament.nz/api/data/search
    {pageSize,page} -> OData {pageSize,page,@odata.count,value:[...]}
    Records already carry questionText + replyText (no detail fetch needed).
    Sorted newest-first (WQ_{n}_{year} descending).
    Reachable only via a browser session (Radware WAF) — in-page fetch
    after landing on the API host.
  - Bills: POST https://bills.parliament.nz/api/data/search with the SPA
    body (documentPreset:1, billTab:'Current'). Records carry title,
    status, billCurrentStageName, memberName, lastStageDate.
  - Diaries: ministerdiarysummaries.org.nz Datasette export (no WAF,
    plain urllib). Link-header keyset pagination. Records: minister,
    date, time, meeting, location, attendees, portfolio, source_url.

Silent (empty stdout) when nothing new -> no_agent watchdog cron.
"""

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/opt/data/parliament-scraper")
sys.path.insert(0, str(BASE))
from scrape_pb import ChromiumFetcher, load_json, save_json, now_iso  # noqa: E402

WQ_SEARCH = "https://questions.parliament.nz/api/data/search"
BILLS_SEARCH = "https://bills.parliament.nz/api/data/search"
DIARIES = "https://ministerdiarysummaries.org.nz/ministerial_diaries_public/meetings.json?_shape=array&_size=5000"

BILLS_BODY = {
    "id": None, "documentPreset": 1, "keyword": None, "selectCommittee": None,
    "status": [], "documentTypes": [], "documentSubtypes": [],
    "beforeCommittee": None, "billStages": [], "billTab": "Current",
    "billId": None, "includeBillStages": True, "subject": None, "person": None,
    "parliament": None, "dateFrom": None, "dateTo": None, "datePeriod": None,
    "restrictedFrom": None, "restrictedTo": None, "terminatedReason": None,
    "page": 1, "pageSize": 100, "sortBy": None, "sortDirection": None,
}


def append_jsonl(name, records):
    path = BASE / "data" / name
    with open(path, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def collect_wq(fetcher, state, events):
    """Newest-first pages until hitting a seen record. Max 3 pages/tick.
    Re-records when lastModified changes (replies arrive after lodging)."""
    known = state.setdefault("wq_ids", {})   # id -> lastModified
    new = []
    page = 1
    while page <= 3:
        res = fetcher.evaluate_on_page(
            WQ_SEARCH,
            {"pageSize": 200, "page": page},
        )
        if not isinstance(res, dict) or "value" not in res:
            err = (res.get("__error__") or str(res)[:60]) if isinstance(res, dict) else "no response"
            events.append(f"WQ FETCH FAIL ({err})")   # never silent on failure
            break
        hit_known = False
        for rec in res["value"]:
            did = rec.get("writtenQuestionsDocumentId")
            lm = rec.get("lastModified") or ""
            if did in known and known[did] == lm:
                hit_known = True
                continue
            if did in known:
                hit_known = True      # updated record: re-record but stop paging
            rec["_collected"] = now_iso()
            new.append(rec)
            known[did] = lm
        if hit_known or not res["value"]:
            break
        page += 1
        time.sleep(1)
    if new:
        append_jsonl("wq_records.jsonl", new)
        events.append(f"WQ +{len(new)}")
    return len(new)


def collect_bills(fetcher, state, events):
    res = fetcher.evaluate_on_page(BILLS_SEARCH, BILLS_BODY)
    if not isinstance(res, dict) or "results" not in res:
        err = (res.get("__error__") or str(res)[:60]) if isinstance(res, dict) else "no response"
        events.append(f"Bills FETCH FAIL ({err})")
        return 0
    known = state.setdefault("bills", {})
    new, updated = [], 0
    for rec in res["results"]:
        rid = rec.get("id")
        lm = rec.get("lastStageDate") or rec.get("lastModified") or ""
        if rid not in known:
            rec["_collected"] = now_iso()
            new.append(rec)
            known[rid] = lm
        elif known[rid] != lm:
            rec["_collected"] = now_iso()
            new.append(rec)          # stage changed -> re-record
            known[rid] = lm
            updated += 1
    if new:
        append_jsonl("bills_records.jsonl", new)
        events.append(f"Bills +{len(new)} ({updated} stage-changed)")
    return len(new)


def collect_diaries(state, events):
    """Aggregator export, newest rowids first. Plain urllib (no WAF)."""
    seen = state.setdefault("diary_rowids", [])
    seen_set = set(seen)
    req = urllib.request.Request(DIARIES, headers={"User-Agent": "Mozilla/5.0 (research)"})
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        events.append(f"diaries ERR {str(e)[:40]}")
        return 0
    new = []
    for rec in rows:          # export is newest-first by rowid
        rid = rec.get("rowid")
        if rid in seen_set:
            continue
        rec["_collected"] = now_iso()
        new.append(rec)
        seen.append(rid)
        seen_set.add(rid)
    if new:
        append_jsonl("diaries_records.jsonl", new)
        events.append(f"Diaries +{len(new)}")
    if len(seen) > 400000:
        state["diary_rowids"] = seen[-300000:]
    return len(new)


def main():
    state_path = BASE / "state" / "records_state.json"
    state = load_json(state_path, {})
    events = []

    # diaries first — no browser needed
    collect_diaries(state, events)

    # WQ + bills share one chromium session
    fetcher = ChromiumFetcher()
    try:
        fetcher.start()

        def evaluate_on_page(target, payload):
            page = fetcher.ctx.new_page()
            try:
                # land on the API host (JSON in <pre>, loads instantly)
                page.goto(target, timeout=60000, wait_until="domcontentloaded")
                return page.evaluate(
                    """async (p) => {
                        const r = await fetch(p.url, {method:'POST',
                            headers:{'Content-Type':'application/json'},
                            body: JSON.stringify(p.body)});
                        return await r.json();
                    }""",
                    {"url": target, "body": payload},
                )
            except Exception as e:
                return {"__error__": str(e)[:120]}
            finally:
                page.close()

        fetcher.evaluate_on_page = evaluate_on_page
        collect_wq(fetcher, state, events)
        collect_bills(fetcher, state, events)
    finally:
        fetcher.stop()

    state["_last_tick"] = now_iso()
    save_json(state_path, state)
    if events:
        print("parliament records tick: " + "; ".join(events), flush=True)
    # silent when nothing new


if __name__ == "__main__":
    main()
