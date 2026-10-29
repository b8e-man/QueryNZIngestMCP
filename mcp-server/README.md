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

## Resources

The same files are readable as MCP resources (files DO leave the box):

- `qnz://readme` — file-delivery conventions (start here)
- `qnz-pdf://<corpus>/<seq>` — captured PDF bytes exactly as fetched
- `qnz-html://<corpus>/<seq>` — captured HTML bytes exactly as fetched
- `qnz-text://<corpus>/<seq>` — verbatim text view (pdftotext -layout)

`<seq>` is the record's stable `seq` from `records`/`get`. Scheme must match
the record's content type (mismatches error loudly). Corpora that carry
stored bytes advertise it as `has_files` in `corpora()`.

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

## Layout

- `corpora.yaml` — which corpora are mounted, where their files live, date/id
  field mapping (edit to mount a new corpus; no code changes)
- `server.py` — the eight tools (mcp SDK v2, MCPServer, streamable-http)
- `README.md` — this
- runtime state (never committed): `metering.jsonl`, `minted_corpora.jsonl`,
  `server.log`, `.venv/`
