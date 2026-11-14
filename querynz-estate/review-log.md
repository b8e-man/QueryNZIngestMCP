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

## Pass 2026-11-15 (mimo): rearchitecture, on Arthur's "take the learnings
you like and rearchitect as you see fit"

### Changes made

| what | files | why |
|---|---|---|
| Index core extracted from server.py into a dependency-light module | qnz-mcp/index.py (new, 595 lines) from server.py (1,727 -> 1,213) | the loader/seq semantics are the contract's heart and were untestable inside the monolith; split is the seam the next changes forced (compaction, fail-loud, tests all live there) |
| Sidecar compaction at load (log -> effective state, atomic replace, seqs preserved) | index.py | sidecars are append-only logs with last-line-per-id semantics; parliament-diaries' had drifted to 3x effective (625,392 -> 208,464 lines compacted at first boot). State 182MB -> 151MB |
| Fail-loud field resolution | index.py | id_field matching no row + no url now REFUSES to load (was: silent content-hash ids - the documented pitfall); id/date gaps warn loudly. All 40 real corpora pass clean (0 warnings) |
| Per-corpus load timing to server.log ([load] lines) | index.py | the 9-minute startup was unattributed; now every boot reports where time goes |
| Same-size-rewrite detection fixed (content sample: head/mid/tail fingerprint) | index.py | LATENT BUG FOUND: this FS returns identical st_mtime values for rewrites within one second, so a same-size same-second rewrite of a record file was invisible to the rebuild gate - silently stale index (measured 2026-11-15). Now caught by st_mtime_ns + a 3x256-byte sample |
| Index contract battery (15 checks: seq stability, arrival order, tailing, dupe enrichment, compaction equivalence, fail-loud, glob re-expansion, capture/annotation blocks) | qnz-mcp/tests/test_index.py (new) | the served contract now has executable truth; plain asserts, no SDK, runs in ~1s |
| Test seams (state_dir, compact_min_lines config knobs, defaults unchanged) | index.py | tests run against a sandbox without touching live state |

### Verification

- 15/15 contract tests pass; py_compile clean on all touched files.
- Ship proof against the live instance: 40 corpora, schema_hash for every
  corpus IDENTICAL pre/post restart, no record count shrank, live appends
  continued through the window (+44), get/records/changes round-trips OK.
- Load: kill 23:06:21 -> healthy 23:14:23 (8:21 wall incl. watchdog pickup);
  actual load ~4.2 min summed from [load] lines vs ~8-9 min on the old code.
  Hot spots now named: parliament-wayback 74.9s (docs pass), written-questions
  33.6s (683K rows), beehive 20.3s.
- Zero WARN lines on the real boot: all 40 corpus field configs are honest.

### Issues found, not changed

| issue | reason / next |
|---|---|
| parliament-wayback docs pass (74.9s) reads page files + strip_html at boot | lazy text extraction would cut it further; deferred - measured, not guessed at |
| written-questions sidecar (683K lines) cannot compact (1:1 with ids) | append-only single-touch corpus; nothing to compact - the cost is the parse, not the log |
| server.py remains 1,213 lines (tools + file delivery + channel) | three cohesive jobs left together deliberately; the next forced seam is file delivery if download/resources grow |
