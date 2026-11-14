"""Newsroom login page: why is #user_login hidden? Map visible vs hidden."""
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        page.goto("https://newsroom.co.nz/wp-login.php", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        # visibility map of form controls
        info = page.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('input, button, form')) {
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                out.push({tag: el.tagName, id: el.id, name: el.name, type: el.type || '',
                          visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none',
                          w: r.width, h: r.height, display: cs.display});
            }
            return out;
        }""")
        for row in info:
            print(row)
        # what is actually visible at top of page? (overlay? custom login UI?)
        vis = page.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll('div, section, a')) {
                const r = el.getBoundingClientRect();
                if (r.width > 150 && r.height > 30 && r.top >= 0 && r.top < 500) {
                    const t = (el.innerText || '').trim().slice(0, 60);
                    if (t) out.push({tag: el.tagName, cls: (el.className || '').toString().slice(0, 40), top: Math.round(r.top), text: t});
                }
            }
            return out.slice(0, 15);
        }""")
        print("--- visible blocks ---")
        for row in vis:
            print(row)
        page.screenshot(path="/opt/data/news-scrapers/ingestion/scripts/newsroom_login.png")
        b.close()

main()
