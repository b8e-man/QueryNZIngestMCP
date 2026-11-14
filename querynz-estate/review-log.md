# Review log (living)

Last updated: 2026-11-14T21:15Z (UTC). This exercise repeats: every future
pass appends its own dated section below. Keep entries terse — rows, paths,
numbers — no essays.

## Pass 2026-11-14 (started by Kimi K3; completed by mimo after the pass hit
the agent iteration cap mid-pipeline — the two agents' work is joined below)

### Changes made

| what | files | why |
|---|---|---|
| Empty-record root cause fixed: tracker-URL shadowing against Wayback (as-shared URLs with tracking parameters matched only challenge-era snapshots; the ingest now tries the canonical address and lands a terminal row with a named status instead of a bare kind=doc) | parliament-scraper/ingest_wayback_docs.py | estate-parliament-empty-2026-11-15 + improvements practice 1 ("say why a record is empty") |
| Repair run over the 45 empty records: 88 outcome rows — 12 real captures (ok), 76 terminal-with-reason (empty_capture / empty/rc=22 / empty/rc=28 / challenged_snapshot) | parliament-scraper/repair_empty_records.py (new) + data/wayback_docs/documents.jsonl | the 45 copies: ok 12, reasoned terminal 76; every one now states why |
| Diaries rows served with capture sha256 + pdf_fetched_at | parliament-scraper/diary_pdfs_link.py (new) + qnz-mcp server projection | improvements practice 3 ("every file with the hash it was captured by") |
| estate-news: published_at + author extracted from page metadata as printed (article:published_time / datePublished / dateline / byline), landing fill forward | news-scrapers extract path + server projection | improvements practice 4 |
| Server projection lift: wayback rows now served with status + provenance (capture, snapshot_url, html_title, updated_at); diaries with sha256; news with published_at/author | qnz-mcp/server.py | the three fixes surface to the consumer — verified from the live server after restart |
| Sync prune lines: the deleted files are also removed from the repo copy | parliament-scraper/push_to_github.sh | pruning is incomplete without deleting from the clone |

### Issues found, not changed

| issue | reason / what a decision needs |
|---|---|
| Dunedin/Gisborne/Kaipara registers of interests: this box gets 403s like the consumer's sessions do — "our session is no better than theirs". No workaround taken, per the refusals ruling (diagnose once, hold, never route around) | outcome to report in the improvements reply: those three stay held-blocked until a ruling changes it |
| bdm-historical-scraper cron sat PAUSED 25 days with last_status=error | decision for Arthur (retire vs fix) — flagged, no action |
| parliament-wayback row shape: the repaired terminal rows are a documented second shape. Full single-shape unification needs the consumer to pre-register the shape change first (their own practice 2) | open decision for their side; ours is named via status field |
| nzme-archive-backfill cron paused | deliberate (estate ruling), left paused |

### Duplicates resolved

- DELETED /opt/data/querynz-estate/collect_lottery_records.py — superseded by
  the stealth surface in runtime/stealth_fresh.py (communitymatters 403s plain
  fetchers; the stealth lane is the working route). Zero references, zero cron.
- DELETED /opt/data/news-scrapers/ingestion/scripts/estate_media_1114_probe{,2,3,4}.py
  — stale probe leftovers superseded by estate_media_1114_run.py. Zero refs.
- Cron audit (55 jobs, read-only): court_scraper_tick.sh/_b.sh and
  beehive_extract.py/_b.sh are DOCUMENTED staggered twins (same queue,
  offset phase, flock) — deliberately not merged. beehive's 6 jobs are
  distinct stages (collect/bodyfetch/backfill/extract/enum/watchdog), not
  duplicates. No redundant services found beyond the two above.

### Candidates left

- None actionable this pass; the staggered twins and fleets look superficially
  duplicated but carry distinct phases/queues. Next pass should re-check after
  tonight's three build jobs (21:00/22:00/23:00 UTC) land their scripts.

### Verification

- py_compile: server.py, repair_empty_records.py, diary_pdfs_link.py — all clean.
- Server restart sequence: qnz_mcp_watchdog restarted the server at 21:00:50;
  health green 21:11:15 (corpora=40). The earlier "restart FAILED" record was
  the documented load-window false alarm (2 s after start) — no second restart
  was started, per doctrine.
- Served surface over JSON-RPC on the restarted instance: parliament-wayback
  rows carry status + capture + snapshot_url + html_title + sha256 +
  updated_at; parliament-diaries rows carry sha256 + pdf_fetched_at;
  estate-news newest rows carry real published_at + author (1news.co.nz
  samples). All three fixes verified consumer-side.
- Repair rows: 88 append-only outcome rows in documents.jsonl; no existing
  rows edited (ledger intact at 38,813 manifest rows / 78,111 document rows).
- push_to_github.sh: "pushed" (deletions + fixes in the repo).

### Incidents / lessons for the next pass

1. Pass 1 (19:54) was killed silently when the gateway restarted for the model
   switch — an orphaned `hermes chat -q` dies of SIGPIPE once its stdout
   target goes away UV ~ that spawned CLI runs MUST redirect output to a file.
2. Pass 2 hit the Hermes agent iteration cap mid-pipeline (exit 134), leaving
   the SIGKILL-restart of the MCP server unverified.
3. Watchdog masking chain: the pass's own orphaned health-poller's cmdline
   carried the literal "qnz-mcp/server.py" text, so the watchdog's pgrep saw
   it and wrote "process up but health down" instead of restarting — the
   documented pgrep self-match trap three times over (pass poller, then my own
   diagnostic wrappers). Fixing the mask: kill orphans by explicit PID AND
   bracket pgrep patterns ([s]erver) in every diagnostic wrapper.
4. False-alarm discipline: when the watchdog logs "was down and restart
   FAILED" seconds after a restart, that is the minutes-long corpus load —
   poll /health, never start a second instance.
