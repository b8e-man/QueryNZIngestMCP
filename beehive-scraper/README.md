# Beehive.govt.nz forward scraper

Everything published or edited on beehive.govt.nz from 2026-10-21 forward, at
record level, with failure visibility. Zero LLM tokens (no_agent cron scripts).

## Layout

- `state.json` — seen URLs, sitemap lastmod map, run health
- `manifest.jsonl` — one record per event (item/edits): ts, kind, url, type, title, raw pub_date, lastmod, teaser description, source
- `extracted.jsonl` — STAGE 2 output: one record per captured body with
  deterministic metadata + LLM topics/quotes (see below)
- `pending_pages.jsonl` — URLs whose HTML body still needs capture (Tier 2)
- `backfill_inventory.jsonl` — every URL in the full 29-page sitemap
- `backfill_queue.jsonl` — inventory rows whose body is not yet captured
- `data/raw/YYYY-MM-DD/` — raw feed + sitemap XML snapshots per run (evidence)
- `data/pages/` — Tier-2 body HTML lands here
- `logs/collect.log` — one summary line per run
- `logs/bodyfetch_stats.log` — pages + transfer bytes per fetcher run
- `proxy.json` (600) — IPRoyal proxy config, creds base64-encoded

Scripts live in `/opt/data/scripts/` (cron no_agent requirement):
`beehive_collect.py`, `beehive_watchdog.py`, `beehive_bodyfetch.py`,
`beehive_extract.py`, `beehive_backfill.py`, + `.sh` cron wrappers.

## What runs

- Collector: every 2h. Silent on success, exit 1 on source failure (the cron
  scheduler turns that into an error alert).
- Watchdog: daily 07:35. Alerts on staleness/zero-capture/error state, plus a
  one-line heartbeat every Monday.
- Bodyfetch (forward queue): every 6h, 12 pages/run.
- Backfill: every 15m, 90 pages/run through the proxy (see Backfill below).
- Extract: every 1h, 400 docs/run (see Extraction stage below).

## Extraction stage (stage 2, downstream — raw untouched)

`scripts/beehive_extract.py` — idempotent per (url, sha256). For every
captured body it writes one record to `extracted.jsonl`:
- deterministic (regex over the Drupal markup): title, published_at (ISO
  from `<time>`), ministers[{name, slug}], portfolios[], body_text,
  word_count, type
- LLM (Nous `deepseek/deepseek-v4-flash`, ~3s/doc, 6 threads): topics[]
  (3-7 NZ policy labels) + quotes[{text, speaker}] verbatim with attribution

Model notes: `deepseek-v4.1-flash` (the cron tier) reasons too long for bulk
work — it truncates or takes 30-60s/doc. v4-flash emits clean JSON in ~3s.
Auth: reads the shared Nous token store fresh per call (Hermes refreshes it);
401 triggers a best-effort OAuth2 refresh grant.
Cost estimate at scale: ~$0.0003-0.0006/doc → ~$15-35 for all 56K.

## Backfill (full history)

`scripts/beehive_backfill.py` harvests ALL 29 sitemap pages (the forward
collector only diffs the tail 2) and writes `backfill_inventory.jsonl`
(56,431 URLs: 54,472 /release/ + 1,947 /node/ aliases + 12 misc) and
`backfill_queue.jsonl` (inventory minus bodies already captured).

The `beehive backfill` cron drains the queue via
`beehive_bodyfetch.py --queue backfill_queue.jsonl --limit 90` every 15m —
~8,600 pages/day, full backfill ≈ 6-7 days. Silent when drained.

Bandwidth (measured): 705KB/page if the browser fetches Drupal's JS bundles,
20KB/page when all scripts EXCEPT `/_Incapsula_Resource` are blocked (HTML is
server-rendered; the challenge JS is what we must keep). Full backfill ≈
1.1GB through the residential proxy either way it runs now.

Known gap (now closed 2026-10-22): the sitemap contains no /speech/ or
/feature/ URLs at all. `scripts/beehive_enum_browse.py` (daily 05:00 cron)
closes it from two sources: the live listing pages (`/speeches?page=0..N`,
10/page — but the listing only reaches back to late 2023, ~279 speeches) and
the Wayback CDX URL index (13,665 /speech/* + 784 /feature/* rows ever
archived — this is where pre-2023 speeches live). CDX is used for
ENUMERATION only; Wayback captures of beehive are challenge stubs.
Discrepancies recorded, not fixed: URL style eras (`/speech.foo+bar` old
style vs `/speech/foo-bar`), `:80` hosts and utm queries stripped for
dedupe only, and ancient paths that 404 are retried 3x by bodyfetch then
abandoned (attempt count in done.jsonl). The enum also re-captures
/feature/post-cab-press-conference when its body sha changes (weekly
transcripts whose feed date never changes).

## Coverage (why this is "everything")

- `rss.xml` = latest 30 items of ANY type (releases + speeches + features; proven
  via Wayback history) — polled every 2h so the 30-item window can never roll
  over unseen (worst observed burst: 31 items/day on Budget day 2026, 27 of them
  in 90 minutes).
- speeches + features feeds add type depth.
- Sitemap tail-page lastmod diff catches: new URLs (incl. backdated inserts),
  and EDITS to existing pages (e.g. the Post-Cabinet press conference feature
  gets weekly transcripts but its feed date never changes — sitemap lastmod is
  the only signal).
- Dedupe is by URL set, never by date (feed ordering is by creation, not
  pubDate — tail items appear out of date order).

## Transport findings (2026-10-21)

- Feed + sitemap XML endpoints: direct fetch OK from the VPS with a browser UA.
- HTML page endpoints: Incapsula JS challenge for every datacenter fetcher
  tested — direct (any UA/headers/cookies), allorigins, codetabs, r.jina.ai,
  archive.ph, anonymous Wayback SPN (now requires an account). Per standing
  rule: bot challenges are never defeated.
- Consequence: Tier 1 = record level (manifest + queue). Bodies need Tier 2.

## Tier 2 — page bodies (RESOLVED 2026-10-22)

- IPRoyal residential proxy (`geo.iproyal.com:12321`, creds base64 in
  `proxy.json` 600) + headless chromium works: the Incapsula JS challenge
  auto-solves in <5s and the real page is served (65KB HTML verified).
- Plain HTTP through the SAME proxy still gets the 212-byte stub — a real
  browser is required, the residential IP alone is not enough.
- Use a FRESH `country-nz_session-<random>_lifetime-30m` per run; a shared
  session ID gets burned after a couple of uses.
- Detection pitfall: real Incapsula-fronted pages ALSO reference
  `/_Incapsula_Resource` — that string is NOT a challenge marker. The stub
  = tiny size + `NOINDEX, NOFOLLOW` / "Incapsula incident".
- `scripts/beehive_bodyfetch.py` + `.sh` wrapper (parliament-scraper venv
  python, PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright). Drains
  `pending_pages.jsonl` (limit 12/run, retries failed/challenged), silent on
  success. Cron `beehive bodyfetch` every 6h.
- Status: all 36 queued bodies captured (2026-10-22). Wayback SPN confirmed
  useless for beehive (captures the challenge stub).
- Possible full-text complement (not yet evaluated): Scoop.co.nz republishes
  Beehive releases in full from a non-challenged origin.

## Data conventions

Raw only, no transformation (discrepancies are recorded here, not fixed):
- pub dates stored as the raw RSS string; lastmod as raw ISO from the sitemap.
- Item pages may carry minister/portfolio tags + full body — extraction is a
  separate downstream step.
- Known quirk: sitemap `lastmod` ≠ pubDate (edits bump lastmod; some releases
  are backdated at publication).
- Known limitation: sitemap tail (last 2 pages) is diffed; edits to pages older
  than the tail window are not detected (rare, low value).

## Ops

**CRON RUNNER KILLS SCRIPTS AT ~120 SECONDS** (measured 2026-10-22: every
backfill run was dying at ~110s mid-batch — captures kept flowing but no
stats lines were written and the job showed `last_status: error`). All tick
scripts therefore carry `--time-budget` and stop cleanly before the kill;
throughput comes from SHORT FREQUENT ticks, not long ones (the scheduler is
fixed-delay: next run = previous completion + interval). Current cadence:
backfill every 1m (~30 pages/tick ≈ 14K/day), extract every 5m
(~150 docs/tick), forward bodyfetch every 6h, enum daily 05:00.

Manual run: `python3 /opt/data/scripts/beehive_collect.py` (silent on success;
check `logs/collect.log` or `state.json`).
Watchdog preview: `python3 /opt/data/scripts/beehive_watchdog.py --heartbeat`.
Backfill progress: real remaining = queue lines minus captured-ok URLs in
`done.jsonl` (the queue file is static; fetchers dedupe at read time).
Extraction failures are logged to `failures.jsonl` and retried (capped at 5
attempts per doc); the run only alerts when ok==0 or >25% fail.
