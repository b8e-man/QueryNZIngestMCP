#!/usr/bin/env python3
"""Discovery pass for the estate-media 12 sites: list pagination + article
link structure per reachable host. Read-only; prints; no landing."""
import re, time, urllib.request, urllib.parse

UA = "QueryNZ-EstateCollector/1.0 (research capture; polite; contact: arthur@betelgeuse.co.nz)"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read(), r.geturl()

def links(d, fin):
    out = set()
    for m in re.finditer(rb'href=["\']([^"\']+)["\']', d, re.I):
        u = urllib.parse.urljoin(fin, m.group(1).decode("utf-8", "ignore")).split("#")[0]
        out.add(u)
    return out

def path(u):
    return urllib.parse.urlsplit(u).path

def net(u):
    return urllib.parse.urlsplit(u).netloc.replace("www.", "")

SITES = [
    ("regulation", "http://regulation.govt.nz/news", None),
    ("dia", "http://dia.govt.nz/Latest-updates", None),
    ("budget", "http://budget.govt.nz/", None),
    ("ot", "http://orangatamariki.govt.nz/about-us/news", None),
    ("knowledge", "http://knowledgeauckland.org.nz/news", None),
    ("maxim", "http://maxim.org.nz/category/blog/", None),
    ("maxim-research", "http://maxim.org.nz/category/research/", None),
]

for name, u, _ in SITES:
    try:
        st, d, fin = get(u)
        host = net(fin)
        ls = links(d, fin)
        same = [x for x in ls if net(x) == host]
        txt = d.decode("utf-8", "ignore")
        print(f"==== {name} {u} -> {st} final={fin} ({len(d)}b, {len(same)} same-host links)")
        # pagination clues
        for pat in [r"page=\d", r"/page/\d", r"paged=\d", r"rel=.?next", r">Next<", r">Older", r">Newer"]:
            c = len(re.findall(pat, txt, re.I))
            if c:
                print(f"    pagination clue {pat!r} x{c}")
        # classify same-host links
        arts, lists, other = [], [], []
        for x in sorted(same):
            p = path(x)
            if re.search(r"(news|article|story|stories|media-release|releases|update|updates|speech|publication|information-release|blog|category|latest)", p, re.I):
                arts.append(x)
            elif re.search(r"(page=\d|/page/\d|paged=\d)", x, re.I):
                lists.append(x)
        print(f"    article-ish {len(arts)}")
        for a in arts[:30]:
            print("      ", a)
        if lists:
            print(f"    pagination-like {len(lists)}")
            for l in lists[:20]:
                print("      ", l)
    except Exception as e:
        print(f"==== {name} {u} ERR {type(e).__name__} {str(e)[:100]}")
    time.sleep(2)
