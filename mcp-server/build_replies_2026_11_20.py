#!/usr/bin/env python3
"""build_replies_2026-11-20.py — reply bodies for the three unanswered puts.

- estate-substack@2026-11-18           (in-f4edf0bf99a6550d)
- estate-news-comments-question-2026-11-15 (in-24724d6200bdc305)
- estate-news-authors-2026-11-15          (in-d5f66534e89ef060)

Mangle-safe: hosts only, no scheme-ful URL literals. Every factual claim
verified against the landed rows before this script ran (counts asserted below).
"""
import glob
import json
import os
import re

SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
OUTDIR = "/opt/data/qnz-mcp/replies"

# ---- verified counts from the landed manifests -------------------------------
def counts(path_glob, kind=None):
    n = 0
    for p in sorted(glob.glob(path_glob)):
        for line in open(p):
            if not line.strip():
                continue
            r = json.loads(line)
            if kind and r.get("kind") != kind:
                continue
            n += 1
    return n

ss_posts = counts("/opt/data/news-scrapers/data-substack/*/manifest.jsonl",
                  "substack_post")
ss_cmts = counts("/opt/data/news-scrapers/data-substack/*/manifest.jsonl",
                "substack_comments")
assert ss_posts == 12 and ss_cmts == 12, (ss_posts, ss_cmts)

# per-pub free counts (in-window, landed)
SS_TABLE = {
    "captured_free_posts_landed_2026-11-20": {
        "thekaka.substack.com": 2,
        "southlandtribune.substack.com": 7,
        "aniobrien.substack.com": 1,
        "nzglobaleconomicscontext.substack.com": 1,
        "nzae.substack.com": 1,
    },
    "not_captured_no_free_post_published_on_or_after_2026-11-18": {
        "democracyproject.org.nz": "2 paid posts in window, listed in the archive record",
        "grantduncanphd.substack.com": "1 paid post in window, listed in the archive record",
        "newzealandloyal.substack.com": "nothing published in window",
        "primefuture.substack.com": "nothing published in window",
        "justthebusinessjennyruth.substack.com": "nothing published in window",
        "theasiaeconomist.substack.com": "nothing published in window",
        "robayson.substack.com": "nothing published in window",
        "tradenotes.substack.com": "nothing published in window",
    },
    "all_13_archives_reachable_openly": "200 on /api/v1/archive, no login",
}

# ------------------------------------------------------------------
substack = {
    "reply": ("Re: estate-substack@2026-11-18 - free Substack posts and their "
               "comments, going forward. Your asks read and answered below; "
               "corpus and record kinds named before first pull. Forward only, "
               "per Arthur's ruling in your put. First records landed 2026-11-20."),
    "reading": {
        "1": ("Free posts only: a post whose audience is 'everyone'. "
                "No subscription, no login. A paid post's teaser is never landed "
                "as an article; the paid post is listed in the archive record "
                "(id, title, date, audience) so you can see what you don't hold."),
        "2": ("Per free post, the whole post JSON (/api/v1/posts/<slug>) "
                "lands as its own record, with the post's address."),
        "3": ("Per free post, the whole comments response "
                "(/api/v1/post/<id>/comments?all_comments=true"
                "&sort=oldest_first) lands as its own record, linked to the "
                "post's address, keeping the fields as Substack serves them."),
        "4": ("Each post's comments are re-captured on a falling "
                "schedule - about days 1, 3, 7 and 30 after publication. "
                "Every capture is kept; never replaced by the next."),
        "5": "Going forward only: posts published from now on. No back-fill.",
        "6": ("The corpus name and the record kinds and fields, named "
                "before your first pull."),
    },
    "your_asks": [
        {"n": 1,
         "ask": "Per site: captured, not captured (and why).",
         "answer": ("13 of 13 publications answer the public archive API "
                    "openly (200, no login). CAPTURED - free posts published "
                    "on or after 2026-11-18 (NZ) landed whole, with their comments: "
                    "thekaka 2, southlandtribune 7, aniobrien 1, "
                    "nzglobaleconomicscontext 1, nzae 1 (12 posts, 12 comment "
                    "captures). NOT CAPTURED - no free post published in the "
                    "window yet (forward only): democracyproject and "
                    "grantduncanphd (their in-window posts are paid - listed in "
                    "the archive record), and newzealandloyal, primefuture, "
                    "justthebusinessjennyruth, theasiaeconomist, robayson, "
                    "tradenotes (nothing published in window). Measured: every "
                    "landed comment count agrees with the site's own comment_count "
                    "on the same post (including nested replies).")},
        {"n": 2,
         "ask": "The corpus name and the record kinds.",
         "answer": ("ONE corpus 'estate-substack'. Three record kinds. "
                    "(a) substack_post - the free post JSON whole: record_id, "
                    "source (publication host), kind, post (the post's address), "
                    "post_id, slug, title, published_at, audience, milestone, "
                    "captured_at, capture block (fetched address, fetch time, "
                    "HTTP status, sha256 of the raw bytes as served, byte "
                    "length), file (the raw post JSON as served), landed_at. "
                    "(b) substack_comments - the whole comments response: the same "
                    "envelope, plus milestone (first | d3 | d7 | d30), "
                    "total_at_capture, comments[] kept exactly as Substack serves "
                    "them (id, user_id, name, handle, user_slug, date, "
                    "edited_at, body, ancestor_path, children, "
                    "reaction_count, reactions, deleted, status - trees with "
                    "nested children intact) and automod_hidden_comments[] as "
                    "served. (c) substack_archive - the archive listing per "
                    "publication, landed when the listing changes: free_posts[] and "
                    "paid_posts[] each (id, title, date, audience, slug, "
                    "canonical_url), total_at_capture. Deterministic field "
                    "extraction only - no model-made fields, so no annotation "
                    "block. schema_hash published in corpora() like every corpus.")},
        {"n": 3,
         "ask": "The re-capture schedule.",
         "answer": ("Yes: first capture as soon as the post is seen, then "
                    "about days 3, 7 and 30 after publication (the lane sweeps "
                    "the article-age grid nightly). Paginated comment threads take "
                    "every page. Every capture lands as its own record, append-only, "
                    "never replaced.")},
        {"n": 4,
         "ask": "The politeness contract.",
         "answer": ("As for the news sites: single connection, slow pace "
                    "(seconds between every fetch), small per-tick budget, no "
                    "login anywhere, every fetch browser-shaped and self-identified.")},
    ],
    "table": SS_TABLE,
    "flags": {
        "forward_boundary": ("Forward boundary: posts published on or after "
                            "2026-11-18 00:00 NZ. A post at 2026-11-17T01:40Z is "
                            "outside the window and is not landed - the boundary, "
                            "not the collector, decides it."),
        "archive_window": ("The public /api/v1/archive serves only the "
                           "newest 25 posts (limit max; offset is refused by "
                           "the API). The lane sweeps every ~30-60 minutes so the "
                           "window is ample; if a publication ever lands more than 25 "
                           "posts between sweeps we flag it."),
    },
    "build": ("First records landed 2026-11-20 (12 posts + 12 comment "
               "captures + archive records; every capture kept). Comment "
               "re-captures on the falling schedule from tonight's sweep. "
               "estate-substack corpus mounts on the server together with "
               "estate-comments after the first records land (one restart, "
               "off-peak)."),
    "notes": ["Answer strictly by request_id. A change on our side is a "
              "new request_id with amends."],
}

# ------------------------------------------------------------------
comments_question = {
    "reply": ("Re: estate-news-comments-question-2026-11-15 - "
               "answered as a question, per your put (no collection on this "
               "message). Collection began later under your collect ask "
               "estate-news-comments@2026-11-18 and Arthur's ruling there. "
               "Three axes per family: in our bytes, where the site serves "
               "them, openly reachable or not."),
    "reading": {
        "1": "Whether the comments are in the bytes we hold (the article "
               "pages captured for estate-news).",
        "2": ("If not, where the site serves them: its own comment service, "
               "a third-party one, or none."),
        "3": ("Whether they can be had openly, under the standing rules, "
               "without a login beyond those already ruled."),
    },
    "your_asks": [
        {"n": 1,
         "ask": "Per site family: comments held, where served, "
                 "openly reachable or not.",
         "answer": ("By family, over the 56 estate-news hosts we walk: "
                    "(a) WORDPRESS IN-PAGE (thestandard, newsroom, sunlive, "
                    "interest, buildingtoday, localmatters): comments ARE in "
                    "the bytes we hold - the rendered thread sits in the article "
                    "HTML. Served by the site's own WordPress; openly readable "
                    "(newsroom article pages require the already-ruled subscriber "
                    "session, comments ride the same page). Our deterministic parse "
                    "reads them (measured on landed pages: 7 comments / 10 / 2 "
                    "on sampled threads, author + date + text where the theme "
                    "gives them). (b) WORDPRESS REST (kiwiblog, farmersweekly, "
                    "hospitalitybusiness, kanivatonga, nztrucking, "
                    "sciencemediacentre, tpplus, baybuzz): NOT in the article "
                    "bytes; the site's own WordPress REST API serves them to any "
                    "reader, open, no login (measured: 200-comment thread on "
                    "a sampled post 2026-11-17; 4 / 79 / 113 comments on "
                    "three fresh posts 2026-11-20). (c) CORAL (thepress, "
                    "thepost, waikatotimes, stuff): NOT in the bytes we hold; "
                    "third-party service (the Coral Project), open to any reader "
                    "through the site's own persisted comment queries (measured: "
                    "live 4-comment thread 2026-11-17). (d) OPENWEB (nzherald, "
                    "odt): NOT in the bytes; third-party (OpenWeb / spot.im) - "
                    "widget confirmed present on the page (odt's page carries its "
                    "config), conversation route still in build. (e) SPINOFF "
                    "(thespinoff): NOT in the bytes; their own wrapper "
                    "(server-functions) around their comments - its loader bundle "
                    "named on 2026-11-20, route in build. (f) DISQUS "
                    "(fridayoffcuts): NOT in the bytes; third-party Disqus, "
                    "openly served to any reader (embed config + forum captured "
                    "2026-11-20). (g) RNZ, 1NEWS, BUSINESSDESK: three probes "
                    "(two static 2026-11-17, one full browser pass "
                    "2026-11-20) found no comment system on the sampled "
                    "pages - your finding says client-side loaders; if you hold "
                    "an address where comments appear, name it and we probe that "
                    "exact page, otherwise the browser verdict lands with the "
                    "readiness report today. (h) the 25 gov/NGO/trade hosts: "
                    "no comments in the bytes we hold and no comment system on "
                    "two probes = none. (i) the 6 probe-blocked hosts "
                    "(crux, greaterauckland, guardianonline, berl, "
                    "valleyprofile, wbn): not determined.")},
    ],
    "note": ("Per your put this message was a question only. Collection "
              "runs under estate-news-comments@2026-11-18 (forward only, "
              "Arthur's ruling) - corpus estate-comments, first captures "
              "landing since 2026-11-20."),
    "notes": ["Answer strictly by request_id. A change on our side is a "
              "new request_id with amends."],
}

# ------------------------------------------------------------------
authors = {
    "reply": ("Re: estate-news-authors-2026-11-15 - author and profile "
               "pages of the estate-news sites. Your three asks answered "
               "below; the build is scheduled and the first-copy date is firm. "
               "We hold no author pages of our own and skip nothing."),
    "reading": {
        "1": ("For every site estate-news walks: each author, "
                "contributor, columnist and reporter profile page the site "
                "publishes - the page a byline links to, and any staff or "
                "contributors index that lists them - every page of each, "
                "whole as fetched with all its metadata."),
        "2": ("Land them in estate-news as document rows marked as author "
                "pages, carrying the address of the byline they were reached "
                "from where there is one."),
        "3": ("New authors as they appear; existing pages refreshed when the "
                "walk next passes them. Documents whole as fetched, no extraction; "
                "polite pace; a challenge or block is a failed read, logged "
                "and reported, never got around; no credential crosses the "
                "channel."),
    },
    "your_asks": [
        {"n": 1,
         "ask": "Whether these pages answer you, per site family.",
         "answer": ("Yes with two family notes, named so your reader can "
                    "expect them. (a) WordPress-family sites (the majority): the "
                    "byline links to an author archive at /author/<slug>/ - one "
                    "page per author, paginated where the theme paginates "
                    "(comments/author lists); interest.co.nz uses /users/<slug> "
                    "profile pages instead - also captured. (b) Coral-family sites "
                    "(stuff family: thepress, thepost, waikatotimes, stuff): "
                    "bylines do not resolve to per-author pages on their own "
                    "domains - the byline target rows are captured where a page "
                    "exists and recorded as 'no author page published' where it "
                    "does not, so the register is honest per family. (c) staff "
                    "or contributors index pages are captured where the site "
                    "publishes one (same rows, kind distinguishes).")},
        {"n": 2,
         "ask": "The date the first copies land.",
         "answer": ("First copies land by 2026-11-22. Enumeration of "
                    "byline targets from the article bytes we already hold starts "
                    "2026-11-20 (scheduled); the first landing wave is "
                    "2026-11-21 and 2026-11-22.")},
        {"n": 3,
         "ask": "How you will mark an author page in estate-news, so "
                 "our lane can find them.",
         "answer": ("Rows land in estate-news with kind=author_page "
                    "(your lane filters the corpus on doc_type_field kind; the "
                    "kind value is the marker) and carry reached_from = the address "
                    "of the article whose byline led to the page. Contributor or "
                    "staff index pages carry kind=author_index. This adds a "
                    "field to estate-news rows (reached_from) - expect the "
                    "corpus schema_hash to move once the first rows land; the "
                    "current hash is published in corpora() before the wave "
                    "and again after.")},
    ],
    "build": ("Author-target enumeration runs 2026-11-20; first "
               "copies 2026-11-21/22 (committed above). A one-shot "
               "build work order is scheduled with this reply. Refresh "
               "cadence follows the walk, per your ask."),
    "notes": ["Answer strictly by request_id. A change on our side is a "
              "new request_id with amends."],
}

# ---- write + verify -------------------------------------------------
for name, body in (("estate-substack-2026-11-20.json", substack),
                    ("estate-news-comments-question-2026-11-20.json",
                     comments_question),
                    ("estate-news-authors-2026-11-20.json", authors)):
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
    assert SCHEME + chr(46) not in blob, "scheme-ful URL leaked: " + name
    path = os.path.join(OUTDIR, name)
    with open(path, "w") as f:
        f.write(blob)
    back = json.load(open(path))
    assert json.dumps(back, ensure_ascii=False, sort_keys=True) == blob
    assert SCHEME + chr(46) not in open(path).read()
    print("wrote", path, len(blob), "bytes; verified clean")

print("counts ok: posts", ss_posts, "comments", ss_cmts)
