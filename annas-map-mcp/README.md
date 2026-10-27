# Anna's Archive Map (annas-map-mcp)

A map of NZ-relevant books in the LibGen compact catalog. **Standalone MCP —
deliberately not part of the Query NZ (qnz-mcp) service.** Own port, own
database, own tool surface. Metadata only; no book content is served.

## Source

- Internet Archive metadata snapshot `libgen-meta-20230113`
  (https://archive.org/download/libgen-meta-20230113/), LibGen compact
  catalog as of 2023-01-13.
- `libgen_compact.rar` (415 MB) → `libgen_compact.sql` (2.06 GB) →
  `dumps/libgen.db` (SQLite, 3,600,823 rows, table `books`).
- Ingested raw with no transformation (`ingest_libgen.py`). Requires the
  official RARLAB `unrar` (durable at `/opt/data/tools/unrar/unrar`).

## The NZ map (`match_nz.py` → table `nz_map`)

Scored selection where every row stores the signals that selected it —
the filter's decisions are inspectable, never silent.

- **Pass 1 — direct evidence (score >= 3):** NZ publisher, "New Zealand" /
  "Aotearoa" in title/series, te reo marker (word-bounded), distinctive
  NZ city.
- **Pass 2 — known authors:** exact normalized author match against authors
  with a repeated NZ publication footprint (>= 2 NZ-published pass-1 rows,
  person-like names, placeholder/org blocklist). Substring author matching
  was tried and rejected: it floods the map with namesakes (measured).
- **Pass 3 — single-signal (score 2):** one distinctive city or te reo
  marker alone. Kept as its own tier so weak-but-real evidence is
  inspectable, not invisible.

Signal dictionaries (publishers, cities, te reo markers) live at the top of
`match_nz.py`. Foreign place-name collisions (Nelson, Hamilton, Canterbury,
Thames, Stratford, Eltham...) are weak signals and never count alone; one
place name never fires both city tiers.

Known limits are reported by the `stats()` tool (`filter_limits`) — the map
states what it would miss (e.g. NZ authors with no metadata signal at all
are invisible; catalog is a 2023-01-13 snapshot).

## MCP server (`server.py`, Streamable HTTP on 0.0.0.0:8647/mcp)

- `stats()` — inventory: catalog/map counts, tier and signal counts, limits.
- `search(query, signal, min_score, pass_tier, year_from, year_to, cursor,
  limit)` — map search, every row carrying its signals.
- `get(id)` — one map row with signals.
- `lookup(id)` — raw unfiltered catalog row (verification path).
- `census(field)` — value counts over the map (measurements, not opinions).
- `/health` — liveness + counts.

Every call is metered to `metering.jsonl`.

## Run

    /opt/data/annas-map-mcp/.venv/bin/python /opt/data/annas-map-mcp/server.py

Rebuild the map: `match_nz.py`. Re-ingest from scratch: `ingest_libgen.py`
(after extracting the RAR with the RARLAB unrar).
