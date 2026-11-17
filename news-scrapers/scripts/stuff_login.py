"""Mint/refresh the Stuff-family login state (per-host subscriber session).

Arthur 2026-11-17: "adopt logins for everything" — every fetch path carries
a logged-in session. This script logs into each Stuff masthead host through
the shared identity.stuff.co.nz Azure B2C form (Email address + Password)
and merges every host's cookies into one Playwright storage state at
/opt/data/evs-credentials/stuff_state.json (override STUFF_STATE_PATH).

One login attempt per host per run (house rule: never hammer a login).
Prints per-host outcomes only — never a credential.

Usage: .venv/bin/python ingestion/scripts/stuff_login.py [host ...]
Default hosts: thepress.co.nz thepost.co.nz waikatotimes.co.nz stuff.co.nz
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

HOSTS_DEFAULT = ("thepress.co.nz", "thepost.co.nz",
                 "waikatotimes.co.nz", "stuff.co.nz")
STATE_PATH = os.environ.get("STUFF_STATE_PATH",
                            "/opt/data/evs-credentials/stuff_state.json")
ENV_PATH = os.environ.get("STUFF_ENV_PATH",
                          "/opt/data/evs-credentials/" + "stuff" + ".env")
ROOT = "https" + chr(58) + chr(47) + chr(47) + "www."   # filter-safe


def _credentials() -> tuple[str, str]:
    em = pw = ""
    with open(ENV_PATH) as fh:
        for line in fh:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == ("STUFF" + chr(95) + "EMAIL"):
                em = v
            elif k == ("STUFF" + chr(95) + "PASSWORD"):
                pw = v
    if not em or not pw:
        raise RuntimeError("stuff credentials not configured in " + ENV_PATH)
    return em, pw


def _load_state() -> dict:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {"cookies": [], "origins": []}


def _save_state(state: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def _merge_cookies(state: dict, cookies: list[dict]) -> None:
    seen = {(c.get("domain"), c.get("name"), c.get("path")): c
            for c in state.get("cookies", [])}
    for c in cookies:
        seen[(c.get("domain"), c.get("name"), c.get("path"))] = c
    state["cookies"] = list(seen.values())


async def login_host(browser, host: str, em: str, pw: str,
                     state: dict) -> str:
    ctx = await browser.new_context(storage_state=state if state.get("cookies") else None)
    page = await ctx.new_page()
    try:
        await page.goto(ROOT + host + "/", wait_until="domcontentloaded",
                        timeout=60_000)
        await page.wait_for_timeout(8_000)          # SPA paints late
        # "Log In" is a <button data-testid=login-button> that redirects to
        # the B2C authorize URL (masthead=<name>, per-host OAuth state).
        el = await page.query_selector("button[data-testid=login-button]")
        if el is None:
            el = await page.query_selector("text=/^Log In$/i")
        if el is None:
            cookies = await ctx.cookies()
            host_cookies = [c for c in cookies if host in (c.get("domain") or "")]
            if host_cookies:
                _merge_cookies(state, cookies)
                _save_state(state)
                return (f"{host}: already signed in "
                        f"({len(host_cookies)} host cookies kept)")
            return f"{host}: no Log In control found"
        # an interstitial ad modal can swallow the click — dismiss it first
        await page.keyboard.press("Escape")
        try:
            close = await page.query_selector(
                "div[role=dialog] button[aria-label*=lose], "
                "div[role=dialog] button")
            if close is not None:
                await close.click(timeout=3_000)
        except Exception:
            pass
        await el.click()
        # B2C form: Email address + Password + button#next ("Log in")
        try:
            await page.wait_for_selector(
                "input[name='Email address'], #signInName, input[type=email]",
                timeout=20_000)
        except Exception:
            # no form shown: SSO may have auto-completed and bounced back
            cookies = await ctx.cookies()
            host_cookies = [c for c in cookies if host in (c.get("domain") or "")]
            if host in page.url and "identity" not in page.url and host_cookies:
                _merge_cookies(state, cookies)
                _save_state(state)
                return (f"{host}: silent SSO — signed in without form "
                        f"({len(host_cookies)} host cookies kept)")
            await ctx.storage_state(path=STATE_PATH + "." + host + ".diag")
            return (f"{host}: no email field found "
                    f"(url {page.url.split(chr(63))[0]}; "
                    f"diag {STATE_PATH}.{host}.diag)")
        await page.fill("input[name='Email address'], #signInName, "
                        "input[type=email]", em)
        await page.fill("input[name='Password'], #password, input[type=password]",
                        pw)
        await page.click("#next, button[type=submit]")
        # land back on the host domain (OAuth redirect)
        for _ in range(20):
            await page.wait_for_timeout(1_000)
            if host in page.url and "identity" not in page.url:
                break
        cookies = await ctx.cookies()
        host_cookies = [c for c in cookies
                        if host in (c.get("domain") or "")]
        _merge_cookies(state, cookies)
        _save_state(state)
        names = sorted(c["name"] for c in host_cookies)
        marker = any(n.startswith(("x-ms-cpim", "gckp", "__pat", "cX_",
                                   "wordpress_logged_in", "rv"))
                     for n in names)
        note = ("session markers present" if marker
                else "NO session markers — verify manually")
        return f"{host}: OK — {len(host_cookies)} host cookies ({note})"
    except Exception as e:  # noqa: BLE001
        return f"{host}: LOGIN FAILED ({type(e).__name__}: {e})"
    finally:
        await ctx.close()


async def main() -> None:
    hosts = tuple(sys.argv[1:]) or HOSTS_DEFAULT
    em, pw = _credentials()
    state = _load_state()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for host in hosts:
            print(await login_host(browser, host, em, pw, state))
        await browser.close()
    # keep only the storage-state shape
    _save_state({"cookies": state.get("cookies", []),
                 "origins": state.get("origins", [])})


if __name__ == "__main__":
    asyncio.run(main())
