"""NBR index forensics: per-child lastmod — where do the fresh articles live?"""
import httpx
import re
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    root = ET.fromstring(c.get("https://www.nbr.co.nz/sitemap.xml").text.encode())
    rows = []
    for sm in root.iter(SM + "sitemap"):
        loc = (sm.findtext(SM + "loc") or "").strip()
        lastmod = (sm.findtext(SM + "lastmod") or "").strip()
        rows.append((lastmod, loc))
    rows.sort(reverse=True)
    print("children:", len(rows))
    for lastmod, loc in rows[:12]:
        print(" ", lastmod, loc)
    print("oldest 3:")
    for lastmod, loc in rows[-3:]:
        print(" ", lastmod, loc)

    # verify the top-3 freshest children actually contain fresh ARTICLES
    for lastmod, loc in rows[:3]:
        body = c.get(loc).text
        root2 = ET.fromstring(body.encode())
        arts = []
        for u in root2.iter(SM + "url"):
            url = (u.findtext(SM + "loc") or "").strip()
            lm = (u.findtext(SM + "lastmod") or "").strip()
            if lm >= "2026-11-08":
                arts.append((lm, url))
        print(f"== {loc.split('/')[-1]} lastmod={lastmod} fresh_urls={len(arts)}")
        for lm, url in arts[:5]:
            print("   ", lm, url)

main()
