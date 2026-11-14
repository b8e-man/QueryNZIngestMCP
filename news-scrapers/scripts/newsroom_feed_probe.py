"""Newsroom robots.txt content signals (full) + RSS feed paging probe."""
import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    print("=== robots.txt (full) ===")
    print(c.get("https://newsroom.co.nz/robots.txt").text)

    print("=== feed paging ===")
    for url in ("https://newsroom.co.nz/feed/",
                "https://newsroom.co.nz/feed/?paged=2",
                "https://newsroom.co.nz/feed/?paged=5"):
        r = c.get(url)
        import re
        items = re.findall(r"<item>", r.text)
        dates = re.findall(r"<pubDate>([^<]+)</pubDate>", r.text)
        links = re.findall(r"<link>([^<]+)</link>", r.text)
        print(f"{url} -> {r.status_code} items={len(items)}")
        if dates:
            print("   newest:", dates[0], "| oldest:", dates[-1])
        if len(links) > 1:
            print("   last link:", links[-1][:80])

main()
