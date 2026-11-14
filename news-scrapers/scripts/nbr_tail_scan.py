"""NBR: which children hold URLs with recent lastmod? Tail scan + child-1 check."""
import time
import httpx
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
CUTOFF = "2026-11-08"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    probes = [112, 111, 110, 109, 108, 1]
    for n in probes:
        url = f"https://www.nbr.co.nz/sitemap.xml/sitemap/SilverStripe-CMS-Model-SiteTree/{n}"
        body = c.get(url).text
        root = ET.fromstring(body.encode())
        fresh, newest = [], ("", "")
        total = 0
        for u in root.iter(SM + "url"):
            total += 1
            lm = (u.findtext(SM + "lastmod") or "").strip()
            loc = (u.findtext(SM + "loc") or "").strip()
            if lm > newest[0]:
                newest = (lm, loc)
            if lm >= CUTOFF:
                fresh.append((lm, loc))
        print(f"child {n}: urls={total} fresh(>= {CUTOFF})={len(fresh)} newest={newest[0]} {newest[1][:70]}")
        for lm, loc in fresh[:4]:
            print("   ", lm, loc[:80])
        time.sleep(10)  # robots.txt Crawl-Delay: 10

main()
