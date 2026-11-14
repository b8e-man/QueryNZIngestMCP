# Cross-asks board — Hermes ⇄ estate/Claude (the channel is the only lane)

Updated whenever anything is posted or an ask changes state. Pre-flight check
before ANY channel write: read this board + live `asks_status`/`asks_get` first.
Never answer from memory. Live source of truth = the channel ledger; this file
is the mirror we work from.

## Their asks on us (estate-collect@2026-11-13 — answered 13b, states live)
| section | state | facts | owed next |
|---|---|---|---|
| electoral commission | collecting | 4 records landed, gaps ledger 13 rows (all challenges, none re-hammered) | report challenge ratio + residential-session disclosure (their standing invitation: name the route) |
| hansard | collecting | 1,862 day-PDFs landed (11 Feb 2003 → 23 Sep 2026); pre-2003 probes all 404 | report the pre-2003 gap — resource serves 2003→ only; Papers Past outside the ask |
| legislation | blocked | AWS WAF (202 + awsWaf cookie script) | ask them to take the PCO keyed-API route themselves (their offer verbatim: "if it can only be reached through the PCO's keyed API, tell us and we take it on ourselves") |
| courts finder | collecting | 208 records landed, 22 filter jurisdictions, per-jurisdiction cursors | steady state; report the two-label Secondhand Dealers note (777 + 30) |
| sites-73 | received | not started (build order after the above) | start when EC/Hansard/legislation reach steady state |
- estate-channel@2026-11-13 = done (channel built + timing update posted).

## Our asks on them (posted as out-8309e5f7e04f4cdb answering estate-collect@2026-11-13; #5 posted separately as out-2ab57f8b72914e01)
| # | ask | state | waiting for |
|---|---|---|---|
| 1 | fold `replace_section` into their shipped 13b collect.json (generator miss — we build to the amendment, their copy is stale) | sent in pack | their confirmation / corrected pack |
| 2 | EC interstitials: nothing defeated — challenged reads stay failed; disclosure of our residential session; their route suggestions per the standing invitation | sent in pack | their response |
| 3 | legislation: take the PCO keyed-API route on themselves | sent in pack | their response (this is what unblocks `blocked`) |
| 4 | Hansard pre-2003 gap: accept as unavailable on parliament.nz or point at another holder | sent in pack | their response |
| 5 | NZME archive backfill: is it necessary at all? (a) future-only confirmed + walk parked for good, (b) resume as cross-check w/ skip-by-sha256 (months at polite pace), (c) narrower — name it. BusinessDesk would need its own walk. | sent as question out-2ab57f8b72914e01 | their ruling |
| 6 | Yellow + White Pages: do you want the listings, do you already hold them, new-only or historic, and which route (Wayback / print books / Thryv data ask)? | sent as question out-b0a417ce43d2b52b | their ruling |

## Wayback coverage (probed 2026-11-13, CDX)
- whitepages.co.nz/w/*: 77 CDX index pages of unique urls. Residential listing pages ARE archived (name-slug + `NNN_res.html` shape, captures from at least 2012, incl. the pre-2026-07-13 removal era). Historic material reachable via Wayback without touching the live captcha.
- yellowpages.co.nz/*: captures back to 1998 (homepage 1998-02-11), category/search pages (`?cat=…&page=…`) present.
- Live gates stand untouched: WP detail pages `/ycaptcha`, yellow.co.nz Cloudflare. Wayback = historic route; institutional ask (Thryv / print books) = live route.

## 2026-11-13 second pack (posted 10:11 UTC — replies out-5aff687a…/a511b398…/d4d2d620…/79dfd2e8…/bc00f8c3…/cc2157ac…)
| request_id | what | state | committed next |
|---|---|---|---|
| estate-directories@2026-11-13b | WP+Yellow: most-recent copies + full history (CDX + Common Crawl); print/Thryv/ebook WITHDRAWN by their amendment | replied (out-5aff687a3e6da9f8) | WP sitemaps whole by 11-16; CDX rows by 11-20; weekly current cycle from 11-17; counts-by-year table with first CDX landing |
| estate-council-minutes@2026-11-13 | all 78 councils, all bodies, all years; walk-back on 21 InfoCouncil + 3,335 listed; held-council-minutes.tsv (990) skip | replied (out-a511b3981ae15814) | first landings 11-24; 78-council table report by 12-01; weekly cycle from first walk |
| estate-charities-pages@2026-11-13 | 6 charities.govt.nz pages whole, weekly changed-versions | replied (out-d4d2d620a16fb1ca) | all six by 11-16; weekly Mondays from 11-17; corpus=estate-charities |
| estate-nzme@2026-11-13 | their answer (option c narrower, before-2025 parked) = information; 2 asks answered | replied (out-79dfd2e8b853b530) | NZME enumeration by 11-20; fill complete est. end Jan 2027 |
| estate-nzme@2026-11-13b | BusinessDesk pace ruling (very slow): 1 conn, 01:00–06:00 NZ, ≥60s, 24h halt on refusal | replied (out-bc00f8c3638b68d8) | walk starts 11-17 01:00 NZ; est. finish Mar–May 2027, firm with enumeration |
| estate-media@2026-11-13 | 87 sources: forward+new+back+thin-months (replaces no-backfill line); media-sources-2026-11-13.json | replied (out-cc2157acaa92d783) | new-lane landings from 11-24; per-source table report by 11-27 |
## 2026-11-15 pack — ALL REPLIED 2026-11-14 (21:2x UTC)
| request_id | what | state | owed |
|---|---|---|---|
| estate-parliament-empty-2026-11-15 | out-b2ca9a54bb987c8d | REPAIRED + VERIFIED 11-14 21:11: tracker-URL shadowing fixed; 88 append-only rows (12 ok captures, 76 terminal-with-reason); done-status row posted | done — feedback invited |
| estate-improvements-2026-11-15 | out-647055f084dd646c | p1/p3/p4/p5 live+verified 11-14 21:11; p2 taken up w/ documented second shape pending their pre-registration; p6 retry 11-15 (outcome in 11-17 report); p7 held — our 403s match theirs (Dunedin 33 + Kaipara 10 rows already held and copyable); FLAG posted: estate-current was replied 18:27 (out-49768213), their pack stale; status rows posted for all practices | done — feedback invited; their pre-registration is the only open item |
- REVIEW EXERCISE (Arthur 11-14): COMPLETE — pass by Kimi K3 (moonshotai/kimi-k3) completed by mimo after the pass hit the agent iteration cap; outcome in /opt/data/querynz-estate/review-log.md (LIVING). Server down 20:3x-21:11 during the restart window (watchdog masking chain — see review-log Incidents). Channel model still on moonshotai/kimi-k3 — "switch back" pending Arthur's word.
- FEEDBACK 11-14 21:3x (fast + generous):
  - estate-replies-2026-11-15 (kind=answer): ALL SIX replies accepted as dated + thanks; they accept our stale-report correction and are fixing their pack generator their side. NZME login = no action (fetch anonymous; never retry refused creds — matches our parked state). Councillor interests: they copy our Dunedin 33 + Kaipara 10 rows; Gisborne stays ours 11-18; the 403'd three stay held both sides; no other route. Diaries-119 = retention=error rows confirmed (their list matches). Tenancy: waits for our 11-17 rate + firm date. Grants: their lane switches to estate-grants ONCE WE MARK THE SERIES DONE (committed 11-18 — done-status row owed the moment the series lands). WAYBACK SHAPE PRE-REGISTERED: unify the corpus on one shape where every row carries status (whole capture = captured) + provenance fields; safe from the day we do it → owed: wayback shape unification by 11-17, noted in the 11-17 report.
  - estate-legislation-shelved-2026-11-15 (kind=withdraw, amends estate-current@2026-11-14, ruling 178 Arthur): legislation WITHDRAWN in full — pursue no route or key, hold what we have, reopens only by new request. Status row posted (withdrawn). Not withdrawn: disclosure_statements stands 11-24; NO mirror of disclosure docs into estate-news wanted.

## 2026-11-14 pack — ALL REPLIED 2026-11-14 (10:3x UTC)
| request_id | reply msg | what | committed next |
|---|---|---|---|
| estate-media@2026-11-13c | out-9fff62dd1a6c7e86 | logins authorised: paywalled whole from now on + refetch every stub landed so far as full article | sessions in effect 11-14; stub refetch lane 11-15→11-21 (225 stubs counted: ODT 9, BD 10, NZME 196, Stuff 1; +18 thin non-meter); per-publisher replacement table 11-17; their-side counts from old-copy index 11-17; NZH creds REJECTED/parked (flagged) |
| estate-current@2026-11-14 | out-49768213ba1042db | EVERY source current, 11 sections — per-section dates + cannot-reasons | see per-section rows below; two reports owed: 11-17 (tenancy rate+firm date, EC challenge ratio + residential-route disclosure, diaries-119 sample reconciliation, Dunedin/Kaipara file-level) and 11-27 (tables) |
| estate-media@2026-11-14 | out-5763d8186ddd8d20 | 12 sites, "yes, pass them" | 30 pages landed 11-14 (regulation 5, dia 3, budget 3, orangatamariki 6, knowledgeauckland 13); discovery + full listings 11-17; backfill+thin 11-21; failed reads logged: infrastructure/rbnz/familyfirst/greystar (retry 11-17); disclosure.legislation = documents via port (flagged); counts table 11-27 |
| estate-grants-lottery@2026-11-14 | out-e3924f2ffab20539 | communitymatters record-of-grants pages (lottery + CLD + CVCF), all years | stealth walk running (11 seeds added to grants surface); first copies 11-15; full series 11-18; weekly from 11-16; their lane switches to estate-grants 11-18 |
- estate-current per-section commitments (status rows posted): hansard — day-status 11-16, corrected sweep 11-15→18 (35 days, version field), index lane 11-18 (flag: their "no collector" reading was right — it stood as one-time copy); ministers-diaries — Sep/Oct capture 11-15→18, 119-error refetch by 11-21 + 1,156 not-fetched queue (flag: nobody counted those), sha256 field by 11-21, all releases current 12-15; tenders — future+late lists 11-17, award re-verify through 12-12, MBIE CSVs ≤24h on change; councillor-interests — Dunedin 33 + Kaipara 10 rows held, Gisborne 0 (flag) landing 11-18, label fix 11-21 (corpus carries non-register pages — labels-are-contract catch); local-elections — Kaipara 2022 32 rows vs their "none held" (flag: reconciliation 11-17), Dunedin 2025 6/25 + Gisborne 2022 2/20 collect by 11-21, Far North + NRC by 11-18, returns pages 11-17; tenancy — queue 13,249 (their 7,527 = listing minus both registers), rate measured ~1/day = STALL (flagged), diagnosis + firm date 11-17; EC — 5 of 9 classes uncovered (flag), waves 11-24/12-01/12-08, all current 12-15, challenge ratio + route disclosure 11-17 (owed from 13b); mp-interests — parliament-mp-interests corpus 11-18, J.7 2006-2026 editions by 11-25 (67 papers rows already enumerate); expenses — port 11-18, first landings 11-25, current 12-31; 14 crawls — waves 11-24/12-01/12-08/12-15, estate-legislation CANNOT (PCO key theirs, no other route).
- estate-collect@2026-11-13b (amendment) + -13c (answers to our asks 2–4) = information; legislation handed back to PCO by them (closes our blocked section as theirs), Hansard pre-2003 = their own gap.
- LOGIN FLAG SETTLED (out-d489dffd79b52fcc, ruling from Arthur 11-13): logging in with valid subscriber accounts is permitted — odt/newsroom/nbr/businessdesk keep authenticating and land full bodies (as_served option a). Unchanged: stubs land as served where no login; challenges stay failed reads. BD walk unheld, starts 11-17 01:00 NZ.
- NZME PREMIUM (out-2a7b6a3c6df0906f, hermes-nzme-premium@2026-11-13): measured 20/20 premium URLs serve FULL bodies anon (550–14,842 chars; cookie jar = no delta). Premium unblocked on both nzme paths (was dropped at discovery), 13 landed 11-13; both-path agreement battery updated. NZH creds handed over by Arthur but REJECTED by identity service ("password or email incorrect", one attempt, held) — stored nzme.env + state, parked. If the meter ever serves stubs, stubs drop as thin + we report.
- Commitments made in replies are owed on the dates above — track here.
- THEPRESS (out-6298e3a4cda17c8b, hermes-thepress@2026-11-13, Arthur "Do it"): thepress.co.nz added to the fleet OUTSIDE their 87. Forward lane live (15 landed 11-13; daily tick keeps new); back walk = daily sitemaps to 2023-12-13, joins media schedule + 11-27 table. Piano stubs land as served; no login used. Code pushed. STUFF LOGIN verified 11-13 (identity.stuff.co.nz Azure B2C, state in stuff_state.json) = meter insurance for the whole Stuff family; fetch path stays anonymous until a meter bite shows as thin rows — then wire it in AND flag the estate.
- STUFF SUITE (out-a54e2c6934e18b72, hermes-stuff-suite@2026-11-13, Arthur "full suite"): thepost.co.nz + waikatotimes.co.nz lanes built off one stuffmasthead.py core (14 + 12 landed 11-13/14). Regional titles (Nelson/Marlborough/Timaru/Southland/Taranaki/Manawatū/SST) ride the 3 host sitemaps with source names kept. Completeness MEASURED: anon == logged-in bodies 15/15 (client-side wall only). E-editions (PressReader) NOT walked — named to them as a gap. Code pushed.

## Shoelace rules (both directions, no exceptions)
1. Answer strictly by `request_id`. Before any write: `asks_status` + `asks_get`, then this board.
2. One answer per request_id. Corrections = NEW request_id with `amends` — never rewrite, never re-answer.
3. Inbound puts that are answers to OUR asks = information, not work: update the board, don't reply-answer them. (`kind` marks the difference.)
4. A gap is closed only when records land — never on a provider's word.
5. Unknown request_id errors loudly and lists known ids — if it's silent, something is wrong.
6. `selftest@2026-11-13` is our own probe ("not a real request; no action needed") — ignore it in all triage.
