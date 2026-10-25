# Query NZ Ingest MCP

**What it is:** an MCP server that exposes the *contents* of the NZ
government-publication corpora (Beehive, parliament.nz) — records, counts, date
ranges, freshness, statistics. Nothing about how records were acquired or
processed is exposed: the consumer sees the database, not the pipeline.

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

2. **records(corpus, cursor=0, limit=50, include_text=true)** — the
   **bulk-ingestion feed**. Records in stable arrival order (new records
   always land at the end; existing positions never change). `cursor` is how
   many records the consumer already holds; each call returns the next batch
   and `next_cursor`. When `next_cursor == ingest_cursor`, the consumer has
   everything — then poll `corpora()` and resume from the saved cursor to
   pull only what landed since. `include_text=false` gives a metadata-only
   pass. Max 200 records per call.

3. **search(query, corpus?, date_from?, date_to?, limit, offset)** — find.
   Case-insensitive AND over record text; empty query + date filters browses.
   Returns matches with snippets.

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

## Record shape

Records carry the database's own fields (url/title, dates, ministers,
portfolios, body text, topics, quotes, question/bill/diary fields — whatever
the corpus holds) plus `seq` (the arrival-order position — the cursor anchor)
and `id`. Acquisition and processing metadata (hashes, capture files, fetch
timestamps, snapshot URLs, model names) is internal and never returned.

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

- **The database, not the pipeline.** Counts, dates, freshness, statistics —
  never acquisition or processing internals.
- **Nothing is silently absent.** Captured-but-not-yet-enriched documents are
  records too (with their text); thresholds write exclusion audits; unknown
  corpus names error loudly.
- **Measurements, not conclusions.** Statistics arrive with error bars;
  interpretation is the consumer's job.

## Layout

- `corpora.yaml` — which corpora are mounted, where their files live, date/id
  field mapping (edit to mount a new corpus; no code changes)
- `server.py` — the five tools (mcp SDK v2, MCPServer, streamable-http)
- `README.md` — this
- runtime state (never committed): `metering.jsonl`, `minted_corpora.jsonl`,
  `server.log`, `.venv/`
