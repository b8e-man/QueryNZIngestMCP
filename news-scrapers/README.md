# News scrapers — working state (2026-11-09)

For the channel: each fix, its evidence, and the build; the unbuildable, stated
plainly. The source is the handed-over pack (`news-scrapers-2026-11-09.tar.gz`,
156 files, checksums verified against `SHA256SUMS` — the pristine reference
copy stays in `/opt/data/cache/drive-in/`). This checkout at
`/opt/data/news-scrapers/` is the working tree that runs.

## Quick start

```bash
cd /opt/data/news-scrapers/ingestion
../.venv/bin/python -m newsscrapers.run --status            # readiness report
../.venv/bin/python -m newsscrapers.run --dry --hours 168 --limit 2
../.venv/bin/python -m newsscrapers.run --hours 168 --limit 30   # real landing
PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright ../.venv/bin/python \
    -m newsscrapers.run ...                                  # browser-lane sources
```

## What landed (first landing sweep, 2026-11-09)

**852 landed across 58 sources** (29 thin, 0 count mismatches, 1 transient
failure: infrastructure.org.nz — server disconnected, the streaks system tracks
it). Store shape: `data/<source>/manifest.jsonl` (landing log) +
`data/<source>/store/<aa>/<sha256>` (raw bytes) + `data/<source>/extracted.jsonl`
(derived stage). Rows carry estate field names (`sha256`/`names`/`urls`/`kind`/
`file`) so each source mounts as an MCP corpus later (see "Next").

## The build

### Capture adapter (`ingestion/capture.py`) — replaces the retired v2 landing
The pack did not include `querynz.ingestion.land_document` / `dedup` / `backlog`
(packer chose by filename). Rather than revive the retired v2 Postgres backlog,
landing is the house capture convention: raw bytes as served, landing log,
extraction as a separate stage. `base.run_source` was rewired onto it. Idempotent
on sha256 and URL (verified: re-run shows `skipped_seen`, no double-lands;
stored file shas match their record ids). Any leftover v2 call raises
`NotImplementedError` — nothing pretends to land.

### Estate-holdings gate (Arthur: "only land what the claude estate doesn't hold")
Before fetching, every discovered URL is checked against the estate manifests
(all 21 corpora at `/opt/data/querynz-estate/sources/*/manifest.jsonl`) and the
MCP's beehive corpus — **155,076 URLs** indexed. Dropped items are counted in an
`already_held` bucket (the A22 counting identity extended; nothing vanishes
uncounted). Verified the gate fires: an estate-held URL drops, a fresh one
passes. In the sweep `already_held: 0` — genuine non-overlap (fresh news vs the
estate's govt registers); the beehive module discovers nothing and defers to
beehive-scraper as the byte-for-byte holder.

### WAF plumbing
- `ingestion/proxies.py` — the ONE proxy helper (C207), now real: IPRoyal
  residential, NZ exit (config `/opt/data/beehive-scraper/proxy.json`, creds
  b64). Password template `<base>_country-nz_session-<random>_lifetime-30m`,
  one session per source-run (per-request rotation breaks transfers). Opt-in
  per source (`PROXIED_SOURCES`) — the hosts measured refusing this egress IP
  outright while serving via the exit. This is the remedy odtconz's docstring
  prescribes.
- `newsscrapers/browserfetch.fetch_raw` — raw response bodies through the
  headless browser in ONE solved session (challenge cookie carries across URLs).
  Built because Chromium's XML viewer escapes a feed into `<pre>` text:
  `page.content()` finds 0 `<item>` while the raw body is the real RSS.

## What was broken and what fixed it (evidence)

Measured from this runtime on 2026-11-09. Each fix is dated in its module.

- **thespinoff.co.nz** — site redesigned; monthly `/posts` sitemaps became
  numbered `/sitemaps/articles/N.xml` (1 = newest). `discover()` silently
  returned 0. Fixed → 21 discovered, extraction survived the redesign.
- **greaterauckland.org.nz** — article pages 403 (both UAs) but the feed
  carries full articles (`content:encoded` 14–33 KB). Module reads the feed
  (one request per sweep, zero article fetches) + wp-json-by-slug fallback for
  backwalk. Landed: the Mayoral Manifesto, 13,034 chars.
- **sfo.govt.nz** — the browser requirement was stale: the media-releases
  LISTING render is challenged (2/2) but pages are server-rendered and answer
  200 to the honest UA. Discovery walks the SilverStripe site-tree sitemap
  (538 media-release URLs), articles fetch plain. 2 landed without a browser.
- **times.co.nz** — two bugs: `render_all` derives its proxy key from the URL
  hostname (`www.times.co.nz`) which missed the proxy entry (browser ran direct
  → challenged); and Playwright wants proxy credentials as fields — embedded in
  the server URL it silently hangs `Page.goto` (60s timeouts). Fixed both →
  2/2 landed.
- **ecan.govt.nz** — Incapsula (the beehive class: proxied plain HTTP still
  gets the 205-byte stub; a real browser auto-solves). Discovery and articles
  ride `fetch_raw` in one solved session. 5 discovered, articles land — with
  flakiness (see "Not happy with").
- **guardianonline.co.nz, crux.org.nz, royalsociety.org.nz (+marsden)** — 403
  on this egress IP for plain and browser UAs; 200 via the residential exit.
  Wired `PROXIED_SOURCES`. Marsden's year pages come in two shapes
  (`marsden-awards-2012…17`, `marsden-fund-awards-2018+`) — the old regex only
  matched the second era. Both Royal Society lanes land (13 + 45 discovered).
- **nzinitiative.org.nz** — listing 301s and article hrefs lost their trailing
  slash; the link regex required one → matched nothing. Fixed → 15 discovered.
- **seafood.co.nz** — TYPO3 → WordPress; the old listing/detail shapes are
  gone. Discovery rides `/feed/` (200, 10 items). Landed 1.
- **beehive.govt.nz** — its `/feed` now serves the Incapsula shell (ParseError).
  beehive-scraper is the holder; the registry entry is `parked:external`.

## What is not buildable here — and why

Statuses live in `newsscrapers/registry.py` with dated, evidence-carrying
comments. Policy: a lane that runs and lands nothing is worse than one that
refuses, because only the second is visible.

- **odt.co.nz → `blocked:paywall`** (new status — the old vocabulary had no
  honest word for a paywall). 4 fetches over 2 cadences: every article answers
  200 but serves the subscriber teaser only ("This story is for subscribers.",
  48 chars). The body is absent from the HTML AND the SSR payload
  (`__NEXT_DATA__`/urqlState walked: ads/robots/teasers only). NBR class: a
  subscription + login lane lifts it. The JS-check earlier reported is not
  reproducible; the paywall is.
- **ruralnewsgroup.co.nz → `blocked:antibot`** — refuses every route: 403
  direct (plain + browser UA), 403 via the residential exit, headless browser
  challenged on the feed. Nothing further to try; the stop is the remedy
  (ruling 290).
- **Frozen refusals (Arthur, 2026-11-09: "don't keep trying the refusals we
  will look at them one by one")** — nothing retries these; they wait for him:
  greystar (robots refused/unreadable), thedailyblog / e-tangata / stoppress /
  ourauckland / voxy / rbnz (anti-bot — challenges or shells).
- **NZME UNFROZEN (ruling 169, Arthur 2026-11-11)** — ruling 12 ("out by
  name") is withdrawn. nzherald.co.nz collects from 2026-10-18 01:15 NZ and
  businessdesk.co.nz from 2026-10-17 10:50 NZ (when the old estate's
  scrapers stopped); no pre-October backfill. Capture-and-hold (ruling 115)
  still applies to the nzherald network: raw land, no extract/embed until an
  NZME licence lands. businessdesk.co.nz: discovery rebuilt onto the Arc
  outbound sitemaps (the monthly `articles-sitemap-YYYYMM` is gone; measured
  2026-11-11) but the site is paywalled — 395 discovered, 100 fetched, 100
  thin, 0 landed (subscriber teasers only) → `blocked:paywall`; a
  subscription + login lane lifts it.
- **parked:external** — beehive.govt.nz (beehive-scraper holds it) and
  **zz-cron** (never captured by this registry; never add it — it feeds the
  separate zz-cron-retention product. If it maps to a module here under another
  name, say which and the rule will be wired exactly).
- **credentials** — newsroom.co.nz, nbr.co.nz: run only when their env vars are
  present (never a login that is not ours — hard limit 6).

## House rules honoured

Robots is read for Crawl-Delay only and the delay is honoured (POLITE_SLEEP);
one request at a time per host; nothing fetched twice; a challenged read is a
failed read and never lands; refusals are diagnosed once and held, never
hammered; every file carries the sha256 of the bytes as captured.

## Tests

`python -m pytest tests/` — 24 pass, 3 skipped. The skips are handover gaps,
loudly labelled: three provenance files the packer missed
(`data-layer/docs/RETIRED.md`, `ingestion/retired/test_backfill_era_dsn.py.retired`,
`ingestion/retired/README.md`) — request from the integrator, re-enable. The
stale NZME assertion (`ready`, from ruling 115's capture-and-hold era) was
corrected to `blocked:ruling` per ruling 12.

## Next

1. `capture.py` tests (the landing format's regression net — empirically
   verified only so far).
2. Scheduling: the intraday/daily runs (6-hourly `--hours 6 --limit 60`, daily
   `--hours 30 --limit 250`) as the box's crons, off-peak where the hosts ask.
3. MCP mounting: per-source corpora (`record_file` = manifest, `path_root` =
   source dir) + one `pipeline` lane each — which closes the loop with the
   estate's `mcp-stale` ask (a lane for every estate-\* corpus; `repair_requests`
   for the stale list; see `/opt/data/mcp-stale-brief.md`).
4. Ruling-28 archive walks (backwalk) — depth is currently 7 days of fresh news.
5. The above, plus the three handover files from the integrator.

## Still owed

- The 3 handover files listed under Tests.
- A look at infrastructure.org.nz's disconnect (transient — one attempt per
  sweep, streaks parks it after three consecutive failures).
