#!/usr/bin/env python3
"""Discover tribunal decisions from the MoJ forms Solr estate.

Cracked 2026-11-03 (provider Q12): the search UIs under
forms.justice.govt.nz/search/<APP>/ are AngularJS over PUBLIC Solr cores
(forms.justice.govt.nz/forms/publicSolrProxy/solr/<core>/select?wt=json):

  TTV2   Tenancy Tribunal orders       ~33,265
         PDF  /search/Documents/TTV2/PDF/<appId>-Tribunal_Order_Redacted.pdf
  ARLA   ARLA decisions                 ~4,179
         PDF  /search/Documents/ARLA/<id>/ARLA_FULL.pdf
  IPTV2  IPT + legacy RSAA decisions   ~21,041
         PDF  /search/Documents/IPTV2/<folder>/<id>.pdf
         folder by id prefix: ref_ -> RefugeeProtection,
                              rem_ -> Deportation, res_ -> Residence

The full decision text is IN the index (document_text_uploaded / decision)
with citation (decisionName_s / abstractappealno_s) and dates. PDFs serve
from origin without challenge (verified 200). The www.justice.govt.nz
listing pages are CAPTCHA-walled — we never solve challenges; this walks
the site's own public data endpoint instead.

Budget/resume (cron kills ~120s): state moj_solr_state.json {core: start}.
Dedupe against queue.jsonl + done.jsonl. Politeness: 0.8s between pages,
~1s before each PDF family. Rows carry citation/date hints so the tick's
classify() records them (kind=judgment_pdf).
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "moj_solr_state.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SOLR = "https://forms.justice.govt.nz/forms/publicSolrProxy/solr"
SLEEP = 0.8
T0 = time.time()

CIT = re.compile(r"\[(\d{4})\]\s*(NZ[A-Za-z]+)\s+([\d–\-]+)")

CORES = {
    "TTV2": {"court": "tenancy", "sort": "publishedDate_dt desc"},
    "ARLA": {"court": "arla", "sort": "decisionDate_dt desc"},
    "IPTV2": {"court": "ipt", "sort": "decisionDateIndex_l desc"},
}


def over(budget):
    return time.time() - T0 > budget


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    if body[:2] == b"\x1f\x8b":            # proxy sometimes gzips anyway
        import gzip
        body = gzip.decompress(body)
    return body


def load_urls(path):
    urls = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    return urls


def ymd(v):
    """Solr date-ish -> YYYY-MM-DD (year precision when that is all we have)."""
    if not v:
        return ""
    s = str(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(1) + "-" + m.group(2) + "-" + m.group(3)
    m = re.match(r"(\d{8})", s.replace("-", ""))  # decisionDateIndex_l
    if m:
        return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
    m = re.search(r"((?:19|20)\d{2})", s)
    return m.group(1) if m else ""


def pdf_urls(core, doc):
    """-> list of (url, case_name, citation, judgment_date) for one Solr doc."""
    did = str(doc.get("id", ""))
    court = CORES[core]["court"]
    date = ymd(doc.get("decisionDateIndex_l") or doc.get("decisionDate_dt")
               or doc.get("publishedDate_s") or doc.get("decisionDate_s"))
    name = ""
    for k in ("decisionName_s", "decisionShortName_s", "abstractappealno_s",
              "caseTitle_txt", "caseTitle_s"):
        v = doc.get(k)
        if v:
            name = str(v[0] if isinstance(v, list) else v)[:300]
            break
    cit = ""
    m = CIT.search(name)
    if m:
        cit = f"[{m.group(1)}] {m.group(2)} {m.group(3)}"
    out = []
    docs = doc.get("documents") or []
    if core == "TTV2":
        app = did.split("_")[0]
        out.append(f"https://forms.justice.govt.nz/search/Documents/TTV2/PDF/"
                   f"{app}-Tribunal_Order_Redacted.pdf")
    elif core == "ARLA":
        out.append(f"https://forms.justice.govt.nz/search/Documents/ARLA/"
                   f"{did}/ARLA_FULL.pdf")
    elif core == "IPTV2":
        folder = {"ref_": "RefugeeProtection", "rem_": "Deportation",
                  "res_": "Residence"}.get(did[:4])
        if folder and docs:
            out.append(f"https://forms.justice.govt.nz/search/Documents/IPTV2/"
                       f"{folder}/{did}.pdf")
    return [(u, name, cit, date, court) for u in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=100)
    ap.add_argument("--core", default="all")
    args = ap.parse_args()

    state = {}
    if os.path.exists(STATE_F):
        state = json.load(open(STATE_F))
    seen = load_urls(QUEUE_F) | load_urls(DONE_F)
    cores = list(CORES) if args.core == "all" else [args.core]

    for core in cores:
        if over(args.budget):
            break
        start = state.get(core, 0)
        added = 0
        while not over(args.budget):
            q = urllib.parse.urlencode({
                "q": "*:*", "rows": 200, "start": start, "wt": "json",
                "fl": "id,documents,decisionName_s,decisionShortName_s,"
                      "abstractappealno_s,caseTitle_txt,caseTitle_s,"
                      "decisionDateIndex_l,decisionDate_dt,decisionDate_s,"
                      "publishedDate_s,publishedFlag_s",
                "sort": CORES[core]["sort"]})
            try:
                raw = fetch(f"{SOLR}/{core}/select?{q}")
                resp = json.loads(raw)["response"]
            except Exception as e:
                print(f"{core} start={start}: {e}", flush=True)
                break
            docs = resp.get("docs", [])
            if not docs:
                state[core] = 0            # exhausted -> re-walk from head
                break
            with open(QUEUE_F, "a") as f:
                for doc in docs:
                    # publishedFlag_s shapes differ per core: '1', ['1'],
                    # ['true'] (TTV2). Normalize before testing.
                    pf = re.sub(r"[\[\]'\" ]", "",
                                str(doc.get("publishedFlag_s", "1")))
                    if pf.lower() not in ("1", "true", "yes"):
                        continue
                    for u, name, cit, date, court in pdf_urls(core, doc):
                        if u in seen:
                            continue
                        seen.add(u)
                        row = {"url": u, "court": court,
                               "kind": "judgment_pdf", "case_name": name,
                               "citation": cit, "judgment_date": date,
                               "discovered_via": f"mojsolr:{core}"}
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        added += 1
            start += len(docs)
            state[core] = start
            with open(STATE_F, "w") as f:
                json.dump(state, f)
            if start >= resp.get("numFound", 0):
                state[core] = 0
                with open(STATE_F, "w") as f:
                    json.dump(state, f)
                break
            time.sleep(SLEEP)
        print(f"{core}: +{added} queued (at start={state.get(core, 0)})",
              flush=True)


if __name__ == "__main__":
    main()
