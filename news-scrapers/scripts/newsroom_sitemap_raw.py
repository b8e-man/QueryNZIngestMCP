"""What does newsroom.co.nz/sitemap.xml actually return?"""
import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def main():
    c = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": UA})
    r = c.get("https://newsroom.co.nz/sitemap.xml")
    print("status:", r.status_code, "| ctype:", r.headers.get("content-type"), "| len:", len(r.text))
    print("head 400:", repr(r.text[:400]))
    # robots.txt sitemap declaration
    rr = c.get("https://newsroom.co.nz/robots.txt")
    print("robots:", repr(rr.text[:400]))

main()
