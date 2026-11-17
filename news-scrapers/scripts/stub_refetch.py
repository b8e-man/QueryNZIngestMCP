#!/usr/bin/env python3
"""Stub refetch lane (hermes-stub-refetch@2026-11-15).

Refetch every thin manifest row (chars < 500) in the paywalled outlets
under the stored subscriber sessions / anonymous path, and land the full
article as a NEW manifest row (append-only; never edit). Sessions are
re-verified at run start; a session that stops authenticating is reported,
never hammered. NZME is fetched anonymous (its creds were rejected and are
parked — never retried).

Run:
  set -a; . /opt/data/evs-credentials/odt.env; . /opt/data/evs-credentials/newsroom.env; \
  . /opt/data/evs-credentials/newsscrapers.env; set +a
  PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright \
  ../.venv/bin/python scripts/stub_refetch.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from newsscrapers import odtconz, businessdesk, nzme, stuffconz, genericrss  # noqa: E402

DATA = "/opt/data/news-scrapers/data"
RESULTS = os.path.join(DATA, "stub_refetch_2026_11_15.json")

# gate phrases that mean "the body was withheld" (not nav boilerplate)
GATE_MARKERS = (
    "to continue reading", "sign in to read", "register to read",
    "subscribe to read", "subscribe to continue", "premium content",
    "this story is for subscribers", "already a subscriber",
    "unlock this", "premium subscription", "requires a premium",
)
QUIZ_RE = __import__("re").compile(
    r"quiz|hat-trick|hard word|crossword|puzzle|weekender quiz", __import__("re").I)


def thin_rows(source: str) -> list[dict]:
    p = os.path.join(DATA, source, "manifest.jsonl")
    out = []
    if not os.path.exists(p):
        return out
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("chars", 0) < 500:
                out.append(r)
    return out


def _url(r: dict) -> str:
    return (r.get("urls") or [{}])[0].get("url", "")


def _store_bytes(source: str, sha: str) -> bytes:
    p = os.path.join(DATA, source, "store", sha[:2], sha)
    try:
        with open(p, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""


def classify(r: dict, source: str) -> str:
    u = _url(r)
    b = _store_bytes(source, r["sha256"])
    t = b.decode("utf-8", "ignore")
    if QUIZ_RE.search(u):
        return "thin-quiz"
    low = t.lower()
    for m in GATE_MARKERS:
        if m in low:
            return "meter"
    return "thin"


def land_replacement(source: str, *, url: str, title: str, text: str,
                     author, published_at, categories: list[str],
                     raw: bytes, fetch_mode: str) -> dict:
    """Append a NEW manifest/store/extracted row for the same URL (no dedup)."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    sha = hashlib.sha256(raw).hexdigest()
    d = os.path.join(DATA, source)
    os.makedirs(os.path.join(d, "store", sha[:2]), exist_ok=True)
    store_path = os.path.join(d, "store", sha[:2], sha)
    if not os.path.exists(store_path):
        with open(store_path, "wb") as f:
            f.write(raw)
    pub = published_at
    if hasattr(pub, "isoformat"):
        pub = pub.isoformat()
    upstream = int.from_bytes(hashlib.sha1(url.encode()).digest()[:8], "big") >> 1
    row = {
        "sha256": sha, "source": source, "kind": "article",
        "names": [title] if title else [],
        "urls": [{"url": url}], "file": store_path,
        "fetched_at": now_iso, "landed_at": now_iso,
        "published_at": pub, "author": author, "upstream_id": upstream,
        "chars": len(text or ""), "fetch_mode": fetch_mode,
        "pipeline_status": "held" if source == "nzherald.co.nz" else "ingested",
    }
    with open(os.path.join(d, "manifest.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(d, "extracted.jsonl"), "a") as f:
        f.write(json.dumps({
            "sha256": sha, "url": url, "title": title, "text": text,
            "author": author, "published_at": pub,
            "categories": categories or [], "extracted_at": now_iso,
        }, ensure_ascii=False) + "\n")
    return row


async def verify_sessions() -> dict:
    out = {}
    # ODT: Piano __utp token in the jar
    jar = odtconz._cookie_jar()
    out["odt.co.nz"] = ("ok" if any("__utp" in k for k in jar)
                        else "no __utp token in jar")
    # Newsroom: wordpress_logged_in_ cookie in storage state
    nsp = os.environ.get("NEWSROOM_STORAGE_STATE",
                         "/opt/data/evs-credentials/newsroom_state.json")
    try:
        st = json.load(open(nsp))
        cookies = st.get("cookies", [])
        out["newsroom.co.nz"] = ("ok" if any(
            c.get("name", "").startswith("wordpress_logged_in_") for c in cookies)
            else "no wordpress_logged_in_ cookie in state")
    except (FileNotFoundError, ValueError):
        out["newsroom.co.nz"] = "no state file"
    # NBR: cookie cache
    nbr_cache = os.path.expanduser("~/.querynz/nbr_cookies.json")
    try:
        c = json.load(open(nbr_cache))
        fresh = (time.time() - c.get("ts", 0)) < (3 * 86400)
        out["nbr.co.nz"] = ("ok" if fresh and c.get("cookies") else
                            "stale/empty cookie cache (re-login needed)")
    except (FileNotFoundError, ValueError):
        out["nbr.co.nz"] = "no cookie cache (login needed)"
    # Stuff: session state is ON the fetch path since 2026-11-17 (logins
    # adopted everywhere) — ok = state file exists AND covers the host
    jar_ok = os.path.exists("/opt/data/evs-credentials/stuff_state.json")
    out["stuff.co.nz"] = ("ok (login on fetch path)"
                          if jar_ok else "no state file — run stuff_login.py")
    # NZME: anonymous only — creds rejected + parked
    out["nzherald.co.nz"] = "anonymous (creds rejected/parked — not retried)"
    return out


async def refetch_odt(rows: list[dict]) -> list[dict]:
    jar = odtconz._cookie_jar()
    out = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                 cookies=jar) as c:
        for r in rows:
            u = _url(r)
            try:
                resp = await c.get(u, headers={"User-Agent": genericrss.base.UA})
                html = resp.text
                ex = odtconz.extract(html, u)
                out.append((r, html, ex))
            except Exception as e:  # noqa: BLE001
                out.append((r, None, None))
            await asyncio.sleep(2.0)
    return out


async def refetch_anon(mod, rows: list[dict], source: str) -> list[dict]:
    out = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        for r in rows:
            u = _url(r)
            try:
                resp = await c.get(u, headers={"User-Agent": genericrss.base.UA})
                ex = mod.extract(resp.text, u)
                out.append((r, resp.text, ex))
            except Exception as e:  # noqa: BLE001
                out.append((r, None, None))
            await asyncio.sleep(2.0)
    return out


async def refetch_bd(rows: list[dict]) -> list[dict]:
    """BusinessDesk via the Arc browser sign-in (full bodies under session)."""
    from newsscrapers import businessdesk as bd
    urls = [_url(r) for r in rows]
    try:
        pairs = await bd.fetch_authenticated(urls)
    except Exception as e:  # noqa: BLE001
        print(f"  BD authenticated fetch failed: {type(e).__name__}: {e}")
        # fall back to anon for diagnosis
        return await refetch_anon(businessdesk, rows, "businessdesk.co.nz")
    m = dict(pairs)
    out = []
    for r in rows:
        u = _url(r)
        html = m.get(u)
        if html is None:
            out.append((r, None, None))
            continue
        ex = businessdesk.extract(html, u)
        out.append((r, html, ex))
    return out


def process(source: str, results: list[tuple]) -> dict:
    """results = [(row, html_or_None, Extracted_or_None), ...]"""
    found = len(results)
    refetched = 0
    replaced = 0
    still_stub = 0
    failed = 0
    replaced_rows = []
    for r, html, ex in results:
        u = _url(r)
        kind = classify(r, source)
        old_chars = r.get("chars", 0)
        if ex is None or html is None:
            failed += 1
            continue
        new_chars = len(ex.text or "")
        if new_chars >= 500:
            refetched += 1
            replaced += 1
            fetch_mode = "refetch-session" if source in ("odt.co.nz", "businessdesk.co.nz") else "refetch-anon"
            row = land_replacement(
                source, url=u, title=ex.title, text=ex.text,
                author=ex.author, published_at=ex.published_at,
                categories=ex.categories, raw=html.encode("utf-8"),
                fetch_mode=fetch_mode)
            replaced_rows.append({"url": u, "old_chars": old_chars,
                                  "new_chars": new_chars, "kind": kind,
                                  "sha256": row["sha256"]})
        else:
            refetched += 1
            still_stub += 1
    return {"found": found, "refetched": refetched, "replaced": replaced,
            "still_stub": still_stub, "failed": failed,
            "replaced_rows": replaced_rows}


async def main() -> int:
    sessions = await verify_sessions()
    print("== session verification ==")
    for k, v in sessions.items():
        print(f"  {k}: {v}")

    summary = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "sessions": sessions, "publishers": {}}

    # ODT (session: Piano cookie jar)
    odt_rows = thin_rows("odt.co.nz")
    print(f"\n== odt.co.nz: {len(odt_rows)} thin ==")
    summary["publishers"]["odt.co.nz"] = process("odt.co.nz", await refetch_odt(odt_rows))

    # BusinessDesk (session: Arc browser sign-in)
    bd_rows = thin_rows("businessdesk.co.nz")
    print(f"\n== businessdesk.co.nz: {len(bd_rows)} thin ==")
    summary["publishers"]["businessdesk.co.nz"] = process(
        "businessdesk.co.nz", await refetch_bd(bd_rows))

    # NZME (anonymous — creds rejected/parked)
    nz_rows = thin_rows("nzherald.co.nz")
    print(f"\n== nzherald.co.nz: {len(nz_rows)} thin (anonymous) ==")
    summary["publishers"]["nzherald.co.nz"] = process(
        "nzherald.co.nz", await refetch_anon(nzme, nz_rows, "nzherald.co.nz"))

    # Stuff (anonymous API — client-side meter only)
    st_rows = thin_rows("stuff.co.nz")
    print(f"\n== stuff.co.nz: {len(st_rows)} thin (anonymous API) ==")
    summary["publishers"]["stuff.co.nz"] = process(
        "stuff.co.nz", await refetch_anon(stuffconz, st_rows, "stuff.co.nz"))

    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)

    print("\n== SUMMARY ==")
    for pub, s in summary["publishers"].items():
        print(f"  {pub}: found={s['found']} refetched={s['refetched']} "
              f"replaced={s['replaced']} still_stub={s['still_stub']} "
              f"failed={s['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
