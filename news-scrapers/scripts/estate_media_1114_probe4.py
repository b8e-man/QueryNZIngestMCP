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

async def get(client, url):
    return await client.get(url, follow_redirects=True,
                            headers={"User-Agent": BROWSER_UA}, timeout=25)

async def main():
    async with httpx.AsyncClient(verify=SSL, follow_redirects=True, timeout=25) as c:
        tests = [
            ("budget releases body", "https://budget.govt.nz/budget/2026/releases/index.htm"),
            ("dia latest updates", "https://www.dia.govt.nz/Latest-updates"),
            ("dia digital safety PR", "https://www.dia.govt.nz/digital-safety-press-releases"),
            ("dia AML news", "https://www.dia.govt.nz/AML-CFT-News"),
        ]
        for label, url in tests:
            try:
                r = await get(c, url)
                body = r.text
                print(f"\n===== {label} -> {r.status_code} len={len(body)} final={r.url}")
                if label == "budget releases body":
                    # find the list of releases: look for links near 'release' or list items
                    # strip nav; print all hrefs not in the nav set
                    allh = re.findall(r'href="([^"]+)"', body)
                    nav = set(re.findall(r'href="(\.\./\.\./\.\./[^"]+)"', body))
                    content_links = [h for h in allh if h not in nav and not h.startswith("#")]
                    print("   non-nav hrefs:", sorted(set(content_links))[:80])
                if "dia" in label:
                    allh = re.findall(r'href="([^"]+)"', body)
                    # release item links
                    items = [h for h in allh if re.search(r"Press-Release|press-release|News|release|Updates|update", h, re.I)]
                    print("   item-ish hrefs:", sorted(set(items))[:80])
                    # also list OpenDocument links
                    od = [h for h in allh if "OpenDocument" in h]
                    print("   OpenDocument hrefs:", sorted(set(od))[:80])
            except Exception as e:
                print(f"\n===== {label} -> ERR {type(e).__name__}: {e}")
            await asyncio.sleep(2)

asyncio.run(main())
