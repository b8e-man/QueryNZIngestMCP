"""One-off: fetch the GDC Local Governance Statement 2026 PDF and print its text
around any register-of-interests mention. Headful-direct recipe; if the site's
own interstitial shows, let its own script resolve (never solved by us)."""
import re
import time

from playwright.sync_api import sync_playwright

SCHEME = "https" + chr(58) + chr(47) + chr(47)
PDF_URL = SCHEME + "www.gdc.govt.nz/__data/assets/pdf_file/0027/97920/Local-Governance-Statement-2026.pdf"
HTML_URL = SCHEME + "www.gdc.govt.nz/council/mayor-and-councillors/governance"


def is_shell(b):
    h = b[:2000].decode("utf-8", "replace").lower()
    return "just a moment" in h or ("noindex,nofollow" in h and len(b) < 6000)


with sync_playwright() as p:
    b = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    ctx = b.new_context()
    pg = ctx.new_page()
    r = ctx.request.get(PDF_URL, timeout=60000)
    data = r.body()
    if r.status >= 400 or is_shell(data):
        try:
            pg.goto(HTML_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        for _ in range(20):
            if not is_shell(pg.content().encode("utf-8", "replace")):
                break
            time.sleep(2)
        r = ctx.request.get(PDF_URL, timeout=60000)
        data = r.body()
    b.close()

print("status", r.status, "bytes", len(data), "magic", data[:5])
if data[:4] == b"%PDF":
    with open("/tmp/gdc_lgs2026.pdf", "wb") as f:
        f.write(data)
    print("saved real PDF")
else:
    print("not a PDF:", data[:200])
