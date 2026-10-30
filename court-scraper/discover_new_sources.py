#!/usr/bin/env python3
"""Seed queue.jsonl from court/tribunal sources outside the courtsofnz + JDO lanes.

  ERA   determinations.era.govt.nz (NZERA)
        history: Wayback CDX prefix  assets/elawpdf/
        fresh:   GET /determinations/recent?start=N   (rows link
                 /assets/elawpdf/<year>/<year>-NZERA-<n>.pdf)
  HRRT  justice.govt.nz (NZHRRT)
        GET /tribunals/human-rights/hrrt-decisions/?Filter_Jurisdiction=27&start=N
        rows link /assets/Documents/Decisions/YYYY-NZHRRT-*.pdf
  HPDT  hpdt.org.nz (NZHPDT) — DNN/XModPro WebForms
        POST /Search-Decisions per year (VIEWSTATE dance) -> Charge-Details?file=...
        detail pages carry the decision filename in <a class="DecF1"> (JS builds
        /portals/0/<file>); we parse the name and queue the PDF + detail page
  WT    waitangitribunal.govt.nz (Wai reports)
        GET /en/publications/tribunal-reports/by-year and /by-wai-number
        rows link forms.justice.govt.nz/search/Documents/WT/wt_DOC_*/....pdf
        (kind=report — Tribunal reports, not judgments)

Politeness: ~1.2s between fetches; UA carries the corpus contact. Idempotent:
dedupe against queue.jsonl + done.jsonl. Robots: ERA /assets/elawpdf/ and HPDT
/portals/ are not disallowed; WT explicitly Allows /assets/*.pdf; justice.govt.nz
/assets/ follows the standing politely-anyway ruling.

Budget/resume: the cron no_agent hard-kills at 120s, so every walk stops at
--budget seconds (default 100) and HPDT remembers its completed years in
new_sources_state.json — re-runs continue where they stopped.

Usage: discover_new_sources.py [--source era|hrrt|hpdt|wt|all] [--budget S]
"""

import argparse
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "new_sources_state.json")
CDX = "https://web.archive.org/cdx/search/cdx"
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SLEEP = 1.2
MAX_TRIES = 3

T0 = time.time()
BUDGET_S = 100


def over():
    return time.time() - T0 > BUDGET_S


def fetch(url, data=None, timeout=45):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


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


def load_state():
    try:
        with open(STATE_F) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_F, "w") as f:
        json.dump(state, f)


class Queue:
    def __init__(self):
        self.known = load_urls(QUEUE_F) | load_urls(DONE_F)
        self.added = 0
        self.rows = []

    def add(self, url, kind=None, court=None):
        if url in self.known:
            return False
        self.known.add(url)
        row = {"url": url}
        if kind:
            row["kind"] = kind
        if court:
            row["court"] = court
        self.rows.append(row)
        self.added += 1
        return True

    def flush(self):
        if not self.rows:
            return
        with open(QUEUE_F, "a") as f:
            for row in self.rows:
                f.write(json.dumps(row) + "\n")
        self.rows = []


# ---------------------------------------------------------------- ERA
def era_cdx(q):
    """Historical ERA determination PDFs from Wayback CDX."""
    prefix = "determinations.era.govt.nz/assets/elawpdf/"
    for attempt in range(1, MAX_TRIES + 1):
        try:
            qs = urllib.parse.urlencode({
                "url": prefix, "matchType": "prefix", "output": "json",
                "fl": "original", "collapse": "urlkey",
                "filter": "statuscode:200", "limit": "100000"})
            rows = json.loads(fetch(f"{CDX}?{qs}", timeout=120))
            break
        except Exception as e:
            print(f"era cdx attempt {attempt}: {e}", flush=True)
            time.sleep(5 * attempt)
    else:
        return 0
    n = 0
    for row in rows[1:]:
        u = row[0]
        if u.lower().endswith(".pdf"):
            n += q.add(u, court="era")
    print(f"era cdx: {len(rows) - 1} rows, {n} new", flush=True)
    return n


def era_recent(q):
    """Fresh ERA determinations via the recent listing (start=N, 10/page)."""
    n = 0
    start = 0
    while start < 400 and not over():   # 4,000 recent is far beyond any gap
        url = ("https://determinations.era.govt.nz/determinations/recent"
               f"?start={start}")
        try:
            body = fetch(url)
        except Exception as e:
            print(f"era recent start={start}: {e}", flush=True)
            break
        found = re.findall(r'href="(/assets/elawpdf/[^"]+\.pdf)"', body)
        if not found:
            break
        for path in found:
            n += q.add("https://determinations.era.govt.nz" + path, court="era")
        time.sleep(SLEEP)
        start += 10
    print(f"era recent: walked to start={start}, {n} new", flush=True)
    return n


# ---------------------------------------------------------------- HRRT
def hrrt_walk(q):
    """HRRT decisions listing (justice.govt.nz decisions finder)."""
    n = 0
    start = 0
    while start < 2000 and not over():
        url = ("https://www.justice.govt.nz/tribunals/human-rights/"
               f"hrrt-decisions/?Filter_Jurisdiction=27&start={start}")
        try:
            body = fetch(url)
        except Exception as e:
            print(f"hrrt start={start}: {e}", flush=True)
            break
        found = set(re.findall(
            r'href="(https://www\.justice\.govt\.nz/assets/Documents/Decisions/'
            r'[^"]+\.pdf)"', body))
        if not found:
            break
        for u in found:
            n += q.add(u, court="hrrt")
        time.sleep(SLEEP)
        start += 25
    print(f"hrrt: walked to start={start}, {n} new", flush=True)
    return n


# ---------------------------------------------------------------- HPDT
HPDT_FIELDS = "dnn$ctr508$XModPro$ctl00$ctl00$ctl00$%s"


def _hpdt_state(body):
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
                 "__EVENTTARGET", "__EVENTARGUMENT"):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % name, body)
        fields[name] = html.unescape(m.group(1)) if m else ""
    return fields


def hpdt_cdx(q):
    """HPDT historical PDFs + detail pages from Wayback CDX. Complements the
    live year search (which paginates unreliably — see report)."""
    n = 0
    for prefix, kind in (("hpdt.org.nz/portals/0/", None),
                         ("hpdt.org.nz/Charge-Details", "case_page"),
                         ("hpdt.org.nz/ChargeDetails", "case_page")):
        if over():
            break
        for attempt in range(1, MAX_TRIES + 1):
            try:
                qs = urllib.parse.urlencode({
                    "url": prefix, "matchType": "prefix", "output": "json",
                    "fl": "original", "collapse": "urlkey",
                    "filter": "statuscode:200", "limit": "100000"})
                rows = json.loads(fetch(f"{CDX}?{qs}", timeout=120))
                break
            except Exception as e:
                print(f"hpdt cdx {prefix} attempt {attempt}: {e}", flush=True)
                time.sleep(5 * attempt)
        else:
            continue
        for row in rows[1:]:
            u = row[0]
            if kind == "case_page" or u.lower().endswith(".pdf"):
                n += q.add(u, kind=kind, court="hpdt")
        print(f"hpdt cdx {prefix}: {len(rows) - 1} rows, {n} new", flush=True)
    return n


def hpdt_walk(q):
    """HPDT decisions: year-filtered WebForms search -> detail pages -> PDFs.
    Results paginate via __doPostBack(...$lnkNext); a year is marked done only
    after all its pages are processed."""
    state = load_state()
    done_years = set(state.get("hpdt_years_done", []))
    try:
        home = fetch("https://www.hpdt.org.nz/Search-Decisions")
    except Exception as e:
        print(f"hpdt: search page failed: {e}", flush=True)
        return 0
    years = re.findall(r'<option value="(\d{4})"', home)
    if not years:
        print("hpdt: no year options found", flush=True)
        return 0
    n = 0
    for year in sorted(set(years)):
        if over():
            break
        if year in done_years:
            continue
        fields = _hpdt_state(home)
        fields[HPDT_FIELDS % "Year"] = year
        fields[HPDT_FIELDS % "CYear"] = ""
        fields[HPDT_FIELDS % "txtSearch"] = ""
        fields[HPDT_FIELDS % "btnSearch"] = "Search"
        try:
            body = fetch("https://www.hpdt.org.nz/Search-Decisions",
                         data=urllib.parse.urlencode(fields).encode())
        except Exception as e:
            print(f"hpdt {year}: {e}", flush=True)
            continue
        year_done = True
        seen_pages = set()
        rows = 0
        while True:
            new_this_page = 0
            links = set(re.findall(
                r"""href=['"]([^'"]*Charge-?Details\?file=[^'"]*)['"]""", body))
            for path in sorted(links):
                if over():
                    year_done = False
                    break
                page_url = urllib.parse.urljoin("https://www.hpdt.org.nz/", path)
                if page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                rows += 1
                new_this_page += 1
                n += q.add(page_url, kind="case_page", court="hpdt")
                try:
                    det = fetch(page_url)
                except Exception as e:
                    print(f"hpdt detail {path[:40]}: {e}", flush=True)
                    continue
                for fname in set(re.findall(
                        r'''class=['"](?:DecF\d*|AOF\d*)['"][^>]*>([^<]+\.pdf)''',
                        det)):
                    fname = html.unescape(fname).strip()
                    n += q.add("https://www.hpdt.org.nz/portals/0/" + fname,
                               court="hpdt")
                time.sleep(SLEEP)
            if not year_done:
                break
            if new_this_page == 0:
                break        # page repeated or empty: end of year
            m = re.search(r"__doPostBack\((?:'|&#39;)([^'&]*\$lnkNext)(?:'|&#39;)",
                          body)
            if not m:
                break
            fields2 = _hpdt_state(body)
            fields2.update({k: v for k, v in fields.items()
                            if not k.startswith("__")})
            fields2["__EVENTTARGET"] = html.unescape(m.group(1))
            fields2["__EVENTARGUMENT"] = ""
            try:
                body = fetch("https://www.hpdt.org.nz/Search-Decisions",
                             data=urllib.parse.urlencode(fields2).encode())
            except Exception as e:
                print(f"hpdt {year} page: {e}", flush=True)
                year_done = False
                break
            time.sleep(SLEEP)
        if year_done:
            done_years.add(year)
            state["hpdt_years_done"] = sorted(done_years)
            save_state(state)
        q.flush()
        print(f"hpdt {year}: {rows} details, {n} new total", flush=True)
        time.sleep(SLEEP)
    print(f"hpdt: {n} new", flush=True)
    return n


def cor_walk(q):
    """Coroners findings of public interest (the official public listing).
    The full findings corpus is NOT publicly indexed on the site - see the
    coverage note in the report; host-wide CDX lives in discover_tribunals."""
    n = 0
    url = ("https://coronerscourt.govt.nz/findings-and-recommendations/"
           "findings-of-public-interest/")
    try:
        body = fetch(url)
    except Exception as e:
        print(f"cor: {e}", flush=True)
        return 0
    found = set(re.findall(
        r'''href=['"]((?:https://coronerscourt\.govt\.nz)?/assets/[^'"]+\.pdf)['"]''',
        body))
    for u in found:
        n += q.add(urllib.parse.urljoin("https://coronerscourt.govt.nz/", u),
                   court="coroners")
    print(f"cor: {len(found)} rows, {n} new", flush=True)
    return n


def wt_walk(q):
    """Waitangi Tribunal reports (by-year + by-wai-number indexes)."""
    n = 0
    for view in ("by-year", "by-wai-number"):
        if over():
            break
        url = ("https://www.waitangitribunal.govt.nz/en/publications/"
               f"tribunal-reports/{view}")
        try:
            body = fetch(url)
        except Exception as e:
            print(f"wt {view}: {e}", flush=True)
            continue
        found = set(re.findall(
            r'href="(https://forms\.justice\.govt\.nz/search/Documents/WT/'
            r'[^"]+\.pdf)"', body))
        for u in found:
            n += q.add(u, kind="report", court="waitangi")
        print(f"wt {view}: {len(found)} rows, {n} new", flush=True)
        time.sleep(SLEEP)
    return n


def main():
    global BUDGET_S
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="all",
                    choices=["era", "hrrt", "hpdt", "wt", "cor", "all"])
    ap.add_argument("--budget", type=int, default=BUDGET_S)
    args = ap.parse_args()
    BUDGET_S = args.budget
    q = Queue()
    want = ({"era", "hrrt", "hpdt", "wt", "cor"} if args.source == "all"
            else {args.source})
    if "era" in want:
        era_cdx(q)
        q.flush()
        era_recent(q)
        q.flush()
    if "hrrt" in want:
        hrrt_walk(q)
        q.flush()
    if "hpdt" in want:
        hpdt_cdx(q)
        q.flush()
        hpdt_walk(q)
        q.flush()
    if "wt" in want:
        wt_walk(q)
        q.flush()
    if "cor" in want:
        cor_walk(q)
        q.flush()
    print(f"new-sources discovery done: {q.added} new queued", flush=True)


if __name__ == "__main__":
    main()
