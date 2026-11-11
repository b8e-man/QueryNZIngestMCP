# Scraper archetypes — reusable patterns for new sources

Most NZ public sources fall into a handful of shapes. Rather than a bespoke scraper
each, a new source should slot into the matching **archetype** below — every one has
an existing **exemplar** to copy and (where built) a **reusable scaffold** so adding a
source is mostly config. This is the map for working through `SOURCES.md`.

See also `ARCHITECTURE.md` (the source→backlog→extraction→extractions flow + storage
rules) and `SCRAPER_PATTERN.md` (the discovery/content split, politeness, idempotency).

---

## A. Document-listing → OCR/text backlog  ·  reusable engine ✅
Listing page(s) → links to documents (PDF/HTML) whose filename carries a stable
identifier → enqueue into the `documents` backlog for the OCR pool, then extract.

- **Exemplar / scaffold:** `scrapers/docsource.py` (generic engine) + `scrapers/registry.py`
  (one `DocSource` config per source) + `scrapers/run.py`. Courts (ERA/Environment/
  District) are configs today.
- **Add a source:** confirm the listing URL + the document-link regex + an
  identifier regex, add one `DocSource` to the registry (+ a group if it shares an
  extractor). No new code.
- **Extraction:** judicial documents reuse `courts.extract` (drains `documents` by
  source tag → court pipeline). A non-judicial doc type needs its own extractor, but
  the *ingestion* is free.
- **Targets:** coronial findings, professional disciplinary (HPDT / LCDT / READT /
  Teaching Council), Waitangi Tribunal, Māori Land Court, Regulatory Impact Statements
  (Treasury), departmental disclosure statements, EPA fast-track project docs.

## B. Structured-content source → backlog → LLM extraction  ·  pipeline ✅
A record with a body (± attachments) that needs the LLM to pull entities/facts.

- **Exemplar / scaffold:** the regulatory pipeline, parameterised by source
  (`comcom` → `comcom_cases`, `fma` → `fma_warnings`); `oia`. **2026-09-23 doc audit:**
  this line named `regulatory_case`/`regulatory_facts`/`regulatory_mentions`, and none
  of the three exists in the database. The claim traces to `comcom/extract.py` and
  `fma/extract.py`, which import `extraction.pipeline_regulatory` and
  `extraction.auth_guard` — **neither module exists**, so those two files cannot run,
  and the only units that ran them are in `ops/systemd/retired/`. What the lanes DO
  write is `comcom_cases` (112 rows) and `fma_warnings` (16). Reading those into a
  register is C397.
- **Add a source:** a scraper → its `incoming_news` backlog table (mirror
  `comcom_cases`), then point the regulatory pipeline at it (source tag → its
  `<source>_facts`/`_mentions`). Extract **all** signal (ARCHITECTURE.md).
- **Targets:** WorkSafe enforcement, RBNZ regulatory actions, EPA consultations.

## C. Notices → backlog → deterministic derive → register + facts  ·  template ✅
Highly-structured notices parsed by regex (no LLM) into entities + facts + a
queryable register that **points at the facts**.

- **Exemplar / scaffold:** `companies_office/` (scraper→`incoming_news` backlog→
  `derive`→entities + `companies_office_facts`/`_mentions` + `director_disqualification`
  pointing at the prohibition fact); `gazette_register/` (3 registers over `gazette_facts`).
- **Add a source:** `ingest.py` (scrape → backlog), `parse.py` (pure), `derive.py`
  (backlog → entities/facts; register row carries `fact_source`+`fact_id`). Any new
  entity-FK table → add to `merge.py` SCALAR_REFS.
- **Targets:** Companies Office liquidations/receiverships; NZX director changes /
  substantial-holdings notices.

## D. Verbatim API register → canonical store  ·  template ✅
An authoritative register pulled **verbatim** from a real API into `nzbn_canonical`
(NOT a derived register), reconciled into the graph nightly.

- **Exemplar / scaffold:** `charities/` (OData → `nzbn_canonical.charities.*` + nightly
  reconcile to `charity_officer` edges).
- **Add a source:** `client.py` (API), `sync.py` (→ canonical store), `reconcile.py`
  (→ graph edges via `get_or_create`), `daily.py`. Verbatim register → `nzbn_canonical`;
  anything *extracted/derived* → `extractions`.
- **Targets:** data.govt.nz (CKAN), Stats NZ (SDMX), LINZ (ArcGIS REST), IPONZ,
  Companies Office bulk CSVs (Disclose + PPSR), DigitalNZ, NZ Legislation (PCO API —
  see `docs/LEGISLATION_STRATEGY.md`).

## E. Bot-protected → headful browser  ·  reusable browser ✅
Radware / Cloudflare hosts that block plain HTTP; cleared once by a de-fingerprinted
Firefox and reused across page loads.

- **Exemplar / scaffold:** `hansard.scraper.HansardBrowser` (masked webdriver, NZ
  locale/timezone, Radware-clearing `goto`). For document sources, pass its `goto`
  text into `DocSource.fetch` (the engine's fetch hook); otherwise drive it directly.
  Needs a display (xvfb on a headless server).
- **Targets:** MP Pecuniary Interests, Parliament select-committee submissions, JDO
  (also needs an NZ residential proxy), LAWA.

## F. Platform scraper (one scraper, many instances)  ·  to build
Many orgs on an identical platform → a single parameterised scraper + a host list.

- **Exemplar:** none yet; closest is the `DocSource` registry idea (one shape, many
  configs).
- **Targets:** Citizen Space / Delib consultations (~6 agencies, identical structure);
  council bylaws + district plans on shared ePlanning platforms (Isovist/Objective).
  Investigate platform commonality + aggregators (MfE/LGNZ) before per-council scrapers.

---

## Verifying a source actually landed — read the RIGHT surface

**Added 2026-07-30 after a real misdiagnosis.** "Is this source in `articles` /
`article_ledger`?" is a valid check for archetype A/E/F sources, which land via
contract-1 `land_document`. It is **wrong for archetypes B, C and D**, which
stage into their own tables — so a healthy source reads as completely absent.

This cost real time: FMA's ingest reported `staged 0`, someone checked
`articles`/`article_ledger`, found zero FMA rows, and concluded the run was
broken and the restored dump was incomplete. In fact `fma_warnings` held 15
rows, the `SELECT 1 FROM fma_warnings WHERE case_id=:c` dedup check was hitting
correctly, and `staged 0` was the right answer. The proposed "fix" — loosening
that dedup — would have duplicated rows on every 3-hourly `ingest-all` sweep.

| Archetype | Lands in | Verify with |
|---|---|---|
| A doc-listing → OCR | `documents` (+ `articles` after materialize) | `SELECT count(*) FROM documents WHERE source=…` |
| B structured → LLM | its OWN backlog table | `comcom_cases`, `fma_warnings`, `oia_requests` |
| C notices → derive | its own backlog table, then a derived register | `nzbn_canonical.gazette.*`, `companies_office_*` |
| D verbatim API register | `nzbn_canonical.<register>.*` | `charities.charity_entities`, `legislation.instruments`, `mp_interests.*` |
| E bot-protected browser | `articles` + its own section table | `hansard_sections` |
| F platform scraper | `articles` | `articles` / `article_ledger` |

Measured on the 2026-07-30 corpus, all of these are invisible to an
articles/ledger check: `hansard_sections` 1,215 · `documents` 1,028 ·
`oia_requests` 302 · `comcom_cases` 89 · `fma_warnings` 15.

**The canonical answer already exists — use it instead of ad-hoc SQL.** The
Flow page's *dedicated pipelines* pane (`/api/flow`, the `dedicated` list in
`v3/api.py`) queries each of these surfaces per source and reports capture
volume, freshness, and processing stage. It was showing the correct picture
throughout the incident above. Check Flow first; reach for SQL only to explain
what Flow shows.

## Target → archetype map (from SOURCES.md)

| Target | Archetype | Status |
|---|---|---|
| ERA / Environment / District courts | A | ✅ live (registry configs) |
| Coronial findings | A | ⬜ add a `DocSource` |
| Professional disciplinary (HPDT/LCDT/READT/Teaching) | A | ⬜ add `DocSource`s |
| Waitangi Tribunal · Māori Land Court | A | ⬜ |
| Regulatory Impact Statements (Treasury) | A | ⬜ |
| Departmental disclosure statements · EPA fast-track | A | ⬜ |
| WorkSafe · RBNZ actions · EPA consultations | B | ⬜ reuse regulatory pipeline |
| Companies Office liquidations · NZX notices | C | ⬜ reuse companies_office template |
| data.govt.nz · Stats NZ · LINZ · IPONZ · DigitalNZ · Companies Office bulk · Legislation API | D | ⬜ reuse charities template |
| MP Pecuniary Interests · Select-committee submissions · JDO · LAWA | E | ⬜ reuse HansardBrowser |
| Citizen Space consultations · council bylaws/plans | F | ⬜ build platform scraper |
