#!/usr/bin/env python3
"""v2: extract UTF-16LE string literals from the .NET WASM assemblies and
find URL/route templates."""
import json
import re
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


# UTF-16LE runs of printable chars, min 5 chars
U16 = re.compile(rb'(?:[\x20-\x7e]\x00){5,200}')

for base, main in (("https://questions.parliament.nz", "WrittenQuestionsWeb.Client.wasm"),
                   ("https://bills.parliament.nz", "HouseWeb.Client.wasm")):
    body = get(f"{base}/_framework/{main}")
    strings = set()
    for m in U16.findall(body):
        strings.add(m.decode("utf-16-le", errors="replace"))
    interesting = [s for s in strings
                   if any(k in s.lower() for k in
                          ("api/", "/api", "attach", "download", "media/",
                           "http", ".pdf", "file/", "asset", "document"))]
    print(f"== {base} ({main}, {len(body)}B, {len(strings)} strings, "
          f"{len(interesting)} interesting)")
    for s in sorted(interesting):
        print("   ", s[:150])
