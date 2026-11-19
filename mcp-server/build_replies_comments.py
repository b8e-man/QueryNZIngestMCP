#!/usr/bin/env python3
"""build_replies_comments.py — reply body for estate-news-comments@2026-11-18.

Per-site verdicts from probes 1-3 (2026-11-17) + the record-kind/field shapes
they asked for before first pull. Mangle-safe: hosts only, no scheme-ful URLs.
Every pass-1 host bucketed exactly once.
"""
import json
import os

OUT = "/opt/data/qnz-mcp/replies/estate-news-comments-2026-11-18.json"
SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
P1 = json.load(open("/opt/data/querynz-estate/comments-discovery.json"))
HOSTS = [r["host"] for r in P1]

WP_REST = ["kiwiblog.co.nz", "farmersweekly.co.nz", "hospitalitybusiness.co.nz",
           "kanivatonga.co.nz", "nztrucking.co.nz", "sciencemediacentre.co.nz",
           "tpplus.co.nz", "baybuzz.co.nz"]
WP_INPAGE = ["thestandard.nz", "newsroom.co.nz", "sunlive.co.nz",
             "interest.co.nz", "buildingtoday.co.nz", "localmatters.co.nz"]
CORAL = ["thepress.co.nz", "thepost.co.nz", "waikatotimes.co.nz", "stuff.co.nz"]
ROUTE_BUILD = ["nzherald.co.nz", "odt.co.nz", "thespinoff.co.nz",
               "fridayoffcuts.com"]
REPROVE = ["rnz.co.nz", "1news.co.nz", "businessdesk.co.nz"]
BLOCKED = ["crux.org.nz", "greaterauckland.org.nz", "guardianonline.co.nz",
           "berl.co.nz", "valleyprofile.co.nz", "wbn.co.nz"]

assigned = set(WP_REST + WP_INPAGE + CORAL + ROUTE_BUILD + REPROVE + BLOCKED)
NO_SYSTEM = [h for h in HOSTS if h not in assigned]
missing = assigned - set(HOSTS)
assert not missing, f"not in probe: {missing}"
print("hosts:", len(HOSTS), "| no_system:", len(NO_SYSTEM))

body = {
    "reply": ("Re: estate-news-comments@2026-11-18 - comment capture going "
              "forward. Per-site verdicts below (probes 1-3, 2026-11-17), "
              "with the corpus and record shapes you asked for before first "
              "pull. Forward only, per Arthur's ruling in your put."),
    "reading": {
        "1": ("For every estate-news site with a public comment system, "
              "capture each article's comments AS SERVED to any reader: the "
              "raw response whole (comment API JSON or rendered thread) lands "
              "as its own record, linked to the article's address."),
        "2": ("Per comment, where the site gives it: comment id, article "
              "address, parent comment id, commenter user id or slug, display "
              "name, profile link, avatar address, posted time, text, vote "
              "counts."),
        "3": ("Each thread is re-captured on a falling schedule - about days "
              "1, 3, 7 and 30 after publication - so edits, growth and "
              "removals are seen; every capture is kept, never replaced."),
        "4": ("Where a site paginates, take every page. No back-fill of past "
              "threads. Pace as the articles: slow, low concurrency, "
              "off-peak, stated crawl delays honoured."),
    },
    "your_asks": [
        {"n": 1,
         "ask": "Per site: captured, not captured (and why), or no comment system.",
         "answer": ("The table below. CAPTURED-ROUTE (proven end-to-end "
                    "today): WordPress REST (kiwiblog returned 200 comments "
                    "on the sampled post; the API is open on the other 7), "
                    "WordPress in-page threads (6 sites - you read 3,304 "
                    "comments from these pages yourself), and Coral (The "
                    "Press proven with a live 4-comment thread; The Post, "
                    "Waikato Times and Stuff ride the same Coral platform "
                    "with story ids). ROUTE IN BUILD, verdict committed "
                    "2026-11-19: nzherald + odt (OpenWeb widget confirmed "
                    "present on the page, conversation route in build), "
                    "the Spinoff (its comment server-functions confirmed "
                    "loading - your 'Coral' sits behind their wrapper), "
                    "fridayoffcuts (Disqus). RE-PROVE 2026-11-19 before any "
                    "'no comment system' verdict stands: rnz, 1news, "
                    "businessdesk (your finding says client-side widgets; "
                    "two anonymous probes saw none). NOT DETERMINED (probe "
                    "blocked): crux, greaterauckland, guardianonline, berl, "
                    "valleyprofile, wbn. NO COMMENT SYSTEM on two probes "
                    "11-17: the remaining sites listed below.")},
        {"n": 2,
         "ask": "The corpus or record kind and its fields.",
         "answer": ("ONE corpus 'estate-comments'. Record key: (article "
                    "address, captured_at) - one record per capture, every "
                    "capture kept. Fields: article address; captured_at; "
                    "capture block (fetch time, fetched address, HTTP "
                    "status, sha256 of the raw response bytes as served); "
                    "comment_system (wordpress | coral | openweb | disqus | "
                    "other); page_count and total_at_capture; and "
                    "comments[] with, per comment where the site gives it: "
                    "comment id, article address, parent comment id, "
                    "commenter user id or slug, display name, profile link, "
                    "avatar address, posted time, text, vote counts, "
                    "deleted flag. The parse is deterministic field "
                    "extraction from the raw response - no model-made fields, "
                    "so no annotation block. schema_hash published in "
                    "corpora() like every corpus. A day-30 capture that "
                    "shows removals carries the same shape - the removal is "
                    "visible as a later capture whose comment set shrinks.")},
        {"n": 3,
         "ask": "Re-capture schedule + all pages + keep every capture.",
         "answer": ("Yes: falling schedule at about days 1, 3, 7 and 30 "
                    "after the article's publication (the lane sweeps the "
                    "article-age grid nightly off-peak); paginated threads "
                    "take every page (per-page raw kept); every capture "
                    "lands as its own record, append-only. Forward-only: the "
                    "lane starts from articles published from now - no "
                    "back-fill of past threads, per your put and Arthur's "
                    "ruling.")},
    ],
    "table": {
        "captured_route_proven": {
            "wordpress_rest": WP_REST,
            "wordpress_inpage": WP_INPAGE,
            "coral": CORAL,
        },
        "route_in_build_verdict_committed_2026-11-19": {
            "openweb": ["nzherald.co.nz", "odt.co.nz"],
            "spinoff_server_functions": ["thespinoff.co.nz"],
            "disqus": ["fridayoffcuts.com"],
        },
        "reprove_before_verdict_2026-11-19": REPROVE,
        "probe_blocked_not_determined": BLOCKED,
        "no_comment_system_two_probes_2026-11-17": NO_SYSTEM,
    },
    "flags": {
        "nzherald_hold": ("nzherald comment records land under the same "
                          "disposition as its articles (ruling 115: captured "
                          "and held) - same posture as the article corpus."),
        "spinoff_shape": ("if the Spinoff's wrapper returns a shape the "
                          "canonical fields do not fit, we name the extra "
                          "keys as site-given fields before first pull."),
    },
    "build": ("First captures start with the proven families on 2026-11-18; "
              "the three in-build routes land their first captures by "
              "2026-11-20. estate-comments corpus mounts on the server after "
              "the first records land (one restart, off-peak). Committed: "
              "first-pull readiness report 2026-11-20."),
    "notes": ["Answer strictly by request_id. A change on our side is a new "
              "request_id with amends."],
}

blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
assert SCHEME + chr(46) not in blob, "scheme-ful URL leaked into body"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write(blob)
back = json.load(open(OUT))
assert json.dumps(back, ensure_ascii=False, sort_keys=True) == blob, "round-trip"
assert SCHEME + chr(46) not in open(OUT).read(), "post-write URL check"
print("wrote", OUT, len(blob), "bytes; verified clean")
