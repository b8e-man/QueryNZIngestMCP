import asyncio, ssl, re, json
import httpx

SSL = ssl.create_default_context()
SSL.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA")

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"

async def get(client, url, ua=BROWSER_UA):
    r = await client.get(url, follow_redirects=True,
                         headers={"User-Agent": ua}, timeout=25)
    return r

async def main():
    async with httpx.AsyncClient(verify=SSL, follow_redirects=True, timeout=25) as c:
        tests = [
            ("regulation sitemap", "https://www.regulation.govt.nz/sitemap.xml", BROWSER_UA),
            ("regulation news", "https://www.regulation.govt.nz/news/", BROWSER_UA),
            ("dia sitemap", "https://www.dia.govt.nz/sitemap.xml", BROWSER_UA),
            ("knowledgeauckland news", "https://knowledgeauckland.org.nz/news/", BROWSER_UA),
            ("maxim article feed", "https://www.maxim.org.nz/feed/?post_type=article", BROWSER_UA),
            ("infra feed retry", "https://infrastructure.org.nz/feed/", BROWSER_UA),
            ("rbnz feeds news", "https://www.rbnz.govt.nz/feeds/news", BROWSER_UA),
            ("familyfirst feed", "https://familyfirst.org.nz/feed/", BROWSER_UA),
            ("budget home", "https://budget.govt.nz/", BROWSER_UA),
            ("disclosure home", "https://disclosure.legislation.govt.nz/", BROWSER_UA),
        ]
        for label, url, ua in tests:
            try:
                r = await get(c, url, ua)
                body = r.text
                print(f"\n===== {label} ({url}) -> {r.status_code} len={len(body)} ct={r.headers.get('content-type','')[:40]}")
                # print sitemap locs / links
                if "sitemap" in label or "news" in label or "feed" in label or "home" in label:
                    if label in ("regulation sitemap","dia sitemap"):
                        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
                        print("   locs:", locs[:40])
                    if label == "dia sitemap":
                        news = [l for l in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
                                if re.search(r"news|media|release", l, re.I)]
                        print("   NEWS-ish locs:", news[:60])
                    if label == "regulation news":
                        links = sorted(set(re.findall(r'href="(/news/[^"]+)"', body)))
                        print("   /news/ links:", links[:40])
                        m = re.findall(r'href="(https?://[^"]*(?:news|media|release)[^"]*)"', body, re.I)
                        print("   other news hrefs:", sorted(set(m))[:40])
                    if label == "knowledgeauckland news":
                        links = sorted(set(re.findall(r'href="([^"]+)"', body)))
                        arts = [l for l in links if re.search(r"news|article|story|blog", l, re.I) and not re.search(r"css|js|png|ico|xml|rss", l, re.I)]
                        print("   article-ish hrefs:", arts[:50])
                    if label == "maxim article feed":
                        items = re.findall(r"<item[ >].*?</item>", body, re.DOTALL)
                        print("   item count:", len(items))
                        for it in items[:5]:
                            m = re.search(r"<link[^>]*>(.*?)</link>", it, re.DOTALL)
                            t = re.search(r"<title[^>]*>(.*?)</title>", it, re.DOTALL)
                            p = re.search(r"<pubDate>(.*?)</pubDate>", it, re.DOTALL)
                            print("    ", (m.group(1) if m else "")[:80], "|", (t.group(1) if t else "")[:60], "|", (p.group(1) if p else ""))
                    if label == "familyfirst feed":
                        items = re.findall(r"<item[ >].*?</item>", body, re.DOTALL)
                        print("   item count:", len(items))
                        for it in items[:5]:
                            m = re.search(r"<link[^>]*>(.*?)</link>", it, re.DOTALL)
                            t = re.search(r"<title[^>]*>(.*?)</title>", it, re.DOTALL)
                            p = re.search(r"<pubDate>(.*?)</pubDate>", it, re.DOTALL)
                            print("    ", (m.group(1) if m else "")[:80], "|", (t.group(1) if t else "")[:60], "|", (p.group(1) if p else ""))
                    if label == "infra feed retry":
                        items = re.findall(r"<item[ >].*?</item>", body, re.DOTALL)
                        print("   item count:", len(items))
                    if label == "rbnz feeds news":
                        items = re.findall(r"<item[ >].*?</item>", body, re.DOTALL)
                        print("   item count:", len(items), "head:", body[:200].replace("\n"," "))
                    if label == "budget home":
                        links = sorted(set(re.findall(r'href="([^"]+)"', body)))
                        news = [l for l in links if re.search(r"news|media|release|speech", l, re.I) and not re.search(r"css|js|png|ico|xml", l, re.I)]
                        print("   news-ish hrefs:", news[:50])
                        print("   all nav hrefs:", [l for l in links if l.startswith("/")][:60])
                    if label == "disclosure home":
                        links = sorted(set(re.findall(r'href="([^"]+)"', body)))
                        print("   hrefs:", links[:80])
            except Exception as e:
                print(f"\n===== {label} ({url}) -> ERR {type(e).__name__}: {e}")
            await asyncio.sleep(2)

asyncio.run(main())
