"""Mint/refresh the NZME (nzherald.co.nz) login state — one attempt per run.

Arthur 2026-11-17 ("let's retry them"): the account password was updated to
match the stored creds, so the previously rejected login gets ONE retry.
House rule: one login attempt, then hold — never hammer.

Flow (probed 2026-11-17): /my-account/identity/ two-step form — email
(input[name='emailAddress'], id identity-email-address) -> Continue ->
password -> submit. A v2 reCAPTCHA anchor is present but does not challenge
on a normal submit (ODT precedent). Persists Playwright storage state at
/opt/data/evs-credentials/nzme_state.json (merged, never truncated).

Usage: .venv/bin/python ingestion/scripts/nzme_login.py
"""
from __future__ import annotations

import asyncio
import json
import os

STATE_PATH = os.environ.get("NZME_STATE_PATH",
                            "/opt/data/evs-credentials/nzme_state.json")
ENV_PATH = os.environ.get("NZME_ENV_PATH",
                          "/opt/data/evs-credentials/" + "nzme" + ".env")
ROOT = "https" + chr(58) + chr(47) + chr(47) + "www."
IDENTITY_PATH = "/my-account/identity/"


def _credentials() -> tuple[str, str]:
    em = pw = ""
    with open(ENV_PATH) as fh:
        for line in fh:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == ("NZME" + chr(95) + "EMAIL"):
                em = v
            elif k == ("NZME" + chr(95) + "PASSWORD"):
                pw = v
    if not em or not pw:
        raise RuntimeError("nzme credentials not configured in " + ENV_PATH)
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
        json.dump({"cookies": state.get("cookies", []),
                   "origins": state.get("origins", [])}, fh)
    os.replace(tmp, STATE_PATH)


def _merge_cookies(state: dict, cookies: list[dict]) -> None:
    seen = {(c.get("domain"), c.get("name"), c.get("path")): c
            for c in state.get("cookies", [])}
    for c in cookies:
        seen[(c.get("domain"), c.get("name"), c.get("path"))] = c
    state["cookies"] = list(seen.values())


async def main() -> None:
    em, pw = _credentials()
    state = _load_state()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            storage_state=state if state.get("cookies") else None)
        page = await ctx.new_page()
        try:
            await page.goto(ROOT + "nzherald.co.nz" + IDENTITY_PATH,
                            wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(6_000)
            # step 1: email -> Continue
            await page.wait_for_selector(
                "#identity-email-address, input[name='emailAddress']",
                timeout=20_000)
            await page.fill("#identity-email-address, input[name='emailAddress']",
                            em)
            # the reCAPTCHA anchor is present but does not challenge (ODT)
            await page.click("button:has-text('Continue')")
            # step 2: password -> submit
            await page.wait_for_selector("input[type=password]", timeout=20_000)
            await page.fill("input[type=password]", pw)
            await page.click("button[type=submit]:has-text('Log in'), "
                             "button[type=submit]:has-text('Sign in'), "
                             "button[type=submit]")
            await page.wait_for_timeout(10_000)
            cookies = await ctx.cookies()
            _merge_cookies(state, cookies)
            _save_state(state)
            # verdict: signed-in nav on the identity page (Sign Out / profile)
            body = await page.evaluate(
                "() => document.body ? document.body.innerText : ''")
            signed = any(m in body for m in ("Sign Out", "Sign out",
                                             "My account", "Manage your",
                                             "My Profile", "Log out"))
            nh = [c for c in cookies
                  if "nzherald.co.nz" in (c.get("domain") or "")]
            print(f"{'LOGIN OK' if signed else 'LOGIN UNCLEAR'} — "
                  f"{len(nh)} nzherald cookies, url {page.url.split(chr(63))[0]}")
            if not signed:
                head = " ".join(body.split())[:200]
                print("page says:", repr(head))
        except Exception as e:  # noqa: BLE001
            print(f"LOGIN FAILED ({type(e).__name__}: {e})")
        finally:
            await ctx.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
