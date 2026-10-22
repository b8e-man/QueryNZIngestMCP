# QueryNZIngestMCP

Query NZ data-acquisition pipelines and ingest tooling.

## Components

- `parliament-scraper/` — parliament.nz record capture:
  forward sitemap/Hansard diff, POST-API corpora (written questions, bills,
  books, SOPs, estimates, ur-debates) with cursor-resumable queue ticks, and
  a Wayback historical harvest (~51K legacy /en/ URLs incl. removed documents,
  Radware-stub filtered, gzip-aware raw capture). See
  `parliament-scraper/README.md` for the full source map and pitfalls.

Te reo `/mi/` mirrors are deliberately excluded from capture scope.
