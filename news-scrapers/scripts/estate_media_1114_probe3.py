import asyncio, ssl, re
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
    return await client.get(url, follow_redirects=True,
                            headers={"User-Agent": ua}, timeout=25)

async def main():
    async with httpx.AsyncClient(verify=SSL, follow_redirects=True, timeout=25) as c:
        tests = [
            ("rbnz article", "https://www.rbnz.govt.nz/news/2026/11/example", BROWSER_UA),
            ("rbnz article 2", "https://www.rbnz.govt.nz/news/2026/10/example", BROWSER_UA),
            ("budget releases", "https://budget.govt.nz/budget/2026/releases/index.htm", BROWSER_UA),
            ("budget speech", "https://budget.govt.nz/budget/2026/speech/index.htm", BROWSER_UA),
            ("dia press releases", "https://www.dia.govt.nz/diawebsite.nsf/wpg_URL/Resource-material-Press-Releases-Index?OpenDocument", BROWSER_UA),
            ("disclosure home2", "https://disclosure.legislation.govt.nz/", BROWSER_UA),
            ("infra retry2", "https://infrastructure.org.nz/feed/", BROWSER_UA),
        ]
        for label, url, ua in tests:
            try:
                r = await get(c, url, ua)
                body = r.text
                print(f"\n===== {label} -> {r.status_code} len={len(body)} final={r.url}")
                if "rbnz article" in label:
                    print("   head:", body[:150].replace("\n"," "))
                    # find links in feed already have; just confirm
                if "budget releases" in label:
                    links = sorted(set(re.findall(r'href="([^"]+\.htm)"', body)))
                    print("   .htm links:", links[:60])
                if "budget speech" in label:
                    links = sorted(set(re.findall(r'href="([^"]+\.htm)"', body)))
                    print("   .htm links:", links[:60])
                if "dia press releases" in label:
                    # find OpenDocument / press release links
                    links = sorted(set(re.findall(r'href="([^"]+)"', body)))
                    pr = [l for l in links if re.search(r"Press-Release|press-release|PressReleases|News", l, re.I)]
                    print("   press-release hrefs:", pr[:60])
                    print("   all hrefs sample:", links[:40])
                if "disclosure home2" in label:
                    # full text search for news/media/about
                    txt = re.sub(r"<[^>]+>", " ", body)
                    txt = re.sub(r"\s+", " ", txt)
                    print("   text head:", txt[:600])
                    print("   'news' in text:", "news" in txt.lower(), "| 'media' in text:", "media" in txt.lower(), "| 'release' in text:", "release" in txt.lower())
                    # look for nav words
                    for w in ["News","Media","About","Latest","Updates","What's new","Publications"]:
                        if w.lower() in txt.lower():
                            print(f"   contains '{w}'")
            except Exception as e:
                print(f"\n===== {label} -> ERR {type(e).__name__}: {e}")
            await asyncio.sleep(2)

asyncio.run(main())
