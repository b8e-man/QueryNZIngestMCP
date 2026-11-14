"""NBR /rss page: what per-category feeds does it list? (discover_rss's source)"""
import httpx
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    html = c.get("https://www.nbr.co.nz/rss/").text
    soup = BeautifulSoup(html, "html.parser")
    links = [a.get("href", "").strip() for a in soup.select("div.styled-content ul li a")]
    print("styled-content feed links:", len(links))
    for u in links[:20]:
        print("  ", u)
    if not links:
        # broader: any rss/xml-ish href on the page
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if any(t in h.lower() for t in ("rss", "feed", ".xml")):
                print("  candidate:", h[:100], "|", a.get_text(strip=True)[:40])
    # fetch two feeds to see freshness + shape
    for u in links[:2]:
        r = c.get(u)
        print(f"== {u} -> {r.status_code} {r.headers.get('content-type','?')} len={len(r.text)}")
        print("   head:", repr(r.text[:300]))

main()
