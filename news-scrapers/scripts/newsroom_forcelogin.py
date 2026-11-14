"""Newsroom: force-fill the hidden classic wp-login form via JS, submit, verify cookie."""
import os
from playwright.sync_api import sync_playwright

def load_env(path):
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    env = load_env("/opt/data/evs-credentials/newsscrapers.env")
    em = env.get("NEWSROOM_EMAIL")
    pw = env.get("NEWSROOM_PASSWORD")
    assert em and pw, "no creds"
    print("creds loaded: email_len", len(em), "pw_len", len(pw))
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto("https://newsroom.co.nz/wp-login.php", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        ok = page.evaluate("""(creds) => {
            const log = document.querySelector('#user_login');
            const pwd = document.querySelector('#user_pass');
            if (!log || !pwd) return 'no form fields';
            const set = (el, v) => {
                const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
                Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, v);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            };
            set(log, creds[0]);
            set(pwd, creds[1]);
            const rem = document.querySelector('#rememberme');
            if (rem && !rem.checked) rem.click();
            document.querySelector('#loginform').submit();
            return 'submitted';
        }""", [em, pw])
        print("form:", ok)
        page.wait_for_timeout(8000)
        print("post-submit URL:", page.url)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        auth = [n for n in cookies if n.startswith("wordpress_logged_in_") or n.startswith("wordpress_sec_")]
        print("auth cookies:", auth)
        for n in auth:
            print("  len:", n, len(cookies[n]))
        # decisive: a subscriber-gated article renders for the session?
        if auth:
            ctx.storage_state(path="/opt/data/evs-credentials/newsroom_state.json")
            print("state saved")
        b.close()

main()
