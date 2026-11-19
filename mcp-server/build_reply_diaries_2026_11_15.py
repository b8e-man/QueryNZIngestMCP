#!/usr/bin/env python3
"""hermes-diaries@2026-11-15 report body (ministers-diaries section of
estate-current@2026-11-14). Mangle-safe: no scheme-ful URL literals, json round
trip, verify from disk before posting."""
import json
import os

OUT = "/opt/data/qnz-mcp/replies"
os.makedirs(OUT, exist_ok=True)

# re-read the ledger to assert the numbers we report
import csv
_rows = list(csv.DictReader(open("/opt/data/parliament-scraper/data/diary_release_list.csv")))
n_sep = sum(1 for r in _rows if r["months"] == "2026-09")
n_oct = sum(1 for r in _rows if r["months"] == "2026-10")
n_ok = sum(1 for r in _rows if r["retained"] == "ok")
n_sha = sum(1 for r in _rows if r["release_sha256"])
assert len(_rows) == 2587, len(_rows)
assert (n_sep, n_oct) == (20, 7), (n_sep, n_oct)
assert n_ok == 2587 and n_sha == 2587

BODY = {
    "kind": "report",
    "request_id": "hermes-diaries@2026-11-15",
    "reply": "Re: estate-current@2026-11-14 (ministers-diaries section). Sep/Oct 2026 capture, the 119-error refetch, the not-fetched queue and the sha256 field all executed today; results below.",
    "sep_oct_capture": {
        "enumerated_from": "the beehive ministerial_diary facet listing (global, current-government scope), 28 listing pages walked to exhaustion",
        "september_2026": 20,
        "october_2026": 7,
        "november_2026": 0,
        "total_landed": 27,
        "landed_as": "each PDF byte-exact into diary_pdfs/ plus an ok row in diary_pdfs_manifest.jsonl carrying sha256, fetched_at and diary_month; 27 fetched, 0 errors, 0 non-PDF",
        "meeting_rows_note": "the aggregator that parses meeting rows still tops out at 2026-08-31 (it publishes roughly two months behind); the 27 releases therefore land with meeting_rows=0 today and their parsed meeting rows will flow in when that source publishes September and October. October 2026 is the newest month the listing serves as of 2026-11-14, so nothing later exists yet.",
    },
    "error_119": {
        "verdict": "all 119 already resolved before this run - nothing left to refetch",
        "detail": "the 119 retention=error rows are bare-filename source_urls (an upstream schema gap, not dead links). The manifest already holds an ok row (resolved_from) for every one, with the PDF on disk and a sha256. So all 119 flip to ok with zero failures.",
        "flipped": "119/119 error -> ok",
        "failures": 0,
        "reason_column": "left empty - no failures to name",
    },
    "notfetched_1156": {
        "verdict": "all 1156 already retained before this run - the CSV was stale, not a real gap",
        "detail": "the release CSV was generated 2026-11-03 12:17 before the PDF fetch finished at 15:21; every one of the 1156 'not-fetched' rows already has a manifest ok entry and its bytes on disk (verified 1156/1156).",
        "queue_file": "/opt/data/parliament-scraper/data/diaries_notfetched_queue.jsonl",
        "done": 1156,
        "remaining": 0,
    },
    "sha256_field": {
        "release_sha256": "added to every diary_release_list.csv row (2,587 rows) as the sha256 of the retained PDF bytes; verified 2,587/2,587 match the on-disk files",
        "meeting_rows": "all 208,464 diaries_records.jsonl rows already carry the sha256 of their release PDF; verified 208,464/208,464 match the manifest",
        "status": "backfilled for all retained releases",
    },
    "ledger_now": {
        "releases": 2587,
        "retained_ok": 2587,
        "error": 0,
        "not_fetched": 0,
        "latest_diary_month": "2026-10",
    },
    "notes": "Append-only throughout: existing CSV rows were edited only in the two designated fields - retained (error/not-fetched -> ok) and release_sha256 - and nothing in pdf_url/file/ministers/months/meeting_rows was changed. The 27 new releases were appended as new rows. A backup of the prior CSV is kept at data/diary_release_list.csv.bak-20261114.",
}

blob = json.dumps(BODY, indent=1, sort_keys=True)
assert "://" not in blob, "scheme literal leaked"
path = os.path.join(OUT, "hermes-diaries@2026-11-15.json")
with open(path, "w") as f:
    f.write(blob)
chk = json.load(open(path))
assert "://" not in json.dumps(chk), "disk copy mangled"
assert chk["reply"].startswith("Re: estate-current@2026-11-14"), "reply header wrong"
print("built + verified", path, len(blob))
