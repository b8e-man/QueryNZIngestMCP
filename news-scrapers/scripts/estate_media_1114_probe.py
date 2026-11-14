import asyncio, ssl, sys, json
import httpx

SSL = ssl.create_default_context()
SSL.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA")

UA = "QueryNZ/1.0 (research aggregator; contact: admin@followthemoney.nz)"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HOSTS = [
    "regulation.govt.nz",
    "disclosure.legislation.govt.nz",
    "maxim.org.nz",
    "infrastructure.org.nz",
    "dia.govt.nz",
    "budget.govt.nz",
    "acc.co.nz",
    "orangatamariki.govt.nz",
    "rbnz.govt.nz",
    "familyfirst.org.nz",
    "greystar.co.nz",
    "knowledgeauckland.org.nz",
]

async def probe(client, url, label):
    try:
        r = await client.get(url, follow_redirects=True,
                             headers={"User-Agent": BROWSER_UA}, timeout=25)
        body = r.text[:400].replace("\n", " ")[:400]
        return {"label": label, "url": str(r.url), "status": r.status_code,
                "ct": r.headers.get("content-type", ""), "len": len(r.content),
                "head": body}
    except Exception as e:
        return {"label": label, "url": url, "status": "ERR",
                "ct": "", "len": 0, "head": f"{type(e).__name__}: {e}"}

async def main():
    async with httpx.AsyncClient(verify=SSL, follow_redirects=True, timeout=25) as c:
        for h in HOSTS:
            print(f"\n===== {h} =====")
            for scheme in ("https://www.", "https://"):
                base = scheme + h
                for path in ("/robots.txt", "/sitemap.xml", "/"):
                    url = base + path
                    res = await probe(c, url, f"{h}{path}")
                    print(f"  {res['label']:45s} -> {res['status']} {res['ct'][:30]} len={res['len']} | {res['head'][:120]}")
                await asyncio.sleep(1.5)
            # common news endpoints (www only)
            base = "https://www." + h
            for path in ("/feed/", "/news/", "/media-releases/", "/media/", "/news-and-media/"):
                res = await probe(c, base + path, f"{h}{path}")
                print(f"  {res['label']:45s} -> {res['status']} {res['ct'][:30]} len={res['len']} | {res['head'][:100]}")
                await asyncio.sleep(1.2)

asyncio.run(main())
