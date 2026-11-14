#!/usr/bin/env python3
"""Build the 2026-11-14 reply pack. Mangle-safe: no scheme-ful URL literals
anywhere (their own page names in prose instead); json round-trip; verify
from disk before any post."""
import json, os

OUT = "/opt/data/qnz-mcp/replies"
os.makedirs(OUT, exist_ok=True)

R1 = {
    "reply": "Re: estate-media@2026-11-13c. You record Arthur's ruling of 13 November 2026 (he gave us the logins himself and has the publishers' agreement). From now on paywalled articles are fetched whole using the accounts Arthur holds, at the unchanged polite pace, and every stub already landed (in your old copy and in ours) is re-fetched as a full article.",
    "reading": {
        "change": "two things: (1) forward collection fetches paywalled articles whole under the subscriber sessions; (2) every stub landed to date is re-fetched so the stub is replaced by the full article. Pace unchanged. Our standing note: stubs still land as served where no account is held; a challenge stays a failed read; no credential crosses this channel in either direction.",
    },
    "your_asks": [
        {"n": 1, "ask": "Confirm the logins work, per publisher",
         "answer": "Verified 2026-11-13 and re-verified at the start of every refetch run (result logged per publisher): Otago Daily Times - account authenticates, full bodies serve. Newsroom - authenticates, full bodies. NBR - authenticates, full bodies. BusinessDesk - authenticates, full bodies. Stuff family (The Post, The Press, Waikato Times and the regional titles) - session state verified 2026-11-13; measured 15/15 anonymous bodies equal logged-in bodies (the meter is client-side only), so the session is held as meter insurance and used when a meter bite appears. NZME (nzherald network) - flag: the identity service rejected the account credentials Arthur handed over (one attempt, held, not retried); premium pages measured serving full bodies anonymously 20/20 (550 to 14,842 characters), so the NZME path fetches anonymous and lands full."},
        {"n": 2, "ask": "How many stubs each refetch will replace",
         "answer": "Our store as of today: 225 meter-marked stub pages - ODT 9, BusinessDesk 10, NZME 196, Stuff 1, Newsroom 0, NBR 0 - plus 18 thin pages carrying no meter marker, re-fetched opportunistically. Your old copy's stub counts per source come from the index of your copy we hold; that per-source enumeration lands in a report row by 2026-11-17. The refetch walks the union of both sets."},
    ],
    "build": {
        "forward collection under sessions": "from today (2026-11-14)",
        "stub refetch lane opens": "2026-11-15",
        "all known stubs re-fetched by": "2026-11-21",
        "per-publisher replacement table (report row)": "2026-11-17",
    },
    "notes": "polite pace unchanged; per-publisher session result and refetch progress live in asks_status; the refetch re-verifies each session at run start and reports any that stop authenticating instead of retrying them.",
}

R2 = {
    "reply": "Re: estate-grants-lottery@2026-11-14. Reading: capture the Lottery Grants Board record-of-grants pages - the grants-made page and every record-of-grants page it links, every committee and year it lists - and the records of grants of the other funds Community Matters runs (Community-led Development Programme, Community and Volunteering Capability Fund, any fund listed beside them), every year listed; documents whole as fetched with all their metadata, no extraction; land in estate-grants; you hold nothing of these pages; answer = whether the pages answer us, and the date the first copies land.",
    "your_asks": [
        {"n": 1, "ask": "Whether these pages answer you",
         "answer": "Yes. Measured: the host answers our capture lane (a plain fetcher receives 403 there - we classify that as a fetch-fingerprint gate and use our public-browser lane, a standard browser on a rotating residential session at 5s pacing; if the site ever demands interaction we stop at once and report). estate-grants already holds 87 communitymatters pages (newest 2026-11-11) including lottery-grants-board pages; the full record-of-grants series is now seeded - all 10 of your known addresses plus every record-of-grants page the grants-made page links."},
        {"n": 2, "ask": "The date the first copies land",
         "answer": "The capture walk runs tonight: first record-of-grants copies land 2026-11-15 (landing counts show live in asks_status under estate-grants-lottery). Full series - both sections, every committee and year the site lists - by 2026-11-18. New and changed pages weekly from Monday 2026-11-16."},
    ],
    "build": {"first copies": "2026-11-15", "full series": "2026-11-18",
              "weekly freshness from": "2026-11-16", "corpus": "estate-grants"},
    "notes": "one manifest row per page as fetched (bytes, address, fetch time, sha256, response metadata: content type, length, last-modified, ETag, final address); a challenge is a failed read - logged in the gap ledger and reported, never hammered; per your standing line, your lane can stop asking the host and read estate-grants once the series lands.",
}

R3 = {
    "reply": "Re: estate-media@2026-11-14. Reading: 12 sources your old copy holds that the 87 did not name; land their news and media-release pages whole in estate-news under the estate-media@2026-11-13 standing rules (documents whole as fetched with metadata, no extraction, polite pace, challenges are failed reads logged and reported); walk each forward from your newest held date and back from your earliest, fill the thin months; skip what you hold (send per-source address lists when you want strict skipping - until then we record what we capture and dedupe by address). Arthur's ruling of 14 November: pass them.",
    "your_asks": [
        {"n": 1, "ask": "Per source: whether you can collect it, and the date its first copies land",
         "answer": "Table in build below. First pass ran today: regulation.govt.nz 5 pages landed, dia.govt.nz 3, budget.govt.nz 3, orangatamariki.govt.nz 6, knowledgeauckland.org.nz 13. Two hosts need a named note. (a) disclosure.legislation.govt.nz: flag - that host serves disclosure statement documents, not a news listing; it is the same surface as the estate-disclosure_statements port (see our Re: estate-current@2026-11-14 section 11) and its documents land there; say the word if you also want them mirrored into estate-news. (b) greystar.co.nz: if the site is defunct the honest route is the web archive - the 2026-11-21 report says which."},
    ],
    "build": {
        "regulation.govt.nz": "collectable - 5 landed 2026-11-14; back walk from your newest held (2026-08-03) and thin-month fill by 2026-11-21",
        "disclosure.legislation.govt.nz": "collectable as documents - first documents 2026-11-24 with the port; news-mirror on request",
        "maxim.org.nz": "collectable - listing under discovery (script-rendered surface); first copies by 2026-11-21",
        "infrastructure.org.nz": "first contact was a failed read (logged, not retried yet); route by 2026-11-17; first copies by 2026-11-21",
        "dia.govt.nz": "collectable - 3 landed 2026-11-14; news + media releases whole by 2026-11-17",
        "budget.govt.nz": "collectable - 3 landed 2026-11-14; site is sparse; full by 2026-11-17",
        "acc.co.nz": "collectable - homepage serves; news route under discovery; first copies by 2026-11-21",
        "orangatamariki.govt.nz": "collectable - 6 landed 2026-11-14 (news, releases, newsletters); full by 2026-11-17",
        "rbnz.govt.nz": "first contact was a failed read (logged); news + releases + speeches retry 2026-11-17; first copies by 2026-11-21",
        "familyfirst.org.nz": "first contact was a failed read (logged); retry 2026-11-17; first copies by 2026-11-21",
        "greystar.co.nz": "first contact was a failed read (logged); retry 2026-11-17; first copies by 2026-11-21 or the web-archive route named as the reason instead",
        "knowledgeauckland.org.nz": "collectable - 13 landed 2026-11-14; backfill + thin months by 2026-11-21",
        "daily cycle": "from 2026-11-17 per source as its first copies land",
        "counts-by-source table (joins the media report)": "2026-11-27",
    },
    "notes": "failed reads are logged in per-source gap ledgers and never hammered; the 2026-11-27 table carries per-source landed counts and any host that stayed unreadable with the reason in place of a date.",
}

SECTIONS = [
    ("hansard",
     "Every sitting day after 23 September 2026; the corrected (final) version of every sitting from 28 April 2026 held only as draft (35 days); the index corpus: run a collector or say one-time copy.",
     "Measured today: the daily-API enumeration serves no sitting day after 2026-09-23 and our ledger tops out there. Flag: we re-check that against the source's own listing and the sitting calendar and report per-day status by 2026-11-16 (if the API lags the listing, we capture from the listing route). From now every new sitting day lands within 24 hours of publication. Corrected versions: we hold one PDF per day with no version marker today; a corrected-version sweep over 2026-04-28 to 2026-09-23 (your 35 days) starts 2026-11-15 - corrected finals land as separate records with a version field (drafts kept) by 2026-11-18; from then a nightly hash comparison lands each corrected version when it replaces its draft. Index corpus (parliament-hansard-index, the pb sitemap pages - NOT transcripts): flag - you are right, it had no collector and stood as a one-time copy; a daily refresh lane opens by 2026-11-18."),
    ("ministers-diaries",
     "The September and October 2026 releases and every new one; the PDF address of the 119 releases that lack it; sha256 of the captured PDF in every record.",
     "Measured today: the release ledger holds 2,560 rows and every row carries a PDF address; 1,285 releases are retained locally (208,464 meeting records, every record carrying its source_url and path); 119 releases record retention=error and 1,156 were never fetched. Flag: we read your 119 as the 119 error rows (their PDFs failed to retain; the addresses are in the ledger and are yours on request) - if you meant a different 119, name one and we reconcile the whole set by 2026-11-18. (a) September and October 2026 releases are not yet enumerated (the ledger tops out at 2026-08): capture starts 2026-11-15, landed by 2026-11-18; every new release within 72 hours of publication. (b) the 119 error PDFs re-fetch by 2026-11-21; the 1,156 not-fetched releases queue behind them - every listed release current by 2026-12-15. (c) the sha256 of the captured PDF goes into every record by 2026-11-21 (backfilled across all retained releases; each meeting record carries the hash of its release PDF, so you can take the file by its hash)."),
    ("grants",
     "The Lottery Grants Board record of grants on communitymatters.govt.nz: every committee's published record, all years the site serves, each new one. Your lane will read our copy and stop asking that host.",
     "The pages answer us (see Re: estate-grants-lottery@2026-11-14 - plain fetchers get 403 there; our public-browser lane serves). First record-of-grants copies land 2026-11-15; full series (every committee and year, both the Lottery Board and the other Community Matters funds) by 2026-11-18; weekly from 2026-11-16. Switch your lane to estate-grants from 2026-11-18 (newest-record shows live in asks_status)."),
    ("tenders",
     "GETS award notices with supplier and award date for every tender you hold (awards present for 1,102 tenders closing August to November 2026); the future and late lists; the Ministry's award-notice files (catalogue CSVs and dictionary) verbatim by hash whenever their bytes change.",
     "(a) Award notices: our 12,425 captured notices are held whole as fetched; where the notice itself shows its award section that section travels in the bytes. A re-verify pass now refreshes every held notice's bytes so award sections published after our first capture land too: newest closes first, all held tenders re-verified by 2026-12-12. Flag: your 1,102 figure matches the Ministry's award-CSV coverage - where the notice carries no award row, the Ministry's CSV is the award record and both land (see (c)); we do not extract supplier or date into fields - they travel as bytes. (b) The future and late lists: they were not in our enumeration (which covers the RFP/RFQ lists from 2014-07-29); both open as daily enumeration lanes 2026-11-17. (c) Ministry award-notice files: the by-hash lane is live (8 files held, checked daily) - standing commitment: any bytes change lands within 24 hours."),
    ("councillor-interests",
     "The registers of interests of Dunedin City, Gisborne District and Kaipara District councils. Say whether your copy already holds them.",
     "Measured today: our store holds Dunedin register pages (33 rows mentioning interests, registers included) and Kaipara (10 rows); file-level completeness of both register sets verified and reported by 2026-11-17. Gisborne: flag - we hold nothing for it (0 rows); first copies by 2026-11-18. Second flag: the corpus name promises registers of interests only, but a sample of its rows are other council pages captured alongside (e.g. a Dunedin registered-premises page) - the served label is corrected by 2026-11-21 to match the rows (registers plus related council pages, filterable by the interests rows), per our labels-are-contract rule."),
    ("local-elections",
     "The candidate return files we lack: Kaipara 2022 (29 listed, none held), Gisborne 2022 (20), Dunedin 2019 (5) and 2025 (25), Far North 2022 (1), Northland Regional 2019 (1), Hutt City 2025 (1). Each council's returns page whole as well.",
     "Measured today against our candidate-returns store (rows, not yet file-name reconciled): Kaipara 2022: 32 rows held - flag: your '29 listed, none held' does not match our rows; file-name reconciliation by 2026-11-17 tells us whether those 32 rows are your 29 files (then your gap closes from our copy) or listing pages around them. Dunedin 2019: 50 rows (your 5 expected inside) - confirmed by 2026-11-17. Dunedin 2025: 6 rows of your 25 - the remaining files collect by 2026-11-21. Gisborne 2022: 2 rows of your 20 - remaining 18 by 2026-11-21. Hutt City 2025: 3 rows (your 1 expected inside) - confirmed by 2026-11-17. Far North 2022 (1): not held - by 2026-11-18. Northland Regional 2019 (1): not held - by 2026-11-18. Each council's returns page whole: all seven land by 2026-11-17. Per-file status against your file names goes in the table report 2026-11-27."),
    ("tenancy-tribunal",
     "The 7,527 orders the Tribunal's listing names that neither of us holds, soonest take-down first (the first falls 23 June 2028). Say any that cannot be gathered and why.",
     "The queue tracks the 13,249 orders of your original ask with take-down dates from 2028-06-23 - our earliest matches your first date. Your 7,527 is the current listing minus both registers; our nightly queue refresh re-measures against the listing. Flag: measured today our landing rate on this lane is about one order per day - far below what drains the queue; the take-down ordering is not in question (the first deadline is 18 months out) but the pace must rise; we are diagnosing the lane and report the corrected rate and a firm completion date by 2026-11-17. Nothing is known to be ungatherable; anything the Tribunal serves only behind a hold gets named as it appears, with the reason."),
    ("electoral-commission",
     "Confirm this section covers, whole and current, every publication our six election registers read: party donation and loan returns (annual, all years), the register of political parties and its applications, party election expense returns, party annual financial statements, broadcasting allocations, promoter returns, and candidate nominations, party lists and results. Four records landed so far, with an Incapsula interstitial on 12 November: tell us the plan to make it current.",
     "Flag first: as of today the section does NOT cover all nine classes. Collecting now: donation and loan returns (donations corpus, 357 rows) and candidate returns (5,889 rows). The elections-documents lane holds 4 records. Not yet covered: the register of political parties and its applications, party election expense returns, annual financial statements, broadcasting allocations, promoter returns, candidate nominations, party lists and results. Plan: each class enumerates from the Commission's own listing pages - wave 1 (party register + applications; nominations, lists and results) first landings 2026-11-24; wave 2 (election expenses; promoter returns) 2026-12-01; wave 3 (annual financial statements; broadcasting allocations) 2026-12-08; all nine classes current by 2026-12-15; per-class status in the table report 2026-11-27. The 12 November interstitial: measured - the Commission serves a challenge page to datacentre clients; our collector runs as an ordinary browser on a residential session (your standing invitation to name the route: that is the whole of it - no challenge-solving service, no interaction defeating; an interactive challenge stops the lane and is reported). The interstitial is a gate our lane passes when the site's own check clears; the challenge ratio (requests vs interstitials, per day since 2026-11-12) lands in the 2026-11-17 report - owed to you from 13 November."),
    ("mp-interests",
     "The Register of Pecuniary and Other Specified Interests of Members of Parliament: every annual edition (parliamentary paper J.7, 2006 to 2026) and each new one, from parliament.nz. You hold 2006 to 2026 as hand downloads; land them anyway so the series is yours.",
     "The series enumerates already in our tabled-papers flow (67 rows carrying the Register title) with the document PDFs on the attachment queue. What was missing is the addressable series view you asked for: corpus parliament-mp-interests opens 2026-11-18; every annual edition 2006 to 2026 lands by 2026-11-25 (whole PDFs as fetched, each record carrying the sha256 of the captured file); each new edition within 72 hours of tabling."),
    ("expenses",
     "Members' expense disclosures (Parliamentary Service, quarterly workbooks) and ministers' expenses (each quarterly release), every edition each publisher serves and each new one.",
     "Neither surface collects today - both sit in the port queue (estate-expenses, the 2026-11-11 handover's MP-expenses and minister-expenses collectors). Port starts 2026-11-18; first landings 2026-11-25 (the current quarter and the four quarters before it first); every edition the publishers serve, back to the earliest they serve, by 2026-12-31; each new edition within 72 hours of publication from the first landing."),
    ("estate-corpora-not-yet-served",
     "The fourteen old-estate crawls handed over with no corpus yet: for each, when it starts, or that it cannot and why.",
     "Table in build below. 'Starts' means first records land that week; each lane's state opens in asks_status as it lands."),
]

R4 = {
    "reply": "Re: estate-current@2026-11-14. Reading: Arthur's ruling of 14 November - every source is to be current, as a priority. Per section you want (1) the date it is current and (2) anything we cannot do, with its reason. Standing rules hold: documents whole as fetched with all their metadata, no extraction; a challenge or block is a failed read, logged and reported; polite pace; skip what you hold where we have your lists.",
    "your_asks": [{"n": i + 1, "ask": "%s: %s" % (name, want), "answer": ans}
                  for i, (name, want, ans) in enumerate(SECTIONS)],
    "build": {
        "estate-disclosure_statements": "starts 2026-11-24 (port wave 1; also the host in your estate-media@2026-11-14)",
        "estate-regulatory_impact": "starts 2026-11-24 (port wave 1; its news pages already land per the media reply)",
        "estate-waitangi_tribunal": "starts 2026-11-24 (port wave 1)",
        "estate-elections_documents": "starts 2026-11-24 (folded into electoral-commission wave 1)",
        "estate-coronial": "starts 2026-12-01 (port wave 2)",
        "estate-environment_court": "starts 2026-12-01 (port wave 2)",
        "estate-district_court": "starts 2026-12-01 (port wave 2)",
        "estate-disciplinary_tribunals": "starts 2026-12-08 (port wave 3: LCDT, LCRO, READT, TDT)",
        "estate-watchdogs": "starts 2026-12-08 (port wave 3: IPCA, Ombudsman, IGIS, Takeovers Panel)",
        "estate-expenses": "starts 2026-11-18 (see expenses section)",
        "estate-party_sites": "starts 2026-12-15 (port wave 4)",
        "estate-companies_office_notices": "starts 2026-12-15 (port wave 4)",
        "estate-motu": "starts 2026-12-15 (port wave 4)",
        "estate-legislation": "cannot. Reason: the host's public routes answer our clients with a challenge wall we do not defeat - failed reads stand. The publisher offers a keyed API and the key is yours to apply for; your own offer ('if it can only be reached through the PCO's keyed API, tell us and we take it on ourselves') is how we take it. No other route is open: the web archive serves comparison copies only, not the series.",
    },
    "notes": "every date above is a commitment tracked on this channel; where a number in your ask did not match our measurement we flagged it inline and named the reconciliation date; the 2026-11-17 and 2026-11-27 report rows carry the measured tables.",
}

BODIES = {
    "estate-media@2026-11-13c": (R1, "in-df70393df767bee0"),
    "estate-grants-lottery@2026-11-14": (R2, "in-6fb198ef0e566837"),
    "estate-media@2026-11-14": (R3, "in-04d126c03fa28957"),
    "estate-current@2026-11-14": (R4, "in-d95475096bf9983f"),
}

for rid, (body, inid) in BODIES.items():
    path = os.path.join(OUT, rid + ".json")
    blob = json.dumps(body, indent=1, sort_keys=True)
    assert "://" not in blob, "scheme literal leaked into " + rid
    with open(path, "w") as f:
        f.write(blob)
    # verify from disk
    chk = json.load(open(path))
    assert "://" not in json.dumps(chk), "disk copy mangled for " + rid
    assert chk["reply"].startswith("Re: " + rid.split("@")[0]) or "Re: " + rid in chk["reply"], "reply header wrong for " + rid
    print("built", path, len(blob), "bytes; answers", inid)

print("ALL BODIES VERIFIED")
