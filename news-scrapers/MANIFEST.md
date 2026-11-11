# Old news scrapers, for the website-crawl provider

Step 9.1 (rulings 152, 156). Made 9 November 2026 by the integrator session.

- Source: the reference copy of the old repository, `/home/user/qnz3-ref`,
  at commit 8c5d163767d6749a4eaa2a9cef81bf1ae36c5067 (clean for these
  paths). Never the live folder.
- 156 files, each listed with its sha256 in `SHA256SUMS` (run
  `sha256sum -c SHA256SUMS` in the unpacked folder). Paths are as in the
  old repository.
- Chosen by file name and pattern search, not by reading. The
  documentation is included and was not read.

## What is in it

- `ingestion/newsscrapers/`: every scraper, with its base, registry,
  runner and browser fetch.
- `ingestion/news/`: the news lane's extract and ledger helpers.
- `data-layer/news_canonical/`: the article store, fetcher, migrations,
  its systemd units and its two docs.
- `ingestion/retired/news_*.py`: the retired news clients, kept for
  reference.
- `ops/systemd/`: the newsscrapers, newsscrapers-daily and
  nzme-archive-backfill units and drop-ins.
- `schema/incoming_news.sql`; four tests under `ingestion/tests/`;
  `ingestion/SCRAPER_ARCHETYPES.md`, `ingestion/SCRAPER_PATTERN.md`,
  `docs/records/v2-heritage/SCRAPERS.md`.

## Left out

- `ops/systemd/newsscrapers.env.example`: an env file (hard limits 1, 2;
  Arthur, 9 November: leave them out). The units name their
  `EnvironmentFile` by path only; the provider supplies its own.
- No credential was found in the 156 files. A scan for connection strings
  with passwords, password, token and key literals, private keys and cloud
  keys matched four lines, all reading the environment, not storing a
  value.
- Not scrapers, so not packed: Papers Past tools (limit 17), suppression,
  article embedding, the claim graph and evaluation scripts.

## For Arthur

- `nbr.py` and `newsroom.py` read a login from the environment. Hard
  limit 6 (never use a login that is not ours) applies to whoever runs
  them.
