#!/usr/bin/env python3
"""Resolve the remaining bare-filename diary releases via Beehive's own
ministerial_diary facet search (discovered 2026-11-03 on /minister/<slug> pages).

The live file names differ wildly from the aggregator's source_url names
(e.g. 'Proactive Diary Release - September 2026 (1)_0.pdf' vs 'Hon Casey
Costello - August 2026.pdf'), so name/month URL guessing is hopeless. This:
  1. visits /minister/<slug> (Chromium + IPRoyal, the beehive bodyfetch route)
  2. pulls the ministers:<ID> facet, paginates /search?f[0]=content_type_facet:
     ministerial_diary&f[1]=ministers:<ID> — attribution is implicit per page
  3. matches month+year tokens in PDF link text/filenames to the target names
  4. fetches the PDFs (browser UA passes /sites/default/files/), writes
     manifest ok rows with resolved_from=name
Then re-run diary_pdfs_link.py.
"""
import base64
import hashlib
import json
import os
import random
import re
import string
import time
import urllib.parse
import urllib.request

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(DATA, "diary_pdfs")
MANIFEST = os.path.join(DATA, "diary_pdfs_manifest.jsonl")
PROXY_F = "/opt/data/beehive-scraper/proxy.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MON = ["January", "February", "March", "April", "May", "June", "July",
       "August", "September", "October", "November", "December"]


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get("Content-Type", "")


# ---- targets: unresolved names -> (minister, month, year) -----------------
done, targets = set(), {}
for line in open(MANIFEST):
    m = json.loads(line)
    if m.get("status") == "ok" and m.get("resolved_from"):
        done.add(m["resolved_from"])
for line in open(MANIFEST):
    m = json.loads(line)
    if m.get("status") != "error" or "unknown url type" not in str(m.get("error", "")):
        continue
    name = m["error"].split("'")[1]
    if name in done:
        continue
    parts = name[:-4].split(" - ")
    minister = parts[0]
    toks = re.findall(r"(" + "|".join(MON) + r")\s+(\d{4})", name)
    if toks:
        targets[name] = (minister, toks[-1][0], toks[-1][1])
print(f"targets: {len(targets)}")


def slugify(minister):
    s = minister.lower().replace(".", "")
    s = re.sub(r"\bmp$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ---- chromium pass: minister pages -> facet ids -> search pages -> PDFs ---
cfg = json.load(open(PROXY_F))
sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
proxy = {"server": cfg["server"],
         "username": base64.b64decode(cfg["username_b64"]).decode(),
         "password": base64.b64decode(cfg["password_base_b64"]).decode()
         + f"_country-nz_session-{sess}_lifetime-30m"}

from playwright.sync_api import sync_playwright  # noqa: E402

ministers = {}
for name, (mn, _, _) in targets.items():
    ministers.setdefault(mn, []).append(name)
print(f"ministers: {len(ministers)}")

pdfs_by_minister = {}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, proxy=proxy,
                          args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA)

    def nav(pg, url):
        pg.goto(url, timeout=60000, wait_until="domcontentloaded")
        for _ in range(6):
            pg.wait_for_timeout(4000)
            h = pg.content()
            if "noindex" not in h[:300] and len(h) > 5000:
                return h
        return pg.content()

    for mn in ministers:
        pg = ctx.new_page()
        slug = slugify(mn)
        html = ""
        for cand in (slug, slug + "-mp"):
            try:
                html = nav(pg, f"https://www.beehive.govt.nz/minister/{cand}")
            except Exception:
                continue
            if "noindex" not in html[:300] and len(html) > 5000:
                break
        ids = re.findall(r"ministers%3A(\d+)", html)
        if not ids:
            ids = re.findall(r"ministers:(\d+)", html)
        print(f"{mn}: slug={slug} facet_ids={sorted(set(ids))}")
        if not ids:
            pg.close()
            continue
        fid = sorted(set(ids))[0]
        found = []
        for page in range(0, 8):
            u = ("https://www.beehive.govt.nz/search?f%5B0%5D=content_type_facet%3Aministerial_diary"
                 f"&f%5B1%5D=ministers%3A{fid}&f%5B2%5D=government_facet%3A6700&page={page}")
            try:
                h = nav(pg, u)
            except Exception:
                break
            hits = re.findall(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', h, re.S)
            if not hits:
                break
            for href, text in hits:
                text = re.sub(r"<[^>]+>", " ", text)
                text = urllib.parse.unquote(text + " " + urllib.parse.unquote(href))
                found.append((href, text))
        print(f"  pdf links: {len(found)}")
        pdfs_by_minister[mn] = found
        pg.close()
    b.close()

# ---- match + fetch --------------------------------------------------------
os.makedirs(OUT_DIR, exist_ok=True)
res = {"resolved": 0, "unresolved": [], "errors": []}
for name, (mn, mon, yr) in targets.items():
    hit = None
    fallback = None
    for href, text in pdfs_by_minister.get(mn, []):
        t = text.lower()
        base_name = urllib.parse.unquote(href.split("/")[-1].split("?")[0]).lower()
        if base_name == name.lower():
            hit = href
            break
        if fallback is None and mon.lower() in t and yr in t:
            fallback = href
    hit = hit or fallback
    if hit and not hit.startswith("http"):
        hit = "https://www.beehive.govt.nz" + hit
    if not hit:
        res["unresolved"].append(name)
        continue
    try:
        body, ctype = fetch(hit)
        if b"%PDF" not in body[:1024]:
            res["errors"].append(f"{name} <- {hit}")
            continue
    except Exception as e:
        res["errors"].append(f"{name} <- {hit}: {e}")
        continue
    fn = safe_name(name)
    path = os.path.join(OUT_DIR, fn)
    if os.path.exists(path):
        root, ext = os.path.splitext(fn)
        path = os.path.join(OUT_DIR, f"{root}_{hashlib.sha256(body).hexdigest()[:8]}{ext}")
        fn = os.path.basename(path)
    with open(path, "wb") as f:
        f.write(body)
    with open(MANIFEST, "a") as f:
        f.write(json.dumps({"url": hit, "status": "ok",
                            "path": f"diary_pdfs/{fn}", "resolved_from": name,
                            "bytes": len(body), "content_type": ctype,
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    res["resolved"] += 1
    time.sleep(0.4)

print(f"resolved: {res['resolved']}  unresolved: {len(res['unresolved'])}  "
      f"errors: {len(res['errors'])}")
for x in res["unresolved"]:
    print("  unresolved:", x)
for x in res["errors"][:10]:
    print("  error:", x)
