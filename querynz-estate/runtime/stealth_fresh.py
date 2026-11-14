#!/usr/bin/env python3
"""Stealth freshness: the ONLY use of the stealth browser (Arthur,
2026-11-05: "let's do the stealth browser for just the freshness ... run
the gathering at a random time during the day so there is no pattern and
use a rotating residential proxy"). Backfill never uses this lane — the
backfill is the wayback rescue (wayback_rescue.py), the legitimate route.

The WAFs (Cloudflare Turnstile, Imperva) defeat our plain client's
fingerprint. Here we browse like a member of the public: patchright
(evades automation fingerprinting), a rotating IPRoyal residential session
per run, 5 s between requests, one host at a time. The challenge must clear
ITSELF — if it ever asks for interaction (a checkbox, an image CAPTCHA),
the host stops at once and is reported. Hard limit 6 stands.

    python stealth_fresh.py --budget-s 900 [--only fma]
"""
import argparse
import base64
import json
import os
import re
import secrets
import sys
import tempfile
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from support import db, jobrun                    # noqa: E402
from support.docstore.landing import land          # noqa: E402

SOURCES_ROOT = os.environ.get("QV4_SOURCES") or "/opt/data/querynz-estate/sources"
PROXY_F = "/opt/data/beehive-scraper/proxy.json"
PAUSE_S = 5.0
CHALLENGE_TITLES = ("just a moment", "pardon our interruption",
                    "attention required", "access denied", "verify you are human")
INTERACTIVE_MARKS = ("verify you are human", "select all images",
                     "i am human", "click the box", "security challenge")

#: never queued as pages: media/binary assets whose FILE NAMES can contain
#: words like "grant"/"recipient" and would otherwise match page_re (the
#: communitymatters audio file that kept stopping the grants surface).
BLOCK_EXT_RE = re.compile(
    r"\.(mp3|mp4|m4a|wav|ogg|jpg|jpeg|png|gif|webp|svg|ico|zip|gz|tgz|"
    r"ics|xml|json|docx?|pptx?|odt|ods)(\?|$)", re.I)

#: freshness surfaces — the hosts whose WAFs refuse the plain client.
#: page_re: links walked as pages (listings/pagination); file_re: landed files.
def _seeded(name):
    pp = os.path.join(HERE, name)
    return [u.strip() for u in open(pp) if u.strip()] if os.path.exists(pp) else []

SURFACES = {
    "fma": {
        "starts": ["https://www.fma.govt.nz/library/warnings-and-alerts/",
                   "https://www.fma.govt.nz/about-us/enforcement/cases/"],
        "page_re": r"fma\.govt\.nz/(library/warnings-and-alerts|about-us/enforcement/cases)/",
        "file_re": r"\.(pdf|xlsx?|csv)(\?|$)",
        "depth": 3,
    },
    "local_elections": {
        "starts": [u.strip().split("\t")[-1] for u in open(
            os.path.join(HERE, "registers", "local_elections", "listings.tsv"))
            if u.strip() and not u.startswith("#")
            and re.search(r"dunedin|gdc\.govt|fndc|ashburtondc", u)
            and u.strip().split("\t")[-1].startswith("http")],
        "page_re": r"(dunedin|gdc\.govt|fndc|ashburtondc)\.govt\.nz/.*"
                   r"(election|return|expense|donation|result)",
        "file_re": r"\.(pdf|xlsx?|csv)(\?|$)",
        "depth": 3,
    },
    "councillor_interests": {
        "starts": [
            "https://www.dunedin.govt.nz/council/governance/elected-members/registers-of-interests",
            "https://www.gdc.govt.nz/council/mayor-and-councillors/Registers-of-Interest",
            "https://www.kaipara.govt.nz/council/elected-members/registers-of-interest",
        ],
        "page_re": r"(dunedin|gdc\.govt|kaipara)\.govt\.nz/.*(interest|pecuniary|register)",
        "file_re": r"\.(pdf|xlsx?|csv)(\?|$)",
        "depth": 2,
    },
    "grants": {
        "starts": _seeded("grants_series_seeds.tsv") + ["https://www.communitymatters.govt.nz/community-organisations-grants-scheme",
                   "https://www.communitymatters.govt.nz/lottery-fund/lottery-fund-grants-made",
                   "https://www.communitymatters.govt.nz/community-led-development-programme/community-led-development-programme-202526-record-of-grants",
                   "https://www.communitymatters.govt.nz/community-led-development-programme/community-led-development-programme-202425-record-of-grants",
                   "https://www.communitymatters.govt.nz/community-led-development-programme/community-led-development-programme-202324-record-of-grants",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2025-community-and-volunteering-capability-fund-record-of-grants-volunteering-sector",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2025-community-and-volunteering-capability-fund-record-of-grants-sector-leadership",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2025-community-and-volunteering-capability-fund-record-of-grants-organisational-capability",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2024-community-and-volunteering-capability-fund-record-of-grants-volunteering-projects-",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2024-community-and-volunteering-capability-fund-record-of-grants-volunteering-organisations",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2024-community-and-volunteering-capability-fund-record-of-grants-sector-leaderhip",
                   "https://www.communitymatters.govt.nz/community-and-volunteering-capability-fund/2024-community-and-volunteering-capability-fund-record-of-grants-organisational-capability",
                   "https://www.communitymatters.govt.nz/lottery-grants-board"],
        "page_re": r"communitymatters\.govt\.nz/.*"
                   r"(grant|record|lottery|cogs|recipient)",
        "file_re": r"\.(pdf|xlsx?|csv)(\?|$)",
        "depth": 2,
    },
    "grants_dia_csv": {
        # the DIA national file's own download URL: a pure freshness check —
        # the held copy's hash is the baseline (gap-ledger 2026-11-05)
        "starts": ["https://catalogue.data.govt.nz/dataset/b6b7f1cc-bfa4-4c7a-81e8-8a03f2983cae"
                   "/resource/06d99ad0-47d6-4591-84c7-8872a4f77da9/download"
                   "/class-4-grants-dataset-csv.csv"],
        "page_re": r"$^",                      # never walks pages
        "file_re": r"class-4-grants-dataset-csv\.csv$",
        "depth": 0,
    },
}


def proxy_config() -> dict:
    cfg = json.load(open(PROXY_F))
    sess = secrets.token_hex(6)      # a fresh session each run: rotation
    return {
        "server": "http://geo.iproyal.com:12321",
        "username": base64.b64decode(cfg["username_b64"]).decode(),
        "password": base64.b64decode(cfg["password_base_b64"]).decode()
        + f"_country-nz_session-{sess}_lifetime-30m",
    }


def manifest_urls(source: str) -> set:
    p = os.path.join(SOURCES_ROOT, source, "manifest.jsonl")
    out = set()
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                for u in row.get("urls", []):
                    out.add(u.get("url"))
                out.update(row.get("names", []))
    except OSError:
        pass
    return {n for n in out if n}


def challenged(pg) -> str:
    t = (pg.title() or "").lower()
    if any(m in t for m in CHALLENGE_TITLES):
        return "challenge title"
    body = ""
    try:
        body = pg.content()[:8000].lower()
    except Exception:                          # noqa: BLE001
        pass
    if any(m in body for m in INTERACTIVE_MARKS):
        return "interactive challenge"
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-s", type=float, default=900)
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    started = jobrun.now()
    conn = db.connect(db.OWNER_KEY, "querynz_v4")
    t0 = time.monotonic()
    out = {"requests": 0, "pages": 0, "files": 0, "new": 0, "failed": 0,
           "stops": [], "stopped": "end"}

    def time_left():
        return time.monotonic() - t0 < a.budget_s

    from patchright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=tempfile.mkdtemp(prefix="stealth-"),
            headless=False, proxy=proxy_config())
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()

        def warm(url: str, force: bool = False) -> str:
            """Land the browser on a STABLE same-origin page: the WAF
            clearance lives in the browser, and same-origin in-page fetch
            then carries it. The file's own URL is a download (goto would
            abort) and the origin ROOT may client-redirect (destroying the
            execution context mid-fetch) — so land on the file's parent
            page: the dataset page for /resource/... downloads, else the
            containing directory."""
            o = urlparse(url)
            cur = urlparse(pg.url or "")
            if not force and cur.netloc == o.netloc and cur.scheme == o.scheme:
                return ""
            if "/resource/" in url:
                target = url.split("/resource/")[0]
            else:
                target = url.rsplit("/", 1)[0]
            for attempt in range(2):
                try:
                    pg.goto(target, timeout=45000, wait_until="domcontentloaded")
                    pg.evaluate("1")        # the context must be alive
                    break
                except Exception as exc:    # noqa: BLE001
                    if attempt == 1:
                        return (f"transport: {type(exc).__name__}: "
                                f"{str(exc)[:120]}")
                    time.sleep(2)
            for _ in range(5):
                why = challenged(pg)
                if not why:
                    break
                pg.wait_for_timeout(2500)
            return challenged(pg)

        def fetch_page(url: str):
            out["requests"] += 1
            try:
                pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            except Exception as exc:           # noqa: BLE001
                out["failed"] += 1
                return None, f"transport: {type(exc).__name__}"
            for _ in range(5):                 # the challenge must clear itself
                why = challenged(pg)
                if not why:
                    break
                pg.wait_for_timeout(2500)
            why = challenged(pg)
            if why:
                return None, why
            time.sleep(PAUSE_S)
            return pg.content().encode("utf-8", "replace"), ""

        def fetch_file(url: str):
            """Files go through in-page fetch, never goto: navigating to a
            PDF lands the viewer's 271-byte placeholder shell (pg.content
            returns the viewer HTML, not the document), and navigating to a
            CSV download aborts the navigation. The bytes come back through
            the page itself and must not look like HTML to be landed."""
            out["requests"] += 1
            why = warm(url)
            if why:
                out["failed"] += 1
                return None, why
            try:
                res = pg.evaluate("""async (u) => {
                    const r = await fetch(u);
                    if (!r.ok) return {err: 'http ' + r.status};
                    const b = new Uint8Array(await r.arrayBuffer());
                    let s = '';
                    for (let i = 0; i < b.length; i += 0x8000)
                        s += String.fromCharCode.apply(
                            null, b.subarray(i, i + 0x8000));
                    return {b64: btoa(s)};
                }""", url)
            except Exception as exc:           # noqa: BLE001
                # a client-side navigation can destroy the context mid-fetch
                # ("Execution context was destroyed"): re-warm and ask once
                err = f"transport: {type(exc).__name__}: {str(exc)[:120]}"
                if "context was destroyed" not in str(exc):
                    out["failed"] += 1
                    return None, err
                why = warm(url, force=True)
                if why:
                    out["failed"] += 1
                    return None, why
                try:
                    res = pg.evaluate("""async (u) => {
                        const r = await fetch(u);
                        if (!r.ok) return {err: 'http ' + r.status};
                        const b = new Uint8Array(await r.arrayBuffer());
                        let s = '';
                        for (let i = 0; i < b.length; i += 0x8000)
                            s += String.fromCharCode.apply(
                                null, b.subarray(i, i + 0x8000));
                        return {b64: btoa(s)};
                    }""", url)
                except Exception as exc2:      # noqa: BLE001
                    out["failed"] += 1
                    return None, (f"transport: {type(exc2).__name__}: "
                                  f"{str(exc2)[:120]}")
            if not res or res.get("err"):
                out["failed"] += 1
                return None, (res or {}).get("err", "no response")
            body = base64.b64decode(res["b64"])
            head = body[:200].lstrip().lower()
            if head.startswith((b"<!doctype", b"<html")):
                return None, "challenge page in file response"
            time.sleep(PAUSE_S)
            return body, ""

        for source, spec in SURFACES.items():
            if a.only and source != a.only:
                continue
            if not time_left():
                break
            held = manifest_urls(source)
            page_re = re.compile(spec["page_re"], re.I)
            file_re = re.compile(spec["file_re"], re.I)
            queue = [(u, 0) for u in spec["starts"]]
            seen = set()
            hosts = {urlparse(u).netloc for u in spec["starts"]}
            while queue and time_left():
                url, depth = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                is_file = bool(file_re.search(url))
                body, why = fetch_file(url) if is_file else fetch_page(url)
                if body is None:
                    out["stops"].append(f"{source}: {why} at {url[:80]}")
                    break           # a refused host stops this run (take it easy)
                # land ALWAYS: by-hash dedupe makes repeats free, and a page
                # that changed lands under its new hash (the freshness record)
                ref, new = land(body, name=url, source=source, conn=conn,
                                name_kind="url",
                                content_type="" if is_file else "text/html")
                if is_file:
                    out["files"] += 1
                else:
                    out["pages"] += 1
                out["new"] += 1 if new else 0
                held.add(url)
                if is_file or depth >= spec["depth"]:
                    continue        # files carry no links; pages at depth stop
                stuck = False
                for href in pg.eval_on_selector_all(
                        "a[href]", "els => els.map(e => e.href)"):
                    href = href.split("#")[0]
                    if not href.startswith("http"):
                        continue
                    if urlparse(href).netloc not in hosts:
                        continue    # off-host links are never walked
                    if file_re.search(href):
                        if href in held:
                            continue
                        fbody, fwhy = fetch_file(href)
                        if fbody is None:
                            out["stops"].append(f"{source}: {fwhy} at {href[:80]}")
                            stuck = True
                            break
                        ref, new = land(fbody, name=href, source=source,
                                        conn=conn, name_kind="url",
                                        content_type="")
                        out["files"] += 1
                        out["new"] += 1 if new else 0
                        held.add(href)
                    elif BLOCK_EXT_RE.search(href):
                        continue    # media/asset: never a page
                    elif page_re.search(href) and href not in seen:
                        queue.append((href, depth + 1))
                if stuck:
                    break           # take it easy: a refused host stops the run
                time.sleep(PAUSE_S)
        ctx.close()
    conn.close()
    detail = (f"stealth_fresh: requests {out['requests']}, pages {out['pages']}, "
              f"files {out['files']}, new {out['new']}, failed {out['failed']}"
              + ("; " + " | ".join(out["stops"]) if out["stops"] else "; end"))
    print(detail)
    jobrun.record("qv4-stealth-fresh", not out["stops"], detail, started, out)


if __name__ == "__main__":
    main()
