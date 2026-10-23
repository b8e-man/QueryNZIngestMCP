# Query NZ Ingest MCP

**What it is:** an MCP server over the NZ government-publication corpora (Beehive,
parliament.nz). The first *consumer-facing surface* of the Query NZ data plane — the
"niche MCP server" delivery from the platform notes: tools return **records and
measurements with confidence signals, never conclusions**. The moat is the corpus;
the protocol is just the door.

**Code canonical:** github.com/b8e-man/QueryNZIngestMCP (`mcp-server/`).
**Live:** `/opt/data/qnz-mcp` (this directory). **Transport:** Streamable HTTP,
`http://127.0.0.1:8646/mcp`. Health: `GET /health`.

---

## ELI5 — the pieces

- **corpora.yaml** — the *control plane*. Which corpora are mounted, where their files
  live, what counts as their date/title/id, how fresh they should be. Change this file
  to mount a new corpus; no code edits.
- **server.py** — the *data plane reader*. It holds the five primitives and nothing
  else. It reads the scrapers' output files read-only and re-reads them when they
  change. It never writes to scraper data.
- **metering.jsonl** — one line per tool call (what was asked, how many results, how
  long). Per-call metering is the billing foundation: not per-seat.
- **minted_corpora.jsonl** — the *audit trail for thresholds*. Every subset a threshold
  creates records every record it excluded and why. Thresholds never drop silently —
  this is the platform's invisible-false-negative concern made mechanical.

## The five primitives

Each declares its type: **READ** (records → records), **REDUCER** (records →
statistics), **ROUTER** (records → named subset).

1. **corpora()** — READ. Manifest of mounted corpora with integrity signals:
   record counts, search coverage, extraction yield, null-date rate (slot-fill), last
   record + freshness SLA. Read this first: it is the error bars for everything else.
   (Family B riding alongside every content read.)
2. **search(query, corpus?, date_from?, date_to?, limit, offset)** — READ. Case-insensitive
   AND search over title + body. Covers **extracted and un-extracted captures alike**
   (raw page bodies are indexed), so nothing is silently absent from results. Every hit
   carries a provenance block (URL, sha256, capture file, snapshot URL, extraction model).
3. **get(record_id, corpus?)** — READ. One record in full, raw, unsummarised, with its
   provenance chain and extraction (topics/quotes/model) or `extraction: null`.
4. **recent(since, corpus?)** — READ (delta). Records with date ≥ since — the
   intake-monitoring shape ("recompute on change" family).
5. **measure(keywords, corpora?, measure_kind, ...)** — REDUCER, optionally ROUTER.
   Keyword × corpus matrix with the three measures kept separable (IDEA-001 §3):
   - `count` — raw occurrences
   - `rate` — occurrences per 10k corpus words
   - `salience` — weighted log-odds vs the rest, with an informative Dirichlet prior
     (Monroe, Colaresi & Quinn 2008), z-scored. *Prior strength in corpora.yaml is
     Slider A generalised; `source_weights` is Slider B* — a human judgement layer,
     always surfaced in output as `judgement_weight`, never mixed into the statistic.
   Every cell carries `n_docs` and a `low_n` flag. Small corpora are annotated,
   **never hidden**.
   - **Minting (ROUTER):** `mint_name` + `mint_threshold` (on count|rate) gathers
     records at/above the threshold into a named subset, searchable as `corpus="mint:<name>"`.
     The mint record stores the definition, every included id, and every exclusion with
     the record's value and the threshold it failed. This is Plane A output-gating:
     threshold-gathered selections that can feed downstream service contracts.

## Consumption (e.g. from Hermes)

```yaml
mcp_servers:
  query_nz:
    url: "http://127.0.0.1:8646/mcp"
```

Tools register as `mcp_query_nz_<tool>`. `timeout: 180` recommended for `measure`
over large corpora.

## Design rules this server holds itself to

- **Never conclusions.** Outputs are records, counts, rates, z-scores, flags.
  Relevance, guilt, significance — downstream consumers' business.
- **Never silent loss.** Coverage gaps, extraction yield, null rates are reported with
  the reads; thresholds write exclusion audits; unknown corpus names error loudly.
- **Provenance on every record.** sha256, source URL, capture timestamp, capture file,
  extraction model — the chain is part of the payload.

## Layout

- `corpora.yaml` — control plane (edit to mount corpora)
- `server.py` — the primitives (mcp SDK v2, MCPServer, streamable-http)
- `README.md` — this
- runtime state (never committed): `metering.jsonl`, `minted_corpora.jsonl`, `.venv/`
