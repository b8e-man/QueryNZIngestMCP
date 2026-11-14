"""Newsroom sitemap shape: index children + per-URL lastmod present?"""
import httpx
import re
import xml.etree.ElementTree as ET

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    idx = c.get("https://newsroom.co.nz/sitemap.xml").text
    root = ET.fromstring(idx.encode())
    children = [(loc.text or "").strip() for loc in root.iter(SM + "loc") if loc.text]
    print("children:", len(children))
    for ch in children:
        print("  ", ch)

    # probe the newest child for lastmod coverage
    if children:
        body = c.get(children[-1]).text
        root2 = ET.fromstring(body.encode())
        rows = []
        for u in root2.iter(SM + "url"):
            loc = (u.findtext(SM + "loc") or "").strip()
            lm = (u.findtext(SM + "lastmod") or "").strip()
            rows.append((lm, loc))
        print(f"== last child: {len(rows)} urls")
        for lm, loc in rows[:5]:
            print("  ", lm, loc[:80])
        fresh = [r for r in rows if r[0] >= "2026-10-17"]
        print("urls with lastmod >= 2026-10-17:", len(fresh))
        for lm, loc in fresh[:5]:
            print("  ", lm, loc[:80])

main()
