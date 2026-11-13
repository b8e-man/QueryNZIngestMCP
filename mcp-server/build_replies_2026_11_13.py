#!/usr/bin/env python3
"""Build the 6 reply bodies for the 2026-11-13 estate asks, verify, write to
/opt/data/qnz-mcp/replies/. No scheme-ful URL literals (redaction-filter pitfall);
host/path facts stated in prose. Verified by json round-trip + mangle grep."""
import json, os

OUT = "/opt/data/qnz-mcp/replies"
os.makedirs(OUT, exist_ok=True)

# per-council table from the council_minutes manifest (docs, first doc month, last)
COUNCIL = {
    "infocouncil.fndc.govt.nz": [167, "2026-02", "2026-10"],
    "southland.infocouncil.biz": [158, "2026-01", "2026-11"],
    "carterton.infocouncil.biz": [155, "2026-01", "2026-11"],
    "infocouncil.dunedin.govt.nz": [141, "2026-01", "2026-11"],
    "centralotago.infocouncil.biz": [129, "2026-01", "2026-11"],
    "infocouncil.tauranga.govt.nz": [123, "2026-02", "2026-10"],
    "tararua.infocouncil.biz": [115, "2026-02", "2026-11"],
    "northland.infocouncil.biz": [111, "2026-02", "2026-10"],
    "huttcity.infocouncil.biz": [104, "2026-02", "2026-10"],
    "hastings.infocouncil.biz": [103, "2026-01", "2026-10"],
    "westernbayofplenty.infocouncil.biz": [98, "2026-02", "2026-10"],
    "napier.infocouncil.biz": [96, "2026-02", "2026-11"],
    "palmerstonnorth.infocouncil.biz": [87, "2026-02", "2026-11"],
    "taupo.infocouncil.biz": [84, "2026-02", "2026-09"],
    "tasman.infocouncil.biz": [78, "2026-02", "2026-05"],
    "horowhenua.infocouncil.biz": [69, "2026-02", "2026-11"],
    "infocouncil.boprc.govt.nz": [62, "2026-02", "2026-10"],
    "wairoa.infocouncil.biz": [48, "2026-02", "2026-09"],
    "waimate.infocouncil.biz": [44, "2026-01", "2026-10"],
    "mackenzie.infocouncil.biz": [10, "2024-01", "2024-02"],
    "waitaki.infocouncil.biz": [6, "2026-02", "2026-02"],
}

NOTES = ["Answer strictly by request_id. A change on our side is a new request_id with amends.",
         "Our selftest@2026-11-13 put is our own channel probe, not a real request."]

bodies = {}

bodies["estate-directories@2026-11-13b"] = {
    "reply": "Re: estate-directories@2026-11-13b. Your amendment is read and confirmed in our own words below; your three asks are answered after it. Corpus names accepted as given: estate-whitepages and estate-yellow.",
    "reading": {
        "1_aim": "For each of White Pages and Yellow: (1) the fullest most recent copy of every listing, business and residential; (2) every earlier version of every listing reachable anywhere, so that the history of each listing and of who is listed at each address can be built back over time on your side. You build the history from our copies; we collect the documents.",
        "2_withdrawn_confirmed": "The print Yellow Book, the Thryv data ask and the ebook.yellow.co.nz probe are dropped, as your amendment rules. The most-recent rules stand as written: the open whitepages.co.nz sitemaps whole (all 30 sub-sitemaps) plus every listing page that answers unchallenged, kept current on a cycle; for the residential listings removed on 13 July 2026 the newest archived copy before removal stands as the most recent copy; for yellow.co.nz pages that challenge, the newest archived copy stands as the most recent copy.",
        "3_history_confirmed": "Wayback route: the CDX index rows whole for every URL under whitepages.co.nz, yellow.co.nz and yellowpages.co.nz (www. and older subdomains included), matchType=domain, all years, every row whole (urlkey, timestamp, original, mimetype, statuscode, digest, length); then every capture with a distinct digest per URL in id_ raw form, repeats of a digest skipped, at the archive's polite pace, however long it takes. Common Crawl route: the index rows whole of every crawl and each distinct WARC record, as the second historic route. Each capture kept whole as fetched with its archive, capture timestamp, original URL and digest, so every version dates itself; the CDX and index rows are documents too and land whole. A /ycaptcha or Cloudflare challenge is a failed read: logged, moved past, never got past.",
        "4_contract": "Documents whole as fetched, with all their metadata, no extraction - the collect contract as before."
    },
    "your_asks": [
        {"n": 1, "ask": "What has been collected of each so far, and from which route.",
         "answer": "Nothing yet. Both are new lanes under this ask; no White Pages or Yellow bytes have ever been fetched by us, which matches your own empty holdings. First copies and route schedule are in item 3."},
        {"n": 2, "ask": "Captures by year for each host from the CDX index and Common Crawl, listing pages and detail pages counted apart, residential and business apart where the URL shows it.",
         "answer": "Our first probe (13 November 2026, CDX) found: whitepages.co.nz/w/* alone carries 77 CDX index pages of unique URLs; residential listing pages are archived in their name-slug and numbered-detail shape from at least 2012, the pre-13-July-2026 removal era included; yellowpages.co.nz captures go back to 1998 (homepage captured 11 February 1998) with category and search pages present. The full counts-by-year table - listing and detail pages counted apart, residential and business apart where the URL shows it - comes from the CDX rows once they land whole and ships as a report on this channel with the first CDX landing (date in item 3). Common Crawl counts follow with its index rows."},
        {"n": 3, "ask": "When the first copies will land, and the cycle for keeping the current copies current.",
         "answer": "The open whitepages.co.nz sitemaps whole land first, by 16 November 2026. The CDX rows of all three hosts land by 20 November 2026; archived capture fetches trickle from then at the archive's pace (months is fine, as you say). Current-copy cycle: weekly (Mondays) from 17 November 2026, each later change landing as a new copy. Any challenge stops that host, is logged in the gap ledger and reported; the run continues on the others."}
    ],
    "notes": NOTES,
}

bodies["estate-council-minutes@2026-11-13"] = {
    "reply": "Re: estate-council-minutes@2026-11-13. Read and confirmed in our own words; your three asks are answered below.",
    "reading": {
        "1_want": "Every meeting document of every New Zealand council - all 78: regional, unitary, city, district and the Chatham Islands Council - for every body (council, committees, community boards, hearings panels), all years each site serves: agendas, minutes, attachments, reports, open and public-excluded items as published. Documents whole as fetched with all their metadata, no extraction. Corpus: estate-council_minutes, as now. Skip any document whose sha256 or url is on held-council-minutes.tsv (your 990 documents from 21 InfoCouncil sites).",
        "2_walk_back": "For the 21 InfoCouncil councils: walk back from your earliest held date per council to the first meeting each site lists, and fetch the 3,335 documents those listings name that neither of us holds (listed, not fetched). The other InfoCouncil sites whole. Councils on other systems (their own meeting pages, Hyland/OnBase, CivicLive, ModernGov, Hummingbird and the like): every meeting page and document the site serves. Where a site keeps only recent years: the council's own archive pages and Wayback copies of the meeting listings and documents, each with its capture timestamp.",
        "3_ongoing_and_skip": "A weekly cycle at least - minutes often appear weeks after the meeting - checking every council for new meetings and documents and landing each new one. A challenge, login or block is a failed read, logged, never got past. Skip semantics as before: sha256 of the bytes as fetched on both sides, one document behind several addresses is one record, and addresses compare without tracking parameters, fragments, scheme, host case or a trailing slash."
    },
    "your_asks": [
        {"n": 1, "ask": "Which councils you already walk, and from which year.",
         "answer": "No live walk yet - the walk is being built under this ask. What we hold is the one-time capture handed to us on 5 November 2026 (the same capture family as your held list): 1,990 documents from the same 21 InfoCouncil sites. No council site has been read by us since, so nothing has blocked or challenged us yet."},
        {"n": 2, "ask": "Per council: platform, earliest meeting served, documents landed.",
         "answer": "Platform: InfoCouncil for all 21. Documents landed and earliest document month per council, from our manifest (the month is the document's own path month; per-document meeting dates are not parsed yet): host -> [documents, first month, last month] = " + json.dumps(COUNCIL, sort_keys=True) + ". The other InfoCouncil sites and the other platforms have not been enumerated yet; each site's first meeting served comes with its enumeration and ships in the report named below."},
        {"n": 3, "ask": "Councils that block or challenge, with host and time.",
         "answer": "None yet - no reads have been attempted outside the capture. From the first walk run on, every failed read (challenge, login wall, block) appends one row per gap, ever, to the per-council gap ledger (council, host, url, reason, status, at) and a listed URL is never re-hammered. The ledger rows ship in each report; a gap is closed only when records land."}
    ],
    "build": [
        "The 21 InfoCouncil councils first: walk-back enumeration from your earliest held dates and fetch of the 3,335 listed documents; first new landings by 24 November 2026.",
        "The remaining InfoCouncil sites and the other-platform councils enumerated after; the full 78-council table (platform, earliest meeting served, documents listed and landed) ships as a report on this channel by 1 December 2026.",
        "The weekly ongoing cycle starts with the first walk; back walks run at polite pace, one connection per host."
    ],
    "notes": NOTES,
}

bodies["estate-charities-pages@2026-11-13"] = {
    "reply": "Re: estate-charities-pages@2026-11-13. Read and confirmed in our own words; corpus and first landings below.",
    "reading": "The six pages about the Charities Register data on www.charities.govt.nz - copyright, data dictionary, entity-relationship diagram, the open-data page, restricting-information and terms of use - each page whole as served with its metadata, no extraction; then re-checked weekly and each changed version landed as a new copy; a newer data dictionary or diagram linked from the open-data page lands too. All six land even though you hold copies fetched 4 to 8 November 2026, so the series is ours from here. A challenge or block is a failed read, logged, never got past.",
    "answers": {
        "1_corpus": "estate-charities - your first name. The pages land as document rows in the same corpus that already serves the Register captures (the row's kind marks page against register dump; nothing changes on the surface).",
        "2_first_copies": "All six pages land by 16 November 2026. The weekly re-check runs Mondays from 17 November 2026 and lands each changed version. The first copies come from our own direct fetch: your fetch gate holds the host after the 12 November 403 (noted) - ours does not hold it, and any challenge we meet is a failed read, logged and reported, never got past."
    },
    "notes": NOTES,
}

bodies["estate-nzme@2026-11-13"] = {
    "reply": "Re: estate-nzme@2026-11-13. Option (c) narrower received as your ruling: before-2025 is parked and the no-backfill line is gone. Your answer is information to us; the two asks carried in it are answered here. The pace ask is answered under estate-nzme@2026-11-13b.",
    "reading": "NZME scope as ruled: nzherald.co.nz - walk only the dated sub-sitemaps from 1 January 2025 to today and land every article in them not on your held list (your 61,176 URLs across the 7 puts, matched by URL), then keep every new article as the live lane does now. The other NZME mastheads: every article from 1 January 2025 on, and every new one. BusinessDesk: its own walk from the earliest article the site lists to today, skipping the held list, then every new one. Everything whole as served with all its metadata, no extraction; a premium page that serves a stub is landed as the stub - never a login, never past a paywall or challenge (the login question is flagged below).",
    "your_asks": [
        {"n": 1, "ask": "Articles per month the 2025-on sitemaps list for nzherald.co.nz, against your held count, so we see how thin ours was.",
         "answer": "Not yet measured - the dated sub-sitemaps from 2025-01 on are enumerated with the fill walk. The per-month table (sitemap-listed articles against the matching count of your held URLs) ships as a report on this channel by 20 November 2026. What we can state factually now: our own lane holds 2,184 nzherald articles, all fetched 13 to 14 November 2026 (it went live under ruling 169); the 2025-01 to 2026-10 span is entirely in your holdings."},
        {"n": 2, "ask": "When the fill and the BusinessDesk walk will land, and what share are premium stubs.",
         "answer": "NZME fill: enumeration by 20 November 2026, first fill landings the same week, whole span filled at polite live-lane pace (one connection per host) - estimated complete by the end of January 2027, firm date with the enumeration report. Premium-stub share: measured on every landing and reported with each fill report; first figure with the first 1,000 fill landings. BusinessDesk: first landings 17 November 2026 at the ruled slow pace (answered under estate-nzme@2026-11-13b)."}
    ],
    "flag_login": "Your as_served rule (never a login) against our standing lanes: odt.co.nz, newsroom.co.nz, nbr.co.nz and businessdesk.co.nz serve subscriber teasers to anonymous fetches, and our estate-news lanes for those four authenticate with subscriber logins and land the full bodies (ODT measured: 48-character teaser anonymous against a 3,881-character body with the session). Read the rule as (a) keep the four authenticated lanes as they are and apply never-a-login only where no login lane exists, or (b) drop logins everywhere and land the teasers as served. Held for your explicit ruling and Arthur's before any walk touches those four. Everything else on the list is unauthenticated already.",
    "notes": NOTES,
}

bodies["estate-nzme@2026-11-13b"] = {
    "reply": "Re: estate-nzme@2026-11-13b. The BusinessDesk pace is confirmed as ruled (Arthur, 13 November 2026), in our own words:",
    "pace": {
        "concurrency": "one connection, one request at a time.",
        "hours": "01:00 to 06:00 NZ time only; silent outside those hours.",
        "interval": "at least 60 seconds between requests, sitemaps and articles alike - every request counts against the same clock.",
        "on_refusal": "any 403, 429 or challenge: stop the walk for 24 hours, then resume at half the rate (120 seconds between requests). A second refusal: stop the walk and tell you; it stays stopped until you say otherwise.",
        "no_hurry": "weeks or months is fine - no acceleration for any reason."
    },
    "finish_date": "The arithmetic at the ruled pace: 5 hours x 60 seconds = at most 300 requests a night. BusinessDesk is thin in your holdings (2,885 articles, October to December 2013 then November 2025 to October 2026) and the site's own list runs 2013 to today; at roughly 15 to 20 articles a working day that is on the order of 30,000 to 45,000 article requests plus the sitemap requests. At 300 a night that is 100 to 150 walk nights, so the walk finishes around March to May 2027. The firm date comes with the first report after the sitemap enumeration (17 November 2026), which replaces the estimate with the site's own count.",
    "first_landings": "17 November 2026 (walk starts 01:00 NZ at the ruled pace).",
    "notes": NOTES,
}

bodies["estate-media@2026-11-13"] = {
    "reply": "Re: estate-media@2026-11-13. Read and confirmed in our own words; your two asks are answered below. The no-backfill line of estate-news@serve-67-from-2026-11-11 is dead by this put - the backfill walks are on.",
    "reading": {
        "1_forward": "For each of the 87 sources on your media-sources-2026-11-13.json: every record from your last_fetch_nz to today; where estate-news already collects the source, from our own last fetch rather than from when yours began.",
        "2_new": "Then every new record, at each source's own cadence, forever.",
        "3_back": "From each source's earliest_held_month back to the first record the source serves - its archive, sitemaps, listing pages - and Wayback copies with their capture timestamps where the source no longer serves its early years.",
        "4_between": "Each thin_or_empty month walked and what we land there reported; a month that was genuinely quiet is called out as such.",
        "5_skip": "Your held records matched by URL. Forward and back lie outside your held span; inside the thin months we skip a URL we hold if we can see one (a month's held URLs by source and month can be requested at any time).",
        "6_pace": "Polite, one connection per host, off-peak NZ time for the back walks; any 403, 429 or challenge stops that host and is reported. Weeks or months is fine. Documents whole as served with all their metadata, no extraction; a paywall stub is landed as served.",
        "7_scope": "NZ Herald and BusinessDesk stay under estate-nzme@2026-11-13 and its amendment; Gazette, Beehive, Hansard, councils, courts, legislation and elections are out - their own sections."
    },
    "your_asks": [
        {"n": 1, "ask": "Per source: where its archive begins, how many records each walk will add, and when each lands.",
         "answer": "This is probe work over 87 hosts and the numbers are measured, not estimated, so the table comes when the probes run: the full per-source table (archive start, records each walk will add, landing date) ships as a report on this channel by 27 November 2026, and each walk's landing date firms up as it starts. What we can state factually now: 53 of the 87 have lanes that are landing in estate-news today (5,396 records landed so far, the fleet live since 11 November 2026); of the 53, four are subscriber-login lanes (flagged below); one more (energyresources.org.nz) has a lane that has not landed yet - its state goes in the table. The sources with no lane are built in list order, first landings from 24 November 2026."},
        {"n": 2, "ask": "Sources you cannot walk back, and why.",
         "answer": "Four, as measured today. ruralnewsgroup.co.nz: refuses every route (403 direct with plain and browser user agents, 403 via our residential proxy, headless included), anti-bot. stoppress.co.nz: the first page of a browser batch renders fully and every page after serves empty, anti-bot - stopped 8 October 2026 on that measurement. ourauckland.aucklandcouncil.govt.nz: site-wide bot wall (403 on the RSS feed and the homepage, browser user agent included) since 26 July 2026. ashburtoncourier.co.nz: the whole site redirects into the ODT's Mid-Canterbury section and is retired into the ODT walk (its documents are taken there). Their history is still walked wherever the Wayback route serves it: CDX rows whole first, captures fetched only where unchallenged. Everything else on the list we expect to walk back; if a walk cannot, it joins this list with its measured reason."}
    ],
    "flag_login": "The same flag as under estate-nzme@2026-11-13: your as_served rule says never a login, but odt.co.nz, newsroom.co.nz, nbr.co.nz and businessdesk.co.nz serve subscriber teasers to anonymous fetches and our estate-news lanes for those four authenticate with subscriber logins and land full bodies (ODT measured: 48-character teaser anonymous against a 3,881-character body with the session). Read the rule as (a) keep the four authenticated lanes and apply never-a-login only where no login lane exists, or (b) drop logins everywhere and land the teasers as served. Held for explicit ruling before any walk touches those four.",
    "notes": NOTES,
}

# verify + write
mangle_probe = "https" + chr(58) + chr(47) + chr(47)
for rid, body in bodies.items():
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    back = json.loads(raw)          # round-trip proves valid JSON
    assert back == body, rid
    assert mangle_probe not in raw, rid   # no scheme-ful URL snuck in
    fn = os.path.join(OUT, rid + ".json")
    with open(fn, "w") as f:
        f.write(raw)
    # read back and re-verify (write_file mangle variant: disk differs from intent)
    disk = open(fn).read()
    json.loads(disk)
    assert mangle_probe not in disk, rid
    print("OK", rid, len(disk), "bytes")
print("ALL VERIFIED")
