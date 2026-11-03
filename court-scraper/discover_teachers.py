#!/usr/bin/env python3
"""Discover Teachers Disciplinary Tribunal decisions (NZTDT).

Source (verified 2026-11-03): the tribunal's own site
teachersdisciplinarytribunal.nz. The decision PDFs are linked from the
blog list / RSS of the decision library:

  HTML  /disciplinary-tribunal-decision-library?page=N   (caps at 20 pages)
  RSS   /disciplinary-tribunal-decision-library?page=N&format=rss  (full)
        item <link> = the PDF URL (Cloudinary); <description> carries
        "Decision Date: DD/MM/YYYY"; <title> = case name.

Detail pages carry metadata only (no PDF), so the RSS walk is the
enumerator. Squarespace ?format=json routes are robots-disallowed —
the RSS feed is used instead (published for syndication).

Budget/resume: state teachers_state.json {page: n}.
"""
import argparse, datetime, json, os, re, time, urllib.request

BASE = "/opt/data/court-scraper"
QUEUE_F = os.path.join(BASE, "queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "teachers_state.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SLEEP = 1.0
T0 = time.time()
ITEM = re.compile(r"<item>(.*?)</item>", re.S)
TAG = lambda t: re.compile(rf"<{t}[^>]*>(.*?)</{t}>", re.S)
CIT = re.compile(r"NZTDT[_\s-]+(\d{4})[_\s-]+(\d{1,3})", re.I)
DDATE = re.compile(r"Decision Date:\s*(\d{2}/\d{2}/\d{4})")


def over(budget):
    return time.time() - T0 > budget


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=100)
    args = ap.parse_args()
    state = {}
    if os.path.exists(STATE_F):
        state = json.load(open(STATE_F))
    page = state.get("page", 1)

    seen = set()
    for path in (QUEUE_F, DONE_F):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    try:
                        seen.add(json.loads(line)["url"])
                    except Exception:
                        pass

    added = 0
    empty = 0
    while not over(args.budget) and empty < 2:
        url = ("https://www.teachersdisciplinarytribunal.nz/"
               f"disciplinary-tribunal-decision-library?page={page}&format=rss")
        try:
            body = fetch(url)
        except Exception as e:
            print(f"rss page {page}: {e}", flush=True)
            break
        items = ITEM.findall(body)
        new = 0
        with open(QUEUE_F, "a") as f:
            for it in items:
                link_m = TAG("link").search(it)
                title_m = TAG("title").search(it)
                if not link_m:
                    continue
                link = link_m.group(1).strip()
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
                dd = DDATE.search(it)
                ddate = ""
                if dd:
                    d, m, y = dd.group(1).split("/")
                    ddate = f"{y}-{m}-{d}"
                cit = ""
                mc = CIT.search(urllib.request.unquote(link + " " + title))
                if mc:
                    cit = f"[{mc.group(1)}] NZTDT {int(mc.group(2))}"
                if link in seen:
                    continue
                seen.add(link)
                is_pdf = link.lower().split("?")[0].endswith(".pdf")
                f.write(json.dumps({
                    "url": link,
                    "court": "teachers",
                    "kind": "judgment_pdf" if is_pdf else "case_page",
                    "case_name": title[:300], "citation": cit,
                    "judgment_date": ddate,
                    "discovered_via": "teachers-rss"},
                    ensure_ascii=False) + "\n")
                new += 1
        added += new
        empty = empty + 1 if not items else 0
        page += 1
        state["page"] = page
        with open(STATE_F, "w") as f:
            json.dump(state, f)
        time.sleep(SLEEP)
    print(f"teachers: at page={page} +{added} queued", flush=True)


if __name__ == "__main__":
    main()
