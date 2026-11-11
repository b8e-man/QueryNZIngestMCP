#!/usr/bin/env python3
"""Patient fetcher: pull the WrittenQuestions Blazor assemblies through the
residential pool (the consumer host is flaky and our VPS IP is blackholed).
Saves HTML + blazor.boot.json + app .dll files to /tmp/wq-crack/."""
import base64
import json
import os
import random
import re
import secrets
import time
import urllib.request

cfg = json.load(open('/opt/data/beehive-scraper/proxy.json'))
OUT = "/tmp/wq-crack"
os.makedirs(OUT, exist_ok=True)


#: ONE proxy session per run (session suffix on the password, beehive's
#: construction). Rotating mid-run breaks file transfers — a fresh session
#: per request was the WQ transfer problem (2026-11-06). Rotate only on
#: failure.
_OP = None


def opener():
    global _OP
    if _OP is not None:
        return _OP
    u = base64.b64decode(cfg["username_b64"]).decode()
    p = base64.b64decode(cfg["password_base_b64"]).decode() \
        + "_country-nz_session-" + secrets.token_hex(5) + "_lifetime-30m"
    pr = f"http://{u}:{p}@geo.iproyal.com:12321"
    _OP = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": pr, "https": pr}))
    return _OP


def get(url, tries=6):
    global _OP
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return opener().open(req, timeout=45).read()
        except Exception as exc:                     # noqa: BLE001
            print(f"  {url[-50:]} try {i+1}: {type(exc).__name__}", flush=True)
            _OP = None                               # rotate on failure only
            time.sleep(3 + random.random() * 5)
    return None


html = get("https://questions.parliament.nz/")
if not html:
    raise SystemExit("root never came back")
open(f"{OUT}/root.html", "wb").write(html)
print("root:", len(html), flush=True)
boot = get("https://questions.parliament.nz/written-questions/_framework/blazor.boot.json")
if not boot:
    raise SystemExit("boot.json never came back")
open(f"{OUT}/blazor.boot.json", "wb").write(boot)
b = json.loads(boot)
names = [a["name"] for a in b.get("resources", {}).get("assembly", {})]
want = [n for n in names if re.search(r"WrittenQuestions|Client|Shared|Question|Data", n)]
print("want:", want, flush=True)
for n in want:
    data = get(f"https://questions.parliament.nz/written-questions/_framework/{n}")
    if data:
        open(f"{OUT}/{n}", "wb").write(data)
        print("saved", n, len(data), flush=True)
print("DONE", flush=True)
