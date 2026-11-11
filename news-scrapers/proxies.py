"""proxies — the ONE proxy helper (C207). IPRoyal residential, NZ exit
(config: /opt/data/beehive-scraper/proxy.json, creds b64). The password
template is <base>_country-nz_session-<random>_lifetime-30m — a fresh session
id PER SOURCE-RUN keeps one egress identity per sweep (per-request rotation
breaks transfers; rotate on failure only).

Opt-in per source: PROXIED_SOURCES lists the hosts measured refusing this
runtime's egress IP outright (403 for plain and browser UAs) on 2026-11-09
while serving fine via the residential exit — guardianonline.co.nz,
times.co.nz, ecan.govt.nz (Incapsula shell), crux.org.nz. Everything else
goes direct (None). base.run_source asks httpx_proxy(source) for its client;
browserfetch asks playwright_proxy(source) for its launch proxy. This is the
remedy odtconz's docstring prescribes ("if 403/429s appear, wire
ingestion/proxies.py in at the runner level").
"""
from __future__ import annotations

import base64
import json
import secrets
from functools import lru_cache

_CONFIG = "/opt/data/beehive-scraper/proxy.json"

PROXIED_SOURCES = {
    "guardianonline.co.nz",
    "times.co.nz",
    "ecan.govt.nz",
    "crux.org.nz",
    "royalsociety.org.nz",   # 403 direct both UAs, 200 via exit (2026-11-09)
}

_SESSIONS: dict[str, str] = {}  # source -> this run's proxy url


@lru_cache(maxsize=1)
def _creds() -> tuple[str, str, str]:
    cfg = json.load(open(_CONFIG))
    user = base64.b64decode(cfg["username_b64"]).decode()
    base_pw = base64.b64decode(cfg["password_base_b64"]).decode()
    return user, base_pw, cfg["server"]  # http://geo.iproyal.com:12321


def _session_url(source: str) -> str | None:
    source = (source or "").removeprefix("www.")  # render_all passes URL hostnames
    if source not in PROXIED_SOURCES:
        return None
    if source not in _SESSIONS:
        user, base_pw, host = _creds()
        pw = f"{base_pw}_country-nz_session-{secrets.token_hex(6)}_lifetime-30m"
        _SESSIONS[source] = host.replace("http://", f"http://{user}:{pw}@")
    return _SESSIONS[source]


def httpx_proxy(source: str) -> str | None:
    return _session_url(source)


def playwright_proxy(source: str) -> dict | None:
    """Playwright wants credentials as fields, not embedded in the server url
    (embedded creds silently hang Page.goto — measured 2026-11-09)."""
    url = _session_url(source)
    if url is None:
        return None
    user, _, _ = _creds()
    scheme, rest = url.split("://", 1)
    hostport = rest.split("@", 1)[1]
    return {"server": f"{scheme}://{hostport}",
            "username": user,
            "password": rest.split("@", 1)[0].split(":", 1)[1]}
