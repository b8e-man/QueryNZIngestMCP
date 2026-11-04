# Query NZ Ingest MCP

**What it is:** an MCP server that exposes the *contents* of the NZ
government-publication corpora (Beehive, parliament.nz, courts) — records,
counts, date ranges, freshness, statistics. Records carry their capture
provenance (as-received hash, fetch time, HTTP status) in a `capture` block;
model-made fields are named in an `annotation` block. The consumer sees the
database and how it arrived, not the pipeline's internals.

**Built for full ingestion:** consumers are expected to pull the entire corpus
through this interface. `records` is the bulk feed — stable arrival order,
resumable cursor — and `corpora()` says when fresh records have landed.

**Code canonical:** github.com/b8e-man/QueryNZIngestMCP (`mcp-server/`).
**Live:** `/opt/data/qnz-mcp` (this directory). **Transport:** Streamable HTTP,
`http://<host>:8646/mcp`. Health: `GET /health`.

---

## The tools

1. **corpora()** — inventory. Per corpus: record count, date range, the
   ingestion cursor (= record count; records are appended in stable arrival
   order), `arrivals_last_24h`, `newest_arrival`. This is the freshness
   signal: poll it, and when the count grows, there is new data to pull.

2. **records(corpus, cursor=0, limit=50, include_text=true, doc_type?)** —
   the **bulk-ingestion feed**. Records in stable arrival order (new records
   always land at the end; existing positions never change). `cursor` is how
   many records the consumer already holds; each call returns the next batch
   and `next_cursor`. When `next_cursor == ingest_cursor`, the consumer has
   everything — then poll `corpora()` and resume from the saved cursor to
   pull only what landed since. `include_text=false` gives a metadata-only
   pass. `doc_type` filters to one document type (e.g. `judgment_pdf`,
   `media_release`) on corpora that declare one; the cursor then counts
   within the filtered set. Max 200 records per call.

3. **search(query, corpus?, date_from?, date_to?, limit, offset, doc_type?)**
   — find. Case-insensitive AND over record text; empty query + date filters
   browses. Returns matches with snippets.

4. **get(record_id, corpus?)** — one record in full: the database's own
   fields and text.

5. **measure(keywords, corpora?, measure_kind, ...)** — statistics. Keyword ×
   corpus matrix as count, rate (per 10k words), or salience (weighted
   log-odds with informative Dirichlet prior, z-scored — the statistic that
   stays comparable across corpora of wildly different sizes). Every cell
   carries `n_docs` and a `low_n` flag: small corpora are annotated, never
   hidden. Optional `mint_name` + `mint_threshold` (on count or rate) gathers
   records at/above the threshold into a named subset, searchable as
   `corpus="mint:<name>"` — with every exclusion recorded alongside its value
   and the threshold it failed.

6. **gaps(series?, sample)** — completeness measurement for the courts
   corpus against the NZLII comparison index (NZLII is a COMPARISON source
   only: case IDs as metadata, never content). Per series: comparison-index
   ids, our own corpus-index ids, the difference, and how much of the
   difference has been probed against the official source
   (`not_on_courtsofnz` = verified absent — the JDO back-catalogue
   evidence). Methodology and caveats travel with the numbers.

7. **download(record_id, corpus?, format=raw|text)** — the file itself.
   Returns a meta block (delivered sha256 + size + content type, the capture
   provenance, the record's `seq`) followed by the captured bytes as an
   embedded resource: `format="raw"` serves the bytes exactly as fetched
   (sha256 checked against the capture record); `format="text"` serves
   verbatim `pdftotext -layout` output for PDFs (computed on read, nothing
   stored — same verbatim rule as Hansard). Metered per call.

8. **pipeline()** — the gathering process itself: per capture lane, work
   items still queued, work items completed, the target where the source
   publishes one, and the completion rate over the last 24h — plus the
   recorded discrepancy list (measured differences between what the sources
   report and what is held). Telemetry about acquisition, not contents.
   A blocked lane reports `status: blocked` and nothing else. Lane list is
   `pipeline.yaml`, re-read on every call (edits land without a restart);
   all counts computed live from the pipelines' own queue/manifest files.

## Resources

The same files are readable as MCP resources (files DO leave the box):

- `qnz://readme` — file-delivery conventions (start here)
- `qnz-pdf://<corpus>/<seq>` — captured PDF bytes exactly as fetched
- `qnz-html://<corpus>/<seq>` — captured HTML bytes exactly as fetched
- `qnz-raw://<corpus>/<seq>` — captured bytes of any other type (xlsx, csv…)
- `qnz-text://<corpus>/<seq>` — verbatim text view (pdftotext -layout)

Every record with bytes carries `file_uri` — the exact URI to pass to
resources/read, family chosen by content type (declared `content_type`
first, file extension filling the gap for stores that carry none).
`<seq>` is the record's stable `seq` from `records`/`get`. Scheme must match
the record's family (mismatches error loudly). Corpora that carry
stored bytes advertise it as `has_files` in `corpora()`.

## Schema stability

`corpora()` advertises, per corpus, a **field registry** (`schema.fields`,
the complete list a served record can carry) and `schema_hash`, which moves
whenever the shape does. `records`/`changes` envelopes carry the current
`schema_hash`, so a consumer can detect drift on arrival instead of going
red mid-parse. Where source field names mislead (e.g. GETS notices shaped
like court records), the corpus declares `schema.aliases` (served as extra
fields — `tender_name`, `tender_id` — with the originals kept for
provenance).

## Record shape

Records carry the database's own fields (url/title, dates, ministers,
portfolios, body text, topics, quotes, question/bill/diary/case fields —
whatever the corpus holds) plus `seq` (the arrival-order position — the
cursor anchor) and `id`. Capture provenance (hashes, fetch timestamps, HTTP
status, raw-file paths) is exposed in a `capture` block; model-made fields
are named in an `annotation` block with their generator. `updated_at` moves
when a record is re-processed. Corpora that declare a `path_root` also carry
`file` — the absolute path to the captured bytes on the host (the raw
relative `path` stays exactly as-received).

## Consumer ingestion pattern

```
state = {corpus: cursor}
loop:
  for corpus in corpora():
      if corpus.ingest_cursor > state[corpus.name]:
          pull records(corpus, cursor=state[corpus.name]) until next_cursor == ingest_cursor
          state[corpus.name] = next_cursor
```

One full pass, then incremental forever. Fresh arrivals show up as
`arrivals_last_24h` / a growing `ingest_cursor` in `corpora()`.

## Design rules this server holds itself to

- **The database and its provenance, not the pipeline.** Counts, dates,
  freshness, statistics, as-received capture metadata — never pipeline
  internals or transformations of the source.
- **Nothing is silently absent.** Captured-but-not-yet-enriched documents are
  records too (with their text); thresholds write exclusion audits; unknown
  corpus names error loudly.
- **Measurements, not conclusions.** Statistics arrive with error bars;
  interpretation is the consumer's job.

## Corpus acquisition & operations (2026-11-03)

Method per corpus (crawl / API / bulk / archive), refresh cadence, and the
meaning of each record's `date`. Block behaviour is documented honestly,
including where terms or robots disagree with practice.

- **courts** — JDO JSON API (undocumented `/jdo-search-api`, enumeration),
  courtsofnz case pages, tribunal sites (ERA, HRRT, HPDT, Waitangi, coroners
  — listings + Wayback CDX for history). Capture tick 5 min; JDO backwalk
  complete 2026-11-03 (2005→2026 enumerated). `date` = fetch date; `doc_date`
  = the judgment's own date (parsed from the JDO case name; backfilled
  2026-11-03, covers JDO-era records). Files: byte-exact, `download` serves
  bytes + verbatim `pdftotext -layout` text (computed on read).
- **gets** — GETS public lists (open/closed/awarded) + Wayback CDX for the
  pre-2014 hidden era. Plain browser-UA fetches, 1 req/s. Lists refreshed
  daily; capture tick 5 min. `date` = fetch date; page fields carry `open_date`,
  `close_date`, `award_date` (the document's own dates). Tender documents sit
  behind a free login — **never taken**. NOTE: GETS terms (cl. 3.2(i)(e)) bar
  "any spider or robot"; automated capture proceeds on the operator's
  instruction, disclosed here. MBIE bulk award CSVs are WAF-blocked to all
  automated routes (403 even via real browser + NZ residential IP); Wayback
  fallback is wired and retries daily.
- **beehive** — sitemap/RSS enumeration, body capture via headless Chromium
  through the site's JS WAF challenge (real browser, real UA, residential IP;
  no credentials, no login exists). Collect 2h, bodyfetch 6h, extract 3–5 min.
  `date` = Beehive's own `published_at`.
- **parliament-\*** (written-questions, bills, sops, sc-reports,
  sc-submissions, bills-historical) — parliament.nz JSON API (passes the WAF
  as-is). Queue tick 5 min–1 h. `date` = the API's own field per corpus
  (`lastModified`, `lastStageDate`, `publicationDate`). Known: 17,619 WQ rows
  changed text on 2026-10-27 without `updated_at` moving (source-side drift,
  recorded, not hidden).
- **parliament-hansard-debates** — daily sitting PDFs (parliament resource
  API), `pdftotext -layout` text stored beside the raw PDF (`raw_file`).
  `date` = sitting date. House rose 23 Sep 2026; corrected versions of 35
  days (from 28 Apr 2026) exist only as drafts upstream.
- **parliament-diaries** — ministers' diary releases scraped from Beehive.
  `date` = meeting date. Releases without a PDF address are records-only.
- **parliament-hansard-index** — parliament sitemap pages (URL + lastmod).
- **parliament-wayback** — Wayback CDX + replay of parliament.nz pages.
  `date` = snapshot timestamp. Archive coverage thins after 2016 (source-side).

Block/CAPTCHA/login policy: no logins, no credentials, no CAPTCHA solving.
Where a site serves a JS challenge to non-browser clients (beehive), capture
uses a real browser on a residential IP and is disclosed above. Where terms
or robots restrict crawling (GETS terms; justice.govt.nz `/assets/` +
`/jdo_documents/` robots exclusions), automated access is done on the
operator's explicit instruction at low cadence and disclosed here — a
consumer may exclude such content.

Change feed (`changes`): fresh arrivals + records whose `updated_at` moved,
plus first-class lifecycle **events** from the daily re-verify pass
(06:45): `removed` (suppression/takedown), `content_changed` (byte-level
change, new capture appended as its own record; pages with per-request
tokens are compared semantically so token churn is not a change),
`restored`. A removal is an event, never silence.

## Layout

- `corpora.yaml` — which corpora are mounted, where their files live, date/id
  field mapping (edit to mount a new corpus; no code changes)
- `pipeline.yaml` — the capture lanes behind the corpora (queue/done/target
  sources, blocked lanes, discrepancy facts; read fresh per `pipeline()` call)
- `server.py` — the nine tools (mcp SDK v2, MCPServer, streamable-http)
- `README.md` — this
- runtime state (never committed): `metering.jsonl`, `minted_corpora.jsonl`,
  `server.log`, `.venv/`

## Estate corpora (handover 2026-11-05)

21 corpora `estate-<lane>` hold every document the QueryNZ estate captured
itself from the websites (59,323 docs, 27 GB) — one corpus per estate lane,
named 1:1 with the lane so each lane can switch to reading here. Documents
live at `/opt/data/querynz-estate/sources/<lane>/` (file named by the bytes'
sha256 + `manifest.jsonl` with urls/via, landings, fetched_at). The estate's
gathering code, lane specs, legal positions, lane tables, fetch-gate ledger
and run history sit under `/opt/data/querynz-estate/supplement/` (raw, kept
for provenance — not mounted as corpora).

Config keys added for these (defaults unchanged for all other corpora):

- `file_fields` — ordered row keys that name the retained bytes relative to
  `path_root` (default `[path, raw_file]`; estate manifests use `[file]`)
- `text_fields` — search text built only from these columns (lists/dicts
  flattened). Default is unchanged: all scalar strings in the row
- `title_field` entries may now be paths: `names[0]`, `urls[0].url`

Record `date` for estate corpora is the capture date (`fetched_at`, falling
back to `landed_at`) — the manifests carry no content dates; those live in the
estate's lane tables (supplement/tables/). `download` hashes the delivered
bytes against the capture sha256 and reports `sha256_matches_capture`.
