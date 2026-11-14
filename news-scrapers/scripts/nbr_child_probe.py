"""Probe one NBR child sitemap: shape of urls inside."""
import httpx
import re

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    for url in ("https://www.nbr.co.nz/sitemap.xml/sitemap/SilverStripe-CMS-Model-SiteTree/1",
                "https://www.nbr.co.nz/sitemap.xml/sitemap/SilverStripe-CMS-Model-SiteTree/112"):
        r = c.get(url)
        body = r.text
        locs = re.findall(r"<loc>([^<]+)</loc>", body)
        lastmods = re.findall(r"<lastmod>([^<]+)</lastmod>", body)
        print(f"== {url} -> {r.status_code} len={len(body)} urls={len(locs)}")
        for u in locs[:6]:
            print("   ", u)
        print("   lastmod sample:", lastmods[:3])

    r = c.get("https://www.nbr.co.nz/rss")
    print("== /rss ->", r.status_code, r.headers.get("content-type", "?"), len(r.text))
    print("   head:", repr(r.text[:400]))

main()
