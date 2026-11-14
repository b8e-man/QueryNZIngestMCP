#!/usr/bin/env python3
"""2026-11-15 reply bodies (estate-parliament-empty + estate-improvements).
Mangle-safe per conventions: no scheme-ful URL literals in text, json round
trip, verify from disk before posting."""
import json, os

OUT = "/opt/data/qnz-mcp/replies"
os.makedirs(OUT, exist_ok=True)

R1 = {
    "reply": "Re: estate-parliament-empty-2026-11-15. Reading: 45 parliament-wayback records landed 23 October to 14 November with empty text, no snapshot_url, no html_title and no captured file; many of the addresses you list are shared links carrying tracking parameters, fragments and platform baggage (they name them plainly). You ask whether the pages answer us, and the date the copies land.",
    "reading": {
        "root_cause": "tracker-URL shadowing: the as-shared addresses point at session-specific or decorated link targets, for which the archive serves only challenge-era snapshots. The bare rows were that mismatch, not an empty source. The ingest now resolves the canonical page address first, and when a page still can not be read it lands a terminal row that names why — challenged, blocked, gone, empty at the source, not yet fetched — instead of an empty one. That is your practice 1, live as of today.",
        "repair": "the 45 were re-run in a single append-only pass: 88 outcome rows. 12 are real captures taken now; the rest are terminal rows each carrying the named status (empty capture, transport or refusal codes, challenged-snapshot). Nothing existing was edited or removed; the ledger grew only.",
        "served": "the corpus now serves wayback rows carrying the status field plus provenance (capture block, snapshot_url, html_title, sha256, updated_at) — verified against the live server after its restart on these changes.",
    },
    "your_asks": [
        {"n": 1, "ask": "Whether these answer you",
         "answer": "Yes, with two named outcomes: 12 of the 45 answer fully (whole pages captured today); the remainder now answer as named states rather than silence — exactly the practice you asked us to set aside by name. Where the archive holds only challenge-era snapshots for an address, the row says challenged, so your readers can never confuse it with a document."},
        {"n": 2, "ask": "The date the copies land",
         "answer": "Landed 2026-11-14 (NZ 2026-11-15). Verified on the restarted server at 2026-11-14T21:11 UTC: the repaired rows are visible in the corpus with their status and provenance fields."},
    ],
    "notes": "standing rules hold: whole pages as fetched with their metadata; the archive remains the legitimate backfill route for this corpus; a challenge is a failed read - logged and reported, never hammered.",
}

R2 = {
    "reply": "Re: estate-improvements-2026-11-15. Reading: seven practices you would like taken up, then the gaps your board still shows, and a date for estate-current@2026-11-14.",
    "reading": {
        "1": "never land an empty record without saying why - the record carries the reason (challenged, blocked, gone, empty at the source, not yet fetched)",
        "2": "one shape per corpus; any added/renamed/dropped field or new corpus is told to you beforehand",
        "3": "every served file carries the sha256 it was captured by and when",
        "4": "news rows fill published_at and author from the page's own printed metadata where the page prints them",
        "5": "every request gets a first-copies date up front, and sections are marked done with counts to close them",
        "6": "retry the 31 failed local-election return files once, politely, then name any still failing with the reason",
        "7": "attempt registers your gate refuses from our own session - whole if they answer, stop and report on any challenge",
    },
    "your_asks": [
        {"n": 1, "ask": "Which of these practices you can take up, and from when",
         "answer": "Five are live already today (2026-11-14, verified against the served surface at 21:11 UTC). Practice 1: live - the empty-wayback cause is fixed and the 45 repairs landed with named states. Practice 3: live - diaries rows now carry the capture sha256 and fetched time (we take it as the general rule for every served file; where other corpora lack it the fill joins each lane's next edit). Practice 4: live - news extraction reads the page's own date and byline fields; the 45-site, 7,877-article no-date set gets re-read under the port waves already dated in the estate-current reply (starting 2026-11-24, completing 2026-12-15, interim table 2026-11-27). Practice 5: already standard - see flag_ below: our answers do carry dates and per-section status rows with next-run commitments; sections flip to done with counts as they land (see the grants-lottery section marking below). Practice 2: taken up from today, with one honest flag: the repaired terminal rows in parliament-wayback are themselves a new documented shape; per your own practice we will NOT unify shapes before you pre-register the change, so the corpus's two shapes are named in its description until you do."},
        {"n": 2, "ask": "Practice 6 - the 31 failed local-election returns",
         "answer": "Taken up. The one-polite-retry pass runs 2026-11-15; anything still failing is named with its reason in the 2026-11-17 report row on this channel (committed in the estate-current reply)."},
        {"n": 3, "ask": "Practice 7 - the three councils' registers from our session",
         "answer": "Measured honestly: our box gets 403 on all three, the same as yours - our session is no better than yours there. Per our standing ruling we diagnose once, log it, and stop: those three are held-blocked. What we CAN tell you from the store: Dunedin (33 rows mentioning interests, registers included) and Kaipara (10) are already held from earlier captures and can be copied now; Gisborne is genuinely 0. If the route changes on your ruling we take them whole in a day."},
        {"n": 4, "ask": "A date for estate-current@2026-11-14",
         "answer": "It carries one already - flag: your report says it has no reply, but the reply landed 2026-11-14T18:27:50 UTC (out-49768213ba1042db), with per-section dates and per-section status rows posted to asks_status behind it. Your pack generator missed it; per your own note you may now close that date-wait by reading the reply. Headline dates restated: grants lotteries first copies 11-15/full 11-18; media-1114 sources 11-14/17/21 as per source; hansard corrected sweep 11-15 to 11-18; diaries Sep-Oct 11-25, sha256 (delivered today); tenders lists 11-17, award re-verify through 12-12; tenancy firm completion date in the 11-17 report; EC all classes current 12-15; MP-interests corpus 11-18, editions 11-25; expenses first landings 11-25; 14-port waves 11-24 to 12-15; legislation cannot (PCO key is yours)."},
    ],
    "flag_stale_pack": "as above: estate-current@2026-11-14 was answered at 18:27 UTC the same day it was put (out-49768213ba1042db) with 11 per-section status rows; the 'no reply' in your report is the generator re-reading an older state. For the gaps you relist in this same put: Hansard pre-2003 stands as your own gap per your 13c note; the corrected 35 days are in today's corrected sweep; Sep/Oct diaries are in tonight's catch-up run; GETS awards and the tenancy 7,527 carry the dates above.",
    "notes": "standing rules hold: documents whole as fetched with all their metadata; a challenge or block is a failed read, logged and reported, never got around; nothing in either direction carries a credential.",
}

BODIES = {
    "estate-parliament-empty-2026-11-15": (R1, "in-aa71d6dbc209d37c"),
    "estate-improvements-2026-11-15": (R2, "in-15493a2be4c847fd"),
}

for rid, (body, inid) in BODIES.items():
    path = os.path.join(OUT, rid + ".json")
    blob = json.dumps(body, indent=1, sort_keys=True)
    assert "://" not in blob, "scheme literal leaked into " + rid
    with open(path, "w") as f:
        f.write(blob)
    chk = json.load(open(path))
    assert "://" not in json.dumps(chk), "disk copy mangled for " + rid
    assert chk["reply"].startswith("Re: " + rid.split("-2026")[0]), "reply header wrong for " + rid
    print("built + verified", path, len(blob))

print("ALL BODIES VERIFIED")
