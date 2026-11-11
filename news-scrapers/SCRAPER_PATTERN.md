# Scraper pattern — reference for new sources

How to build a new scraper/importer in this sandbox. Distilled from the
production `fyi-scraper-standalone` / `nzlii-scraper-standalone` (Java/dataox)
design and reconciled with the existing Python `explore/fyi_scraper.py`.

The goal of this repo is unchanged: **scrape + parse only, no DB writes** in
exploration; you see exactly what production would extract before committing to
storage. New sources slot into the same read-only `explore_run` harness.

---

<!-- 2026-09-23 doc audit: the three helper names above carried a leading
     underscore the code has never had — they are `pdftotext`, `ocr_pdf` and
     `dedup_attachments` in `ingestion/explore/_fetch.py`. A reader following
     this pattern grepped for a private name and found nothing. The Java
     names (`ScraperOutput`, `MetadataOnly`, `ContentComplete`,
     `FyiAuthorityChecker`) are deliberate references to the prior system and
     are left as they are. -->

## 1. Principles (from the dataox scrapers)

1. **Scrape/parse only — no persistence, no scheduler.** Each scraper returns
   plain objects; storage, dedup, and scheduling live in a separate runner. (The
   Java projects ship zero DB code by design.)
2. **Two phases, separated.** *Discovery* (cheap: list item links/ids) is a
   different concern from *content* (expensive: fetch + parse one item). Keep them
   in separate functions/classes — they paginate, rate-limit, and fail differently.
3. **Errors are values, not exceptions.** A fetch/parse failure returns a result
   object (or `None`), never throws across the boundary — one bad item must not
   abort a crawl. (Java uses a sealed `ContentComplete | ContentError`; in Python,
   return the item or `None` and log.)
4. **Be polite.** A delay between requests, an honest `User-Agent`, honour
   `robots.txt`, and (at scale) a NZ-IP proxy. Coverage is a marathon.
5. **Idempotent / incremental.** Never re-fetch what you've already stored — track
   what's been seen so a re-run is cheap (see §5).

---

## 2. The data contract

The harness ([`explore/explore_run.py`](explore/explore_run.py)) only needs a few
things from any scraped item. Keep this minimal common shape; add source-specific
fields freely.

**Required**: `url: str`, `title: str`, `source: str` (domain, drives
`source_type`), and `combined_text(max_chars=...) -> str` (the text fed to the
LLM). **Recommended**: `published_date: str | None` (ISO), `attachments:
list[dict]` (`{url, filename, extract_method, char_count, text}`).

`combined_text()` is where you compose the LLM input from the parts you scraped —
e.g. OIA = authority + request + responses + attachment text; a court judgment =
just the body; an enforcement notice = the notice fields. See
`ScrapedArticle.combined_text()` for the shape.

> Mirror of the Java `ScraperOutput`: `MetadataOnly` (a discovered link) →
> `ContentComplete` (parsed item) → `ContentError`. In Python we collapse this to
> "discovery returns urls/light records; `scrape_one()` returns the item or
> `None`."

---

## 3. Shape of a source module

**Copy [`explore/_template_scraper.py`](explore/_template_scraper.py)** to
`explore/<source>_scraper.py` and fill in the TODOs — it's a working skeleton of
exactly this shape (`ScrapedItem` + `discover()` + `scrape_one()`, wired to
`_fetch`, with a standalone `--url` dev loop).

```python
# explore/<source>_scraper.py
BASE = "https://example.govt.nz"

def discover(limit=..., since=..., **filters) -> list[str]:
    """Phase 1 — cheap. Return item URLs (or lightweight id records).
    Paginate here; stop at the cap/cutoff."""

def scrape_one(url: str) -> ScrapedItem | None:
    """Phase 2 — expensive. Fetch + parse ONE item into the contract object.
    Return None on failure (logged), never raise."""
```

Then point the harness at it (the README "Adding a new source" recipe):
1. `explore_run.run()` calls your `discover()` + `scrape_one()`.
2. Register the domain → `source_type` in `extraction.source_tags`
   (`SOURCE_TYPE_OVERRIDES`) in `querynz-data-layer`.

---

## 4. Coverage strategies (the part most scrapers get wrong)

The dataox FYI scraper is worth copying here:

- **Most listings cap out** (FYI: 20 pages × 25 = 500 per query; many gov sites
  cap similarly). If a source can exceed the cap, **chunk the query** — by month
  (FYI), by year (NZLII), by category — so each sub-query stays under it.
- **Pre-flight volume check.** Before crawling an authority/section, do 1–2 cheap
  requests to estimate size and pick a strategy: small → paginate directly; large
  → chunk. (`FyiAuthorityChecker` → `EMPTY | SMALL | LARGE`.) Saves hammering
  empty sections and silently truncating big ones.
- **Detect the last page explicitly** (a disabled "next", an empty result set, no
  pagination element) — don't assume a fixed page count.

---

## 5. Incremental — prefer a seen-ledger over re-scraping

The Java scrapers *emit markers* (per-authority/-type/-month "scraped" records)
and leave persistence to you. In this stack you already have the better version:
a **durable seen-id ledger** (the data-layer's `article_ledger`,
`news_canonical/store/ledger.py`, is exactly this — `captured → processed →
failed`). For a new source:

- Record every discovered item's stable id (the URL, or the site's own id) the
  moment you see it.
- Skip items already `processed`; re-attempt `failed` up to N times then drop.
- This makes re-runs cheap and means nothing is silently lost.

Use a stable natural key (the request slug, the judgment citation) — not a
generated uuid — so re-discovery maps to the same ledger row. (This is the same
dedup-by-`upstream_id` lesson the news pipeline learned the hard way.)

---

## 6. Robustness toolkit (reuse, don't re-implement)

`fyi_scraper.py` already contains source-agnostic helpers worth **extracting into
a shared `explore/_fetch.py`** so every new source reuses them:

- **HTTP client** — `httpx.Client(headers={"User-Agent": UA}, timeout=30,
  follow_redirects=True)` + a `REQUEST_DELAY` between calls.
- **PDF → text, then the recogniser** — `pdftotext` (embedded) → `ocr_pdf`
  (`ec_pageread.vision_ocr`, the estate's one page recogniser) when embedded
  text is thin. Returns `(text, method)` where method ∈ `text|ocr|none`.
  Scanned PDFs are common across gov sources, so this is broadly useful; a
  page the recogniser cannot read is COUNTED in `OCR_DROPS`, never dropped
  silently.
- **Attachment content dedup** — `dedup_attachments` (drop exact/contained
  duplicate text; richest copy wins; keep empties for audit). The same letter
  attached three times wastes LLM context and skews extraction.
- **Per-attachment records** — keep `{url, filename, extract_method, char_count,
  text}` so the url ↔ text association survives to storage/audit.

### Bot-protected sources (browser required)

Some sources block plain HTTP. Keep the browser machinery inside the scraper
module (behind the same `discover`/`scrape_one` interface) so the harness stays
unchanged. **Worked example: [`explore/hansard_scraper.py`](hansard/scraper.py)** (hansard.parliament.nz, behind Radware Bot Manager). Lessons:

- **Recon before building.** A plain GET returned `<title>Radware Page</title>`,
  not content — establish *what* protects a site and whether there's an easier
  path (sitemap / RSS / underlying JSON API) before writing a scraper.
- **Find the API.** The site turned out to be a Blazor WASM app with a clean JSON
  API under `/api/data/` and date-routed transcripts — far better than parsing
  rendered HTML. Capture the app's XHR (Playwright `page.on("response", …)`) to
  discover it.
- **Headless gets flagged.** Radware (and Cloudflare) escalate to a captcha on
  headless browsers. The fix that worked: **non-headless** Firefox + masked
  `navigator.webdriver` + realistic UA/locale/timezone. Headful needs a display —
  `xvfb-run` on a headless server.
- **Reuse one session.** Clear the bot-challenge once, then reuse the browser for
  many pages (cf. the Java NZLII pool). Wait for the SPA to *render* (content
  often appears seconds after `networkidle`), not just for navigation.
- **Use Playwright's async API** for browser sources so they compose with the
  async extraction harness (`explore_run` awaits the LLM). Sync Playwright throws
  inside a running asyncio loop. `HansardBrowser` is an async context manager.
- **Enumerate via the site's own API, not the rendered listing.** Hansard's
  debates page POSTs `/api/data/search` (OData: `@odata.count` + `value[]` with
  `sittingDate`). Driving that JSON enumerator (`discover_all`) lists the whole
  back-catalogue of sitting days with **no per-day render** — only `scrape_one`
  pays the browser cost. Capture the listing's own XHR to find this.

**Coverage/archival roadblock (worth checking early).** A "modern" portal often
only serves *text* for recent years; older material is scanned page-images hosted
elsewhere. Hansard text via the app runs back to **2003-02-11** (~330k chars/day);
1854–2002 are scanned bound volumes on **HathiTrust / Google Drive** (the volumes
API exposes their `Url`), so "back to the beginning" needs separate OCR of foreign
hosts — out of scope for the text scraper. Probe the index/volumes API for the
real text floor before promising full history.

**Huge-document roadblock.** A sitting day is ~330k–1.5M chars — far over a useful
LLM context. The explore harness caps it (`max_chars`), so only the *start* of the
day is extracted. Real ingestion must **chunk by debate section** (the transcript
carries section headings) and use a source-appropriate prompt/schema (the news
prompt tags Hansard as generic "public administration" and manufactures
quotes/sentiment — the same fit problem OIA had; Hansard wants its own schema:
speaker, party, motion, division/vote).

---

## 7. Two runners (read-only first, write later)

- **Explore (read-only)** — `explore_run.py` is the canonical harness: `discover`
  → `scrape_one` → `ExtractionClient.extract` (LLM) → `match_org` (read-only NZBN)
  → JSONL dump + summary. **No DB.** This is where you validate a new source.
- **Ingest (writes)** — only once a source is proven, add a writing runner (like
  `oia_ingest.py`) that feeds items through the appropriate store/pipeline. Make
  it **idempotent via the ledger** and commit one item per transaction.

---

## 8. New-source checklist

- [ ] `explore/<source>_scraper.py` with `discover()` + `scrape_one()` returning
      the contract object (`url`, `title`, `source`, `combined_text()`).
- [ ] Honour `robots.txt`; set an honest `User-Agent`; add a request delay.
- [ ] Coverage: handle pagination caps (chunk if needed) + a pre-flight size check
      for large sections.
- [ ] Reuse the shared fetch/PDF/OCR/dedup helpers (`explore/_fetch.py`).
- [ ] Register the domain → `source_type` in `extraction.source_tags`.
- [ ] Validate read-only via `explore_run` (eyeball the JSONL: entities, facts,
      NZBN matches, attachment text).
- [ ] Only then: a writing runner, idempotent via a seen-ledger.

---

## Lineage

- `fyi-scraper-standalone` / `nzlii-scraper-standalone` (Java/Spring, dataox) —
  the production scrapers this pattern is mined from: sealed `ScraperOutput`,
  link/content split, pre-flight volume check, monthly/yearly chunking, marker
  incrementalism, proxy pools, CF bypass.
- `explore/fyi_scraper.py` — the Python reference implementation (homepage
  discovery + thread parse + PDF/OCR + attachment dedup).
- `querynz-data-layer` — the extraction pipeline, `source_tags`, and the
  `article_ledger` durable-seen pattern the ingest runners should reuse.
