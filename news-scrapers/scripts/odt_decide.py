"""Decisive ODT check: use saved session, open a real article, decode Piano token claims (claims only, no values)."""
import base64
import json
import re
from playwright.sync_api import sync_playwright

STATE = "/opt/data/evs-credentials/odt_state.json"

def decode_jwt_claims(tok):
    try:
        parts = tok.split(".")
        if len(parts) < 2:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(parts[1] + pad)
        claims = json.loads(raw)
        # keep only non-identifying claims
        keep = {k: claims.get(k) for k in ("exp", "iat", "iss", "aud", "sub_type", "subscription", "access", "role", "type") if k in claims}
        keep["all_claim_keys"] = sorted(claims.keys())
        return keep
    except Exception as e:
        return {"decode_error": type(e).__name__}

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=STATE, user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        page = ctx.new_page()

        # decode the piano tokens from stored cookies (claims only)
        state = json.load(open(STATE))
        for c in state.get("cookies", []):
            if c["name"] in ("__utp", "DPsLYze0pa__ut", "__pid", "__pat", "__tac"):
                val = c.get("value", "")
                info = decode_jwt_claims(val) if val.count(".") >= 2 else None
                print(f"TOKEN {c['name']}: jwt={bool(info)} claims={info}")

        page.goto("https://www.odt.co.nz/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
        arts = [h for h in dict.fromkeys(links) if re.search(r"odt\.co\.nz/(star|news|business|opinion|sport|lifestyle)/.+\d{4}", h)]
        print("article links found:", len(arts), arts[:3])
        if not arts:
            arts = [h for h in dict.fromkeys(links) if "odt.co.nz" in h and h.count("/") >= 5 and not any(x in h for x in ("login", "search", "topic", "author", "latest"))][:5]
            print("fallback links:", arts[:3])
        if arts:
            page.goto(arts[0], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            txt = page.eval_on_selector("body", "e => e.innerText")
            print("ARTICLE TITLE LINE:", repr(txt[:150]))
            print("BODY LEN:", len(txt))
            print("BODY SNIPPET:", repr(txt[300:800]))
            html = page.content().lower()
            for marker in ["sign in to continue", "subscribe now", "this article is for subscribers", "paywall", "already a subscriber", "log in"]:
                print(f"marker[{marker}]:", html.count(marker))
        b.close()

main()
