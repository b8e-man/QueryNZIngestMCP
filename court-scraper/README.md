# NZ Court Judgments Scraper (court-scraper)

Raw-first capture of NZ judicial decisions into Query NZ corpora.
Planned with Arthur 2026-10-29 from his seven-row courts source map.

## Source map (recon-tested 2026-10-29)

| # | Source | Host/path | Access finding |
|---|--------|-----------|----------------|
| 1 | Supreme Court, Court of Appeal, High Court judgments | courtsofnz.govt.nz — PDFs under `/assets/cases/<year>/`, per-court RSS `/judgments/<court>/RSS` | OPEN. 3 feeds live (SC/CA/HC). Case pages `/cases/<slug>` carry PDF links. robots allows (only /search/ + admin disallowed). Wayback CDX shows >=50,000 case pages. |
| 2 | District Court judgments | districtcourts.govt.nz | Site up but `/judgments` 404s — real path not yet found. |
| 3 | HC/CA back catalogue | Judicial Decisions Online (justice.govt.nz) | BLOCKED: robots `Disallow: /*/jdo` + Cloudflare. JDO enquiry thread open with MoJ (auto-acked 21-22 Oct 2026, "5 working days"). |
| 4 | Tribunal decisions, ERA, coronial findings, disciplinary tribunals (LCRA, REAA, Teachers, LCRO) | justice.govt.nz/assets | robots `Disallow: /assets/` — crawling disallowed. Direct known-URL fetches are a policy decision (OPEN ITEM). |
| 5 | Employment Court, Environment Court, coroners' court | justice.govt.nz subsites (robots = same justice policy) | Paths unconfirmed. |
| 6 | Waitangi Tribunal reports | waitangitribunal.govt.nz + document service | OPEN. robots explicitly `Allow: /assets/*.pdf`. Reports page live (40KB). "205" in Arthur's map (count to verify). |
| 7 | Parsed case law | OpenLaw NZ API (openlaw.nz) | API exists ("programmatic access to case law") but KEY-GATED: contact OpenLaw NZ to request a key. API terms at s3-ap-southeast-2.amazonaws.com/assets.openlaw.nz/apiterms.pdf. |

## Capture design (house discipline)

- Raw only: case page HTML + judgment PDFs stored byte-exact. No text
  extraction at gather time — transformation is a separate phase.
- Every record in `records.jsonl` carries capture provenance: url,
  fetched_at, http_status, sha256, storage path, discovery channel.
- Terminal states (ok / 404 / 410) recorded once in `done.jsonl`;
  transient failures retried with a 3-strike cap.
- Freshness over archives: RSS feeds polled every tick; the Wayback CDX
  discovery channel seeds the historical backfill queue (>=50K case pages).
- Budgeted ticks (`--time-budget`, default 80s) with incremental queue +
  record writes — safe under the ~120s cron hard-kill, resumable.

## Layout

```
/opt/data/court-scraper/
├── court_scraper.py       budgeted tick: RSS freshness + queue drain
├── discover_cdx.py        one-shot/seeding: Wayback CDX -> queue
├── queue.jsonl            pending case page URLs (deduped)
├── done.jsonl             terminal outcomes (per URL)
├── records.jsonl          capture records (per document)
├── data/pages/<slug>.html case pages, byte-exact
├── data/pdfs/<year>/      judgment PDFs, byte-exact
└── logs/tick.log          per-tick stats
```

## Open items

1. justice.govt.nz `/assets/` robots disallow — respect vs request
   permission (Arthur's call; possibly fold into the open MoJ thread).
2. OpenLaw API key request (institutional ask).
3. District Court judgments path discovery.
4. Employment/Environment/Coroners paths confirmation (row 5).
5. JDO back catalogue — blocked; pursue via the MoJ automated-access thread.

## Māori Land Court (2026-11-03)

- JDO `/jdo-search-api` accepts court NAMES: `court='Māori Land Court'`
  (100 judgments 2025, 76 2024, ~2 2020, none pre-2015) and
  `court='Māori Appellate Court'` (14 2025, 4 2024). Citations are MB-style
  ("[2025] Māori Appellate Court MB 45"). JDO's `court=All` includes these
  rows (sorted deep in pages — earlier 300-row samples missed them).
  `mlc_enum.py` year-shard walk guarantees completeness (cron 07:00 daily).
- MLC bulk data captured: `data/mlc_data/` 27 files / 30MB — Māori Land
  Updates 2011-2025 (PDF), National Lists of Māori Land Blocks 2016-2025
  (xls/xlsx), National Registers of Māori Incorporations 2022-2025. Manifest:
  `data/mlc_data_manifest.jsonl` (sha256 each). Source page re-checks on
  `mlc_data_fetch.py` re-run (new editions appear as new URLs).
- Full minute-book corpus lives in **Pātaka Whenua** (the court's e-record
  portal: minutes, orders, judgments, minute book indexes, survey plans,
  historic schedules). Entry: `customer.service.maorilandcourt.govt.nz/prweb/
  PRAuth/MlcAnonymousUser` — a Pega app with guest-search (no login needed
  per court's own guide). Pega auth dance behind a JS form → next step is a
  Playwright session capturing the search XHRs. NOT yet captured.
- The court's site is the punycode domain `www.xn--morilandcourt-wqb.govt.nz`
  (macron ā). justice.govt.nz/courts/decisions/?Filter_Jurisdiction=24|468
  = MLC + Māori Appellate Court views of JDO.
