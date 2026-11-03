# parliament.nz scraper

Forward + historical capture of parliament.nz records. Record level, raw only.

## Streams (all cron no_agent, silent on success)

1. **Forward diff** (`scripts/parliament_scraper_tick.sh`, hourly): sitemap
   tail diff + Hansard daily PDFs (tier 1, WAF-exempt) + budgeted tier-2 page
   capture + `scrape_records.py` current-records diff (WQ/bills/diaries).
2. **API queue** (`scripts/parliament_api_queue.sh`, every 5m): drains the
   POST corpora — questions 683K (full Q+A texts), ur-debates 333K,
   estimates, SOPs, books, bills 92. **OFFSET CAP: the API 500s on any
   query past offset ~100,100 regardless of page size** — corpora over the
   cap are drained year-sharded via dateFrom/dateTo (verified filter),
   deduped by record id. Cursor state in `api_queue_state.json`; output
   `data/api_queue/{corpus}.jsonl`.
   Bills require the FULL SPA body shape (simple `{"page","pageSize"}` is
   rejected with totalResults -1).
3. **Wayback historical** (`scripts/parliament_wayback.sh`, every 5m +
   `scripts/parliament_wayback_enum.sh`, daily 06:00): the sitemap omits all
   per-document records; Wayback's CDX index holds 51,112 /en/ URLs —
   including the entire legacy site (en-NZ paths, 00HOH... document IDs:
   submissions called, old bill docs, Speaker speeches). Te reo /mi/ mirrors
   deliberately excluded. Queue `wayback_queue.jsonl`; output
   `data/wayback_docs/{documents.jsonl,manifest.jsonl,pages/}`.
   Per URL: snapshot list via CDX, NEWEST snapshot with REAL content saved
   (raw bytes verbatim), metadata rows for every snapshot examined.

## Wayback pitfalls (learned 2026-10-22 — do not re-learn)

- Wayback's own crawler gets Radware-challenged: post-challenge-era snapshots
  are 118KB 'Radware Page' stubs. Classify + skip them
  (status=challenged_snapshot); pre-challenge-era captures are real HTML.
- `id_` captures preserve original Content-Encoding — bodies may be gzip.
  Analyze after decompressing; store the raw bytes as-is (record
  content_encoding).
- urllib gets spurious 429s from web.archive.org where curl gets 200 —
  downloads use curl (`-sf`). 429s are not helped by the proxy; just back off.
- Display-truncated URLs break exact-URL CDX lookups (they return []) —
  always enumerate with prefix queries; never reconstruct URLs from logs.
- CDX has a 50K row cap per query — year-slice with collapse=urlkey.

## WAF / transport summary

- Radware Bot Manager on HTML; `.pdf`/`.xml` bypass entirely. VPS IP and
  IPRoyal residential exits both get captcha'd on HTML paths currently —
  budgeted tier-2 (2-3 pages/tick, backoff) is the live-page strategy.
- searches.parliament.nz + bills.parliament.nz TCP-ban the IP under burst
  (curl 000); questions.parliament.nz tolerated the queue traffic. Be
  polite: 0.8s between API calls, cursored resumable ticks.

## Git note

Canonical repo: **github.com/b8e-man/QueryNZIngestMCP** (this code lives in
its `parliament-scraper/` subdir). This directory is the live execution copy
the crons run from — intentionally NOT a git checkout. After editing code
here, run `bash push_to_github.sh` to commit+push (standing git rule).
Credential store: /opt/data/shared/.gitcreds (600). The fine-grained PAT
cannot delete or push repos outside its access list — new repos must be
added to the PAT's selection before it can manage them.

## Document download API (2026-11-03)

Cracked from the WASM client assemblies (string-hunt, UTF-16 literals):

- detail:   `bills.parliament.nz/api/data/{type}/{id}` — types: `paper`,
  `selectcommitteereport`, `amendmenttobill` (SOPs), `bill`, `oralquestion`,
  `petition` (validated enum — 400 body names invalid values)
- bytes:    `bills.parliament.nz/download/{folder}/{attachmentId}` → PDF.
  Valid folders: amendmenttobill, bill, paper, selectcommitteereport,
  oralquestion, petition. AttachmentIds come from the detail APIs
  (papers: `Attachments[]`; sc-reports: top-level `AttachmentId`).
- `parliament_docs_fetch.py` drains sc-reports + papers via cron
  (manifest: `data/doc_pdfs_manifest.jsonl`, sha256 each). SOP detail
  exposes no `Attachments` (empty for all samples) — SOP PDF bytes unresolved
  (likely legislation.govt.nz — `BillLegislationUrl` on detail).
- sc-evidence (preset 11, 1.1M rows) + sc-submissions carry page URLs
  (`/en/pb/sc/submissions-and-advice/document/...`) but no attachment ids —
  bytes need the SPA route (Blazor WASM won't boot: Radware mangles the ICU
  .dat → SRI integrity fails at 98%; same on www + hansard).
- WQ attachments (44,584 rows with `attachmentId` GUIDs): route
  `/download/wq/{guid}` exists on questions.parliament.nz (validation-typed
  GUID) but neither attachmentId nor question id resolves (56s-then-404).
  Full Q+A text already in the corpus; attachments are supplementary tables.
- Papers (preset 2): 39,050/39,053 captured. Discrepancy: 3 rows unreachable
  — the full-scan page 40 persistent-500s server-side (routed around with a
  date-shard tail), and 3 undated rows sit on that dead page excluded from
  every date shard. Sort params ignored; no other query dimension reaches
  them. Recorded as-is.
- Preset map: 2=Paper(39,053) 11=Bills-SC-Evidence(1,111,490!) 12=Debate
  (24,740 — thin metadata only) 13=HouseVideo(83,298). Debate/HouseVideo
  rows carry no urls or text; hansard.parliament.nz serves per-speech HTML
  but is Radware+hCaptcha (standing rule: never cross) — per-speech HTML
  comes via the Wayback lane (`pb/hansard-debates` 4,772 queued, 331+
  ingested; batch drains ~25/5min).
- Pre-2003 (WQ/Hansard): Wayback holds ZERO pre-2000 captures of
  parliament.nz. Not recoverable from open web archives → institutional ask
  territory (Parliament library / Turnbull / Archives NZ), like BDM.

