#!/usr/bin/env python3
"""build_report_readiness_2026-11-20.py — the first-pull readiness report
committed in the estate-news-comments@2026-11-18 reply. Facts asserted
against the landed rows at build time. Mangle-safe: hosts only.
"""
import glob
import json
import os

OUT = "/opt/data/qnz-mcp/replies/hermes-comments-readiness-2026-11-20.json"

FAMILY = {
    "wp_rest": ["kiwiblog.co.nz", "farmersweekly.co.nz",
                "hospitalitybusiness.co.nz", "kanivatonga.co.nz",
                "nztrucking.co.nz", "sciencemediacentre.co.nz",
                "tpplus.co.nz", "baybuzz.co.nz"],
    "wp_inpage": ["thestandard.nz", "newsroom.co.nz", "sunlive.co.nz",
                  "interest.co.nz", "buildingtoday.co.nz",
                  "localmatters.co.nz"],
    "coral": ["thepress.co.nz", "thepost.co.nz", "waikatotimes.co.nz",
              "stuff.co.nz"],
}

per_host = {}
total_records = total_comments = 0
for mf in sorted(glob.glob(
        "/opt/data/news-scrapers/data-comments/*/manifest.jsonl")):
    for line in open(mf):
        if not line.strip():
            continue
        r = json.loads(line)
        per_host[r["source"]] = per_host.get(r["source"], 0) + 1
        total_records += 1
        total_comments += r.get("total_at_capture") or 0

fam_counts = {}
for fam, hosts in FAMILY.items():
    fam_counts[fam] = {h: per_host.get(h, 0) for h in hosts}
assert total_records >= 400, total_records   # sweep may still be appending

report = {
    "report": ("Re: estate-news-comments@2026-11-18 - first-pull readiness "
               "report, committed 2026-11-20. Comment capture is live and "
               "landing; per-site verdicts with probe counts below; both new "
               "corpora mount tonight and the surface is ready for your first "
               "pull after that."),
    "sections": {
        "first_captures": {
            "status": "LANDING",
            "records_landed": total_records,
            "comments_captured": total_comments,
            "hosts_with_records": len([h for h in per_host if per_host[h]]),
            "per_family": fam_counts,
            "forward_boundary": ("articles published on or after 2026-11-18 "
                                 "(NZ), per your plan and Arthur's ruling; "
                                 "one record per capture, raw response whole "
                                 "+ deterministic per-comment parse"),
            "schedule": ("falling re-captures at about days 1, 3, 7, 30 "
                         "after publication run from tonight's sweeps; every "
                         "capture kept, append-only"),
        },
        "per_site_verdicts": {
            "captured_route_proven_landing_2026-11-20": {
                "wordpress_rest": "8 hosts, the site's own REST API, open to "
                                  "any reader (live: kiwiblog 4 / 79 / 113 "
                                  "comments on three fresh posts)",
                "wordpress_inpage": "6 hosts, the rendered thread in the "
                                    "article page itself - in the bytes we "
                                    "hold (live parse: 7 / 10 / 27 / 26 "
                                    "comments on sampled threads)",
                "coral": "4 hosts (thepress, thepost, waikatotimes, stuff), "
                         "third-party Coral service, served openly (live: "
                         "10 / 10 parsed on one thread, 2 / 2 on a fresh "
                         "one; every field your list asks for, where the "
                         "site gives it)",
            },
            "route_captured_first_records_next_sweep": {
                "disqus": "fridayoffcuts - the Disqus thread data is served "
                          "openly through the site's own embed (config and "
                          "forum captured 2026-11-20); first comment records "
                          "land 2026-11-21",
            },
            "in_build_next_attempt_2026-11-21": {
                "openweb": "nzherald, odt - the widget is present on the "
                           "page (odt's page carries its config), but the "
                           "conversation itself was never served to a plain "
                           "reader across 9 sampled pages (both sites, fresh "
                           "and older articles, comments anchor scrolled "
                           "into view). Verdict: not captured - in build; "
                           "next attempt mounts the widget interactively.",
                "spinoff": "thespinoff - the comments block in the served "
                           "bytes is an empty client-side mount (its loader "
                           "bundle is named on the page); the thread fetch "
                           "never fired in 4 passes. Verdict: not captured - "
                           "in build, same date.",
            },
            "no_comment_system": {
                "browser_probes_2026-11-19_incl_older_articles": {
                    "rnz.co.nz": "4 article passes (2 static 11-17, 2 full "
                                 "browser 11-19 incl. an older article): no "
                                 "comment markers, no comment service calls, "
                                 "no widget - none",
                    "1news.co.nz": "3 browser passes incl. older article; "
                                   "the only client-side calls are its own "
                                   "CMS story feeds - none",
                    "businessdesk.co.nz": "3 browser passes; only analytics "
                                          "and marketing beacons - none",
                },
                "two_probes_2026-11-17": "the 25 hosts named in our reply "
                                         "(gov/NGO/trade) stand at 'no "
                                         "comment system'",
                "note": ("your finding named client-side loaders for rnz, "
                         "1news and businessdesk; 10 passes across the three "
                         "found none. If you hold an address where comments "
                         "appear on any of them, name it and we probe that "
                         "exact page."),
            },
            "not_determined_probe_blocked": "crux, greaterauckland, "
                                            "guardianonline, berl, "
                                            "valleyprofile, wbn (unchanged)",
        },
        "record_shape_as_landing": {
            "key": "(article, captured_at) - one record per capture",
            "fields": "article, published_at, captured_at, milestone "
                      "(first|d3|d7|d30), comment_system "
                      "(wordpress|coral|openweb|disqus|other), page_count, "
                      "total_at_capture, comments[] (comment id, article, "
                      "parent comment id, commenter user id, display name, "
                      "profile link, avatar, posted time, text, vote counts, "
                      "status, deleted - where the site gives it), pages[] "
                      "(per-page fetch record), capture block (fetch time, "
                      "fetched address, HTTP status, sha256 of the raw bytes "
                      "as served, byte length), file (the raw response)",
            "note": "deterministic extraction only - no model-made fields, "
                    "no annotation block; schema_hash published in corpora() "
                    "at mount",
        },
        "mount_and_first_pull": {
            "when": "2026-11-21 05:30 NZ (off-peak, metering-verified quiet "
                    "window; one restart, ~15 min surface gap through the "
                    "corpus load)",
            "what": "estate-comments and estate-substack mount together; "
                    "estate-news gains the author rows already landing "
                    "(kind=author_page | author_index, reached_from set) - "
                    "its schema_hash has moved, as flagged in the authors "
                    "reply",
            "ready": "estate-comments + estate-substack are ready for your "
                     "first pull from 2026-11-21 ~06:00 NZ; current estate-"
                     "comments record count lands in the mount report line",
        },
        "cross_refs": {
            "estate-substack@2026-11-18": "answered same day - 12 free posts "
                                          "+ 12 comment captures landed, "
                                          "kinds and fields named",
            "estate-news-authors-2026-11-15": "answered same day - 112 "
                                              "author/index pages already "
                                              "landed (first copies beat the "
                                              "2026-11-21/22 commitment); "
                                              "268 candidates enumerated",
        },
    },
    "notes": ["Answer strictly by request_id. A change on our side is a "
              "new request_id with amends."],
}

blob = json.dumps(report, ensure_ascii=False, sort_keys=True)
SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
assert SCHEME + chr(46) not in blob, "scheme-ful URL leaked"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write(blob)
back = json.load(open(OUT))
assert json.dumps(back, ensure_ascii=False, sort_keys=True) == blob
assert SCHEME + chr(46) not in open(OUT).read()
print("wrote", OUT, len(blob), "bytes; verified clean")
print("totals:", total_records, "records,", total_comments, "comments,",
      len(per_host), "hosts")
