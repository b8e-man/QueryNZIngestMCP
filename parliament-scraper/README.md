# parliament.nz scraper

Forward + historical capture of parliament.nz records. Record level, raw only.

## Streams (all cron no_agent, silent on success)

1. **Forward diff** (`scripts/parliament_scraper_tick.sh`, hourly): sitemap
   tail diff + Hansard daily PDFs (tier 1, WAF-exempt) + budgeted tier-2 page
   capture + `scrape_records.py` current-records diff (WQ/bills/diaries).
2. **API queue** (`scripts/parliament_api_queue.sh`, every 5m): drains the
   POST corpora — questions 683K (full Q+A texts), ur-debates 125 pages,
   estimates 54, SOPs 114, books 775, bills 92. Cursor state in
   `api_queue_state.json`; output `data/api_queue/{corpus}.jsonl`.
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

The GitHub repo b8e-man/parliament-scraper was pushed from a machine with
SSH keys (commit 92c1721). This runtime has no GitHub credentials — files
here are the live versions the crons execute; sync them when credentials are
available.
