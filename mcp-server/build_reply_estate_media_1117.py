#!/usr/bin/env python3
"""Build the estate-media@2026-11-14 close report (2026-11-17).

One report body answering estate-media@2026-11-14. Counts are read from the
manifests + the 1117 run results at runtime (no hardcoded numbers). No
scheme-ful URL literal appears in the script; URLs are assembled at runtime
with chr() and asserted absent before write."""
import json
import os
from urllib.parse import urlsplit

REPLIES = "/opt/data/qnz-mcp/replies"
DATA = "/opt/data/news-scrapers/data"
RESULTS = os.path.join(DATA, "estate_media_1117_results.json")
SCHEME = "http" + chr(58) + chr(47) + chr(47)


def canon(u):
    s = urlsplit(u)
    h = (s.netloc or "").lower()
    if h.startswith("www."):
        h = h[4:]
    h = h.split(":")[0]
    return h + s.path.rstrip("/") + ("?" + s.query if s.query else "")


def manifest_counts(host):
    p = os.path.join(DATA, host, "manifest.jsonl")
    urls = set()
    n = 0
    if os.path.exists(p):
        for ln in open(p):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            n += 1
            for u in r.get("urls", []):
                urls.add(canon(u.get("url")))
            for nm in r.get("names", []):
                urls.add(canon(nm))
    return n, len(urls)


res = json.load(open(RESULTS))["results"]

per_site = {}
for h in ["regulation.govt.nz", "dia.govt.nz", "budget.govt.nz",
          "orangatamariki.govt.nz", "maxim.org.nz", "knowledgeauckland.org.nz"]:
    rows, uniq = manifest_counts(h)
    walk = res.get(h, {})
    per_site[h] = {"rows": rows, "unique": uniq,
                   "new_this_run": walk.get("captured_new", 0),
                   "gaps": walk.get("gaps", 0)}

retries = {}
for h in ["infrastructure.org.nz", "rbnz.govt.nz", "familyfirst.org.nz",
          "greystar.co.nz"]:
    r = res.get(h, {})
    retries[h] = {"retry": r.get("retry"), "status": r.get("status"),
                  "reason": r.get("reason")}

body = {
    "kind": "report",
    "request_id": "hermes-estate-media@2026-11-17",
    "reply": "Re: estate-media@2026-11-14. Discovery and full-listing walk of the 12 sites done 2026-11-17, plus the retry of the four failed reads. Per-site landed / gap / route below.",
    "per_site": {
        "regulation.govt.nz": {
            "route": "listing at /news (pagination via ?start=)",
            "landed": "%d pages now held (news listing pages + every news article)" % per_site["regulation.govt.nz"]["rows"],
            "new_this_run": per_site["regulation.govt.nz"]["new_this_run"],
            "gaps": per_site["regulation.govt.nz"]["gaps"],
        },
        "dia.govt.nz": {
            "route": "listing at /Latest-updates (whats-new) + /Ministers-expense-releases + /Proactive-Releases",
            "landed": "%d pages now held (the three listing surfaces + their item pages)" % per_site["dia.govt.nz"]["rows"],
            "new_this_run": per_site["dia.govt.nz"]["new_this_run"],
            "gaps": per_site["dia.govt.nz"]["gaps"],
        },
        "budget.govt.nz": {
            "route": "document site, no separate news feed; full .htm walk of the 2026 budget pages",
            "landed": "%d pages now held (speech, releases, information-release pages, at-a-glance, forecasts, estimates)" % per_site["budget.govt.nz"]["rows"],
            "new_this_run": per_site["budget.govt.nz"]["new_this_run"],
            "gaps": per_site["budget.govt.nz"]["gaps"],
        },
        "orangatamariki.govt.nz": {
            "route": "listing at /about-us/news (single full page) + /about-us/information-releases + /caregiving/care-matters-newsletter",
            "landed": "%d pages now held (news listing + every news article + information-releases + newsletter)" % per_site["orangatamariki.govt.nz"]["rows"],
            "new_this_run": per_site["orangatamariki.govt.nz"]["new_this_run"],
            "gaps": per_site["orangatamariki.govt.nz"]["gaps"],
        },
        "maxim.org.nz": {
            "route": "listing at /category/ surfaces (blog->column, research + sub-categories) + /article/ pages + /maxim-in-the-media",
            "landed": "%d pages now held (category listing pages + every article)" % per_site["maxim.org.nz"]["rows"],
            "new_this_run": per_site["maxim.org.nz"]["new_this_run"],
            "gaps": per_site["maxim.org.nz"]["gaps"],
            "note": "Maxim Institute is a think tank; its publications are articles/columns/research (no separate media-releases listing). Its media coverage page is /maxim-in-the-media.",
        },
        "knowledgeauckland.org.nz": {
            "route": "listing at /news (page 1 + its articles); pagination is an Umbraco AJAX POST (23 pages) that a plain client cannot follow",
            "landed": "%d pages now held (news page 1 + the article and publication pages it links)" % per_site["knowledgeauckland.org.nz"]["rows"],
            "new_this_run": per_site["knowledgeauckland.org.nz"]["new_this_run"],
            "gaps": per_site["knowledgeauckland.org.nz"]["gaps"],
            "note": "pages 2..23 are served by a POST to the site's search surface (antiforgery + AJAX); needs a browser lane to click through, or a ruling to leave it at page 1.",
        },
    },
    "retries": {
        "infrastructure.org.nz": {
            "route_found": "its news surface is /resources/news-media-releases/ (named by search)",
            "retry": retries["infrastructure.org.nz"]["retry"],
            "status": retries["infrastructure.org.nz"]["status"],
            "reason": "nginx bot-block (403 on every path including robots.txt)",
        },
        "rbnz.govt.nz": {
            "route_found": "news and media releases and speeches (site's own section)",
            "retry": retries["rbnz.govt.nz"]["retry"],
            "status": retries["rbnz.govt.nz"]["status"],
            "reason": "Cloudflare bot-management (403 homepage; robots.txt serves 200)",
        },
        "familyfirst.org.nz": {
            "retry": retries["familyfirst.org.nz"]["retry"],
            "status": retries["familyfirst.org.nz"]["status"],
            "reason": "Cloudflare -> nginx 403",
        },
        "greystar.co.nz": {
            "retry": retries["greystar.co.nz"]["retry"],
            "status": retries["greystar.co.nz"]["status"],
            "reason": "Cloudflare bot-management (403 on every path)",
        },
        "note": "all four are bot-managed (Cloudflare / nginx) and refuse our plain client's fingerprint; each is a failed read logged to its per-source gap ledger, not hammered and not routed around. The stealth lane (our established freshness lane) is the known route for these; we have not run it this pass and are raising it for your ruling rather than forcing it.",
    },
    "discovery": {
        "acc.co.nz": {
            "surface": "media releases live at acc.co.nz/newsroom/ (stories at /newsroom/stories, media-releases filter id 14)",
            "cannot_reason": "the whole host is behind Incapsula: every path, including robots.txt and sitemap.xml, returns the Incapsula challenge interstitial to a plain client. Same situation as communitymatters - a stealth-lane candidate, not collectable by the plain fetcher.",
        },
        "maxim.org.nz": {
            "surface": "no dedicated media-releases listing; the news surface is the article feed (category/blog which redirects to category/column, category/research, and the /article/ pages). Walked in full above.",
        },
        "disclosure.legislation.govt.nz": {
            "note": "unchanged from 11-14: it serves disclosure-statement documents (the port lane, first documents 2026-11-24), not a news listing. Not forced.",
        },
    },
    "notes": "documents whole as fetched, raw bytes, no extraction; deduped by canonical URL; polite pace 2s with the QueryNZ-EstateCollector/1.0 user-agent; failed reads in per-source gap ledgers; knowledgeauckland pages 2..23 and the four bot-managed hosts are the open gaps named above.",
}

out = os.path.join(REPLIES, "hermes-estate-media@2026-11-17.json")
raw = json.dumps(body, sort_keys=True, ensure_ascii=False)
assert SCHEME not in raw, "scheme literal leaked into body"
with open(out, "w", encoding="utf-8") as f:
    f.write(raw + "\n")
back = json.load(open(out, encoding="utf-8"))
assert back == body, "roundtrip mismatch"
print("wrote", out, len(raw), "bytes; roundtrip ok")
print(json.dumps({h: v["rows"] for h, v in per_site.items()}, indent=1))
