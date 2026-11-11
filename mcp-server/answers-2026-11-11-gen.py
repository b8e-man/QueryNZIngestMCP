#!/usr/bin/env python3
"""Generate the point-by-point answer to the estate's provider pack
2026-11-11. Every row is keyed by the CONSUMER's request_id / gap_id (stable
across their regeneration). Output: reply-to-querynz-2026-11-11-2.json.

Answer vocabulary (declared in the letter):
  collector running          a lane is live and records land
  collector building         accepted; port in build; lane listed in
                             pipeline() as paused; closes when records land
  serving                    the ask is to serve held data and it is served
  cannot: <reason>           refusal / out of scope / conflict with a ruling
  nothing                    a withdrawn ask (their own instruction)
  inventory                  their `noted` rows (asked: null) — no action
"""
import json
import time

BASE = ("/opt/data/cache/documents/provider-pack-2026-11-11/"
        "provider-pack/")
OUT = "/opt/data/qnz-mcp/reply-to-querynz-2026-11-11-2.json"

stale = json.load(open(BASE + "mcp-stale.json"))
gaps = json.load(open(BASE + "mcp-gaps.json"))
oldc = json.load(open(BASE + "asks/old-collectors.json"))
news = json.load(open(BASE + "asks/news.json"))
tenders = json.load(open(BASE + "asks/tenders.json"))
tenancy = json.load(open(BASE + "asks/tenancy_tribunal.json"))

# corpus -> the pipeline() lane that collects it (2026-11-11)
LANES = {
    "estate-building_practitioners": "estate-building-practitioners",
    "estate-candidate_returns": "estate-candidate-returns",
    "estate-charities": "estate-charities",
    "estate-commerce_commission": "estate-commerce-commission",
    "estate-council_minutes": "estate-council-minutes",
    "estate-councillor_interests": "estate-councillor-interests",
    "estate-disclosures": "estate-disclosures",
    "estate-fma": "estate-fma",
    "estate-grants": "estate-grants",
    "estate-iwi_directory": "estate-iwi-directory",
    "estate-local_elections": "estate-local-elections",
    "estate-real_estate_authority": "estate-real-estate-authority",
    "estate-settlement_commitments": "estate-settlement-commitments",
    "estate-tenancy_tribunal": "estate-tenancy-tribunal",
    "estate-worksafe": "estate-worksafe",
    "estate-news": "news-capture",
    "estate-tenders": "mbie-bulk-csv",
    # the 14 ports (paused until first records land)
    "estate-disclosure_statements": "estate-disclosure-statements",
    "estate-regulatory_impact": "estate-regulatory-impact",
    "estate-waitangi_tribunal": "estate-waitangi-tribunal",
    "estate-coronial": "estate-coronial",
    "estate-environment_court": "estate-environment-court",
    "estate-district_court": "estate-district-court",
    "estate-disciplinary_tribunals": "estate-disciplinary-tribunals",
    "estate-watchdogs": "estate-watchdogs",
    "estate-elections_documents": "estate-elections-documents",
    "estate-expenses": "estate-expenses",
    "estate-party_sites": "estate-party-sites",
    "estate-companies_office_notices": "estate-companies-office-notices",
    "estate-legislation": "estate-legislation",
    "estate-motu": "estate-motu",
}

PORT_JOB = {a["corpus"]: a["old_estate_job"] for a in oldc["asks"]}

answers = []
_by_id = {}


def ans(key, answer, note=""):
    old = _by_id.get(key)
    if old is None:
        item = {"id": key, "answer": answer, "note": note}
        _by_id[key] = item
        answers.append(item)
        return
    # their pack reuses an id across sections — keep the more specific
    # answer, and both notes
    if len(answer) > len(old["answer"]):
        old["answer"] = answer
    if note and note not in old["note"]:
        old["note"] = (old["note"] + " | " if old["note"] else "") + note


# ---------------------------------------------------------------- mcp-stale
for r in stale.get("stale", []):
    ans(r["request_id"], "collector running",
        f"lane {LANES.get(r['corpus'], '?')}")
for r in stale.get("no_collector", []):
    lane = LANES.get(r["corpus"], "?")
    ans(r["request_id"], "collector running",
        f"lane {lane} now visible in pipeline(); runner: the estate "
        f"scheduler (once-nightly off-peak). Corpus newest_arrival moves "
        f"on its own cadence ({r.get('cadence_days')}d)")
for r in stale.get("short_of_source", []):
    rid = r["request_id"]
    corpus = r["corpus"]
    if corpus == "estate-news":
        ans(rid, "collector running",
            "corpus estate-news serves the news (883 records at first "
            "mount; 58 outlets landing). NZME per ruling 169: nzherald.co.nz "
            "live 2026-11-11, 24 articles landed from 2026-10-18 01:15 NZ; "
            "businessdesk.co.nz cannot be collected yet — measured "
            "2026-11-11: 395 discovered, 100 fetched, 100 thin, 0 landed "
            "(subscriber teasers only). A subscription + login lane lifts "
            "it. Daily-cadence collector runs (news-capture). Catch-up over "
            "the 17/18 Oct window trickles at the outlets' own publication "
            "rates — the gap closes as records land.")
    elif corpus == "estate-tenders":
        ans(rid, "serving",
            "the catalogue package is served as corpus estate-tenders, "
            "each file verbatim by hash: 8 of 9 files live (ids = sha256 "
            "of the bytes; our 3 originals' hashes match your "
            "we_hold_sha256 exactly). gets-product-categories-historic.csv "
            "not yet landed (served as a browser download) — lands via the "
            "daily re-check. Changed bytes land as a new record; unchanged "
            "bytes never re-land.")
    elif corpus == "estate-tenancy_tribunal":
        ans(rid, "collector running",
            "worked soonest-take-down-first (qv4-tenancy-tribunal-capture, "
            "nightly). Ask queue: 13,249 of 13,249 still open at "
            "2026-11-11T04:55Z, lane estate-tenancy-ask-2026-11-11, queue "
            "refreshed nightly. Earliest take-down 2028-06-23 has runway; "
            "the gap closes as records land.")
    else:
        lane = LANES.get(corpus, "?")
        ans(rid, "collector building",
            f"port of the old estate's {PORT_JOB.get(corpus, 'collectors')} "
            f"in build (2026-11-11 handover verified: 73 files, all "
            f"sha256 OK); lane {lane} listed in pipeline() as paused and "
            f"opens when its first records land")

# ------------------------------------------------------------------- asks
ans(news["request_id"], "collector running",
    "see estate-news rows above. Outlets we cannot collect and why: "
    "odt.co.nz (paywall: subscriber teasers only, no body served), "
    "businessdesk.co.nz (paywall: measured 2026-11-11, 395 discovered / 100 "
    "fetched / 100 thin / 0 landed — a subscription + login lane lifts "
    "either), ruralnewsgroup.co.nz (antibot: "
    "refuses every route including the residential exit), greystar.co.nz "
    "(robots refused/unreadable), thedailyblog.co.nz / e-tangata.co.nz / "
    "stoppress.co.nz / ourauckland.org.nz / voxy.co.nz / rbnz.govt.nz "
    "(anti-bot challenges or shells — frozen at Arthur's word 2026-11-09, "
    "reviewed one by one), newsroom.co.nz / nbr.co.nz (credentials — run "
    "only with logins that are ours). fyi.org.nz: not collected (your "
    "ruling 168). NZME capture-and-hold (our ruling 115): the nzherald "
    "network lands raw and is served raw; extraction and embedding stay "
    "withheld until an NZME licence lands — your legal lane reviews before "
    "display (our ruling 94).")
ans(tenders["request_id"], "serving",
    "corpus estate-tenders: 8 of 9 files verbatim by hash now; the 9th "
    "follows on the daily re-check (the Ministry's cadence is about "
    "quarterly; we re-check daily and land a new record only when the "
    "bytes change). File ids are the sha256 of the bytes — id permanence "
    "per version.")
ans(tenancy["request_id"], "collector running",
    "see the estate-tenancy_tribunal short_of_source row.")
for a in oldc["asks"]:
    ans(a["request_id"], "collector building",
        f"accepted; port of {a['old_estate_job']} in build; lane "
        f"{LANES.get(a['corpus'], '?')} in pipeline(). Your crawl stops "
        f"per your own rule once our copy has new records.")

# -------------------------------------------------------------------- gaps
NEWS_CANNOT = ("cannot: your rulings 161/163 copy the old estate's news "
               "archive whole into the new estate, and your news ask "
               "(estate-news@serve-67-from-2026-11-11) states the 2003-2026 "
               "archive needs no backfill — we read this row as inventory; "
               "say so if you want it gathered anyway")
REF_CANNOT = ("cannot: out of scope — a worldwide reference dataset with no "
              "NZ join value (the GeoNames precedent: LINZ place names cover "
              "what is needed)")
PARTY_BUILD = ("collector building (lane estate-party-sites): whole-site "
               "recapture; historical depth will trickle at polite crawl "
               "rates — closes as records land")

# the rows named in the letter (biggest of each class) — full answers
OVERRIDES = {
    "wikidata@none#all": REF_CANNOT,
}
for g in gaps.get("withdrawn", []):
    OVERRIDES[g["gap_id"]] = "nothing (your ruling)"
for g in gaps.get("closed", []):
    OVERRIDES[g["gap_id"]] = "closed"

cat_rules = {
    "reference dataset": REF_CANNOT,
    "party site": PARTY_BUILD,
}

for g in gaps.get("gaps", []):
    gid = g["gap_id"]
    if gid in OVERRIDES:
        ans(gid, OVERRIDES[gid])
        continue
    cat = (g.get("category") or "").lower()
    if gid.startswith("articles:") and cat.startswith("news"):
        ans(gid, NEWS_CANNOT)
    elif gid.startswith("articles:") and cat.startswith("party"):
        ans(gid, PARTY_BUILD)
    elif cat in cat_rules:
        ans(gid, cat_rules[cat])
    elif "gets" in gid or "mbie" in gid.lower():
        ans(gid, "serving: the award rows live inside the files now served "
                 "as estate-tenders (gets-award-notices*.csv, verbatim by "
                 "hash); ingest closes this when the rows land in your "
                 "register")
    else:
        ans(gid, "collector building",
            "queued in the porting/gather programme; closes when records "
            "land (no lane yet means no records yet — never a silent drop)")
for g in gaps.get("noted", []):
    ans(g["gap_id"], "inventory", "your asked: null — no action")
for g in gaps.get("withdrawn", []):
    ans(g["gap_id"], "nothing (your ruling)",
        g.get("why", ""))

out = {
    "schema_version": 1,
    "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "in_reply_to": "provider-pack-2026-11-11",
    "vocabulary": ["collector running", "collector building", "serving",
                   "cannot: <reason>", "nothing", "inventory"],
    "answers": answers,
}
with open(OUT, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)

# summary for the letter
from collections import Counter
c = Counter(a["answer"].split(":")[0] for a in answers)
print(f"wrote {OUT}: {len(answers)} answers")
for k, v in c.most_common():
    print(f"  {k}: {v}")
ids = {a["id"] for a in answers}
need = ([r["request_id"] for r in stale["no_collector"]]
        + [r["request_id"] for r in stale["short_of_source"]]
        + [a["request_id"] for a in oldc["asks"]]
        + [news["request_id"], tenders["request_id"], tenancy["request_id"]]
        + [g["gap_id"] for g in gaps["gaps"] + gaps["noted"] + gaps["withdrawn"]])
missing = [x for x in need if x not in ids]
print("request ids not answered:", len(missing), missing[:5])
from collections import Counter as C2
dups = [k for k, v in C2(a["id"] for a in answers).items() if v > 1]
print("duplicate ids:", len(dups), dups[:5])
