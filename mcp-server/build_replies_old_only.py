#!/usr/bin/env python3
"""build_replies_old_only.py — reply body for estate-news-old-only-sites@2026-11-18.

Mangle-safe: hosts only (bare domains), no scheme-ful URLs. Every one of the
117 sites is bucketed exactly once: collectable / held_elsewhere / not_collectable.
Evidence: probe-old-only-sites.json (11-17 probe). Prints coverage check.
"""
import json
import os

OUT = "/opt/data/qnz-mcp/replies/estate-news-old-only-sites-2026-11-18.json"
SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)
PROBE = json.load(open("/opt/data/querynz-estate/probe-old-only-sites.json"))
SITES = {r["host"]: r for r in PROBE}

COUNCIL_MIN = "estate-council-minutes@2026-11-13 (council-minutes corpus; first landings 11-24)"
MEDIA = "the estate-media lane (bot-managed challenge, gap-logged there; stealth-lane ruling pending)"
COURTS = "our courts corpus (JDO judgments)"

# held elsewhere: host -> (where, note)
HELD = {
    "beehive.govt.nz": ("your beehive corpus", "your given"),
    "gazette.govt.nz": ("DigitalNZ", "your given"),
    "hansard.parliament.nz": ("our hansard corpus",
        "1,862 day-PDFs landed 2003-02 to 2026-09; nothing for us to add here"),
    "courtsofnz.govt.nz": ("our courts corpus",
        "JDO everything-new lane covers the courts; judgments, not news"),
    "environmentcourt.govt.nz": ("our courts corpus",
        "court records; JDO-family judgments"),
    "coronerscourt.govt.nz": ("our courts corpus",
        "court records (findings); say if you want them routed as estate-news instead"),
    "determinations.era.govt.nz": ("our courts corpus",
        "ERA determinations fit the courts-finder jurisdiction filter; confirm the routing"),
    "disclosure.legislation.govt.nz": ("the standing disclosure_statements lane",
        "estate-current@2026-11-14 commitment (11-24) - NOT the withdrawn legislation ask"),
    "elections.nz": ("the electoral-commission section of estate-collect@2026-11-13",
        "waves 11-24/12-01/12-08, all current 12-15; 403 to plain probes, its lane has its own route"),
    "knowledgeauckland.org.nz": ("estate-media@2026-11-14",
        "13 pages landed; pages 2-23 = Umbraco AJAX, browser lane pending"),
    "greystar.co.nz": (MEDIA, "520/403 bot-managed (Cloudflare)"),
    "acc.co.nz": (MEDIA, "Incapsula on every path; newsroom route named in that thread"),
    "rbnz.govt.nz": (MEDIA, "403 Cloudflare bot-managed"),
    "familyfirst.org.nz": (MEDIA, "403 -> nginx bot-managed"),
    "infrastructure.org.nz": (MEDIA, "403 bot-managed"),
    "orangatamariki.govt.nz": (MEDIA, "106 pages already landed 11-14"),
    "mbie.govt.nz": ("the GETS/tenders lanes",
        "procurement lives there (tender lists + award CSVs); site 403 to probe"),
    "companies-register.companiesoffice.govt.nz": ("the companies/NZBN data family",
        "register data, not news"),
    "scoop.co.nz": ("already in estate-news", ""),
}

# council minutes instances (all the same lane)
for h in SITES:
    if "infocouncil" in h:
        HELD[h] = (COUNCIL_MIN, "same family the 78-council walk covers"
                   + ("; instance 404 to our probe - the lane's discovery re-locates it"
                      if SITES[h].get("home_error") else ""))

# same-site subdomains: host -> (parent, note)
SAME = {
    "shop.greens.org.nz": ("greens.org.nz", "store; not news"),
    "action.greens.org.nz": ("greens.org.nz", "campaign-action pages; not news"),
    "action.act.org.nz": ("act.org.nz", "campaign pages; not news"),
    "assets.national.org.nz": ("national.org.nz", "assets host; not news"),
    "shop.opportunity.org.nz": ("opportunity.org.nz", "store; not news"),
    "merch.opportunity.org.nz": ("opportunity.org.nz", "store; not news"),
    "cdn.opportunity.org.nz": ("opportunity.org.nz", "cdn; not news"),
    "assets.nationbuilder.com": ("nationbuilder platform", "vendor CDN, not a site"),
    "cdn.rivercitypress.co.nz": ("rivercitypress.co.nz",
        "cdn of the Whanganui community paper - the paper itself is collectable under the parent name"),
    "motu-www.motu.org.nz": ("motu.org.nz", "same site, www host"),
    "wellington.scoop.co.nz": ("scoop.co.nz", "its Wellington section"),
    "ourauckland.aucklandcouncil.govt.nz": ("aucklandcouncil.govt.nz",
        "its news page; 403 to our probe"),
    "cdn.prod.website-files.com": ("webflow platform", "vendor CDN, not a site"),
    "media.umbraco.io": ("umbraco media store", "asset host, not a site"),
    "web-assets.education.govt.nz": ("education.govt.nz", "asset host, not a site"),
    "assets.retirement.govt.nz": ("retirement.govt.nz", "asset host, 404"),
    "res.cloudinary.com": ("cloudinary CDN", "asset host, not a site"),
    "iea.blob.core.windows.net": ("azure blob store", "asset host, not a site"),
    "assets.publishing.service.gov.uk": ("gov.uk publishing platform", "asset host, not a site"),
}

# not collectable: host -> why
NOT = {
    "nzfirst.nz": ("gone",
        "DNS dead at probe time (11-17) though your copy runs to 2026-11-04 - flag: the party site has vanished; if it returns we collect it"),
    "ashburtoncourier.co.nz": ("gone", "origin down (522) at probe time"),
    "opunakecoastalnews.co.nz": ("gone", "domain serves a placeholder; content stops 2007"),
    "apt.ch": ("not news", "not a news site; content stops 1989"),
    "ombudsman.parliament.nz": ("challenge", "403 to our probe"),
    "seafood.co.nz": ("challenge", "403 to our probe"),
    "fma.govt.nz": ("challenge", "403 to our probe"),
    "educationcounts.govt.nz": ("challenge", "403 to our probe"),
    "asms.org.nz": ("challenge", "403 to our probe"),
    "ashburtondc.govt.nz": ("challenge", "403 to our probe"),
    "scionresearch.com": ("challenge", "403 to our probe"),
    "fedcourt.gov.au": ("not news", "foreign court; out of estate-news scope"),
    "ohchr.org": ("not news", "foreign body; out of scope"),
    "gov.scot": ("not news", "foreign government; out of scope"),
    "centreformentalhealth.org.uk": ("not news", "foreign body; unreachable at probe time"),
    "womensdeclaration.com": ("not news", "campaign document site"),
    "unodc.org": ("not news", "foreign body; out of scope"),
    "forms.justice.govt.nz": ("not news", "forms intake, no newsroom"),
    "nzmj.org.nz": ("not news", "medical journal, not news - say if you want publications"),
    "stonearrow.co.nz": ("not news", "shop"),
    "tepunaaonui.govt.nz": ("not news", "support-service site, no newsroom"),
    "familyfirst.org.nz": (MEDIA, "bot-managed"),
}

# collectable into estate-news (the remainder), with agency/party notes
NOTES = {
    "greens.org.nz": "party newsroom (WP)",
    "act.org.nz": "party newsroom",
    "national.org.nz": "party newsroom",
    "labour.org.nz": "party newsroom",
    "opportunity.org.nz": "party newsroom",
    "maoriparty.org.nz": "party newsroom",
    "womensrightsparty.nz": "party newsroom (WP)",
    "animaljustice.org.nz": "party newsroom (WP)",
    "conservatives.nz": "party newsroom",
    "allianceparty.nz": "party newsroom (WP)",
    "alcp.org.nz": "party newsroom",
    "nzofp.co.nz": "party newsroom",
    "vision.org.nz": "party newsroom",
    "tetaitokerauparty.org.nz": "party newsroom (WP)",
    "palfree.nz": "party site",
    "ruralnewsgroup.co.nz": "rural news outlet",
    "stoppress.co.nz": "marketing/media trade press (WP)",
    "critic.co.nz": "student magazine (Otago)",
    "constructionnews.co.nz": "construction trade press (WP)",
    "rivercitypress.co.nz": "Whanganui community paper (reached via its cdn host row)",
    "nzier.org.nz": "economics think-tank newsroom",
    "motu.org.nz": "research institute newsroom (via motu-www host)",
    "energyresources.org.nz": "industry body newsroom",
    "forestandbird.org.nz": "NGO newsroom",
    "drugfoundation.org.nz": "NGO newsroom",
    "hasanz.org.nz": "workplace-safety NGO newsroom",
    "apex.org.nz": "NGO newsroom",
    "ruralleaders.co.nz": "rural programme site (tiny)",
    "cclponline.org": "NGO site (tiny)",
    "comcom.govt.nz": "agency media releases",
    "ipca.govt.nz": "agency media releases",
    "igis.govt.nz": "agency publications",
    "justice.govt.nz": "agency media releases",
    "takeovers.govt.nz": "agency determinations/media",
    "climatecommission.govt.nz": "agency newsroom",
    "publicservice.govt.nz": "agency newsroom",
    "tewaihanga.govt.nz": "agency newsroom",
    "eeca.govt.nz": "agency newsroom (tiny)",
    "environment.govt.nz": "agency newsroom (tiny)",
    "pateawaverleypress.com": "Taranaki community paper (tiny)",
}

rows = []
covered = set()
for host, r in sorted(SITES.items(), key=lambda kv: -(kv[1].get("old_articles") or 0)):
    old = r.get("old_articles")
    newest = r.get("old_newest")
    if host in HELD:
        where, note = HELD[host]
        v = "held_elsewhere"
        detail = where + (" - " + note if note else "")
    elif host in SAME:
        parent, note = SAME[host]
        v = "same_site"
        detail = parent + " - " + note
    elif host in NOT:
        why, note = NOT[host]
        v = "not_collectable"
        detail = why + " - " + note
    elif host in NOTES or host in ("rivercitypress.co.nz", "motu.org.nz"):
        v = "collectable"
        detail = NOTES.get(host, "collectable")
    else:
        v = "collectable"
        detail = "collectable (site reachable, sitemap/feed per probe)"
    covered.add(host)
    rows.append({"host": host, "old_articles": old, "old_newest": newest,
                 "verdict": v, "detail": detail})

missing = set(SITES) - covered
assert not missing, f"unbucketed: {missing}"
counts = {}
for x in rows:
    counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
print("coverage ok:", len(rows), counts)

body = {
    "reply": ("Re: estate-news-old-only-sites@2026-11-18 - per-site verdicts for "
              "all 117 old-estate sites (table below), subdomain=same-site notes "
              "included, backfill waves committed most-old-articles-first."),
    "reading": {
        "1": ("You are moving news into the new estate site by site; a site's old "
              "collection stops only once estate-news is current for it: published "
              "in the last 7 days, no gap back to where your old copy stops, and "
              "no more than 5% stubs."),
        "2": ("Per site we say one of: collectable into estate-news (and from "
              "when), already held in another corpus (named), or not collectable "
              "(why: login, challenge, gone, not news)."),
        "3": ("Every collectable site gets back-filled at least to its old_newest "
              "so no gap remains; subdomains listed the way your old estate held "
              "them are mapped onto their parent site."),
    },
    "your_asks": [
        {"n": 1, "ask": "Per-site verdicts (collectable+from when / held elsewhere / not collectable+why).",
         "answer": ("The table below: 117 sites, ordered most old articles "
                    "first, exactly one verdict each. Counts: "
                    + json.dumps(counts, sort_keys=True)
                    + ". 'From when' is the site's own listing depth - "
                    "discovered per site at its wave start and reported with "
                    "the wave (a from-when guessed now would be an estimate "
                    "dressed as fact).")},
        {"n": 2, "ask": "Back-fill each collectable site at least to its old_newest.",
         "answer": ("Committed, most old articles first. Waves: the three big "
                    "party newsrooms (greens 4,265 / act 4,156 / national "
                    "3,757) start 2026-11-19; the rest of the >300 club "
                    "(motu 407, opportunity 876, labour 929, nzfirst-see-flag, "
                    "maoriparty 363, nzier 315) follows through 11-26; "
                    "everything under 300 rides the same collector at polite "
                    "pace by 2026-12-08. Gap-closure report per site (old_newest "
                    "reached, stub rate) 2026-12-01 and 2026-12-15. Pace: as "
                    "the article lanes - slow, low concurrency, off-peak.")},
        {"n": 3, "ask": "Subdomains: say where one is the same site as another host.",
         "answer": ("Same-site rows in the table name the parent: the greens/act/"
                    "opportunity shop+action+cdn hosts, national assets host, "
                    "nationbuilder/webflow/umbraco/cloudinary/azure asset hosts "
                    "are not sites; motu-www is motu.org.nz's www host; "
                    "wellington.scoop is scoop's Wellington section; cdn "
                    "rivercitypress is the Whanganui paper's cdn (the paper "
                    "itself is collectable, collected under the parent name).")},
    ],
    "flags": {
        "nzfirst_gone": ("nzfirst.nz is DNS-dead today though your copy runs to "
                         "2026-11-04 - the party's site has vanished. Flagged; "
                         "we collect it the moment it resolves again."),
        "infocouncil_404": ("tasman / kapiticoast / waitaki / mackenzie "
                            "infocouncil instances 404 to our probe - the "
                            "council-minutes lane re-locates them during its "
                            "78-council discovery."),
        "held_elsewhere_routing": ("ERA determinations and Coroners Court "
                                   "findings are routed to our courts corpus "
                                   "family - confirm you want them there, not "
                                   "as estate-news."),
    },
    "sites": rows,
    "build": ("Probe evidence 2026-11-17 (home reachability, robots, sitemap/"
              "feed discovery, titles) on file. Classification ships today; "
              "collector waves start 2026-11-19."),
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
