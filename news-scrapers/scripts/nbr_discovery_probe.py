"""NBR discovery diagnosis: what does sitemap.xml actually return now?"""
import httpx
import re

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    for url in ("https://www.nbr.co.nz/sitemap.xml",
                "https://www.nbr.co.nz/robots.txt",
                "https://www.nbr.co.nz/sitemap_index.xml",
                "https://nbr.co.nz/sitemap.xml"):
        try:
            r = c.get(url)
            body = r.text
            print(f"== {url} -> {r.status_code} {r.headers.get('content-type','?')} len={len(body)}")
            print("   head:", repr(body[:300]))
            if "sitemap" in url and "robots" not in url:
                locs = re.findall(r"<loc>([^<]+)</loc>", body)
                print("   <loc> count:", len(locs), "first 5:", locs[:5])
        except Exception as e:
            print(f"== {url} ERR {type(e).__name__}: {e}")

    # what does the live homepage offer for discovery? (rss/atom links, json feeds)
    try:
        r = c.get("https://www.nbr.co.nz/")
        html = r.text
        print("== homepage:", r.status_code, len(html))
        for m in re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*>', html)[:6]:
            print("   feed link:", m[:160])
        for m in re.findall(r'href="([^"]*(?:feed|rss|atom)[^"]*)"', html)[:10]:
            print("   feed-ish href:", m[:120])
    except Exception as e:
        print("homepage ERR", e)

main()
