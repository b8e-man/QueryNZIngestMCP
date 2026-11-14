"""Measure date/author DOM hooks on a live ODT article (cookie auth). Values safe to print."""
import json
import re
import httpx

STATE = "/opt/data/evs-credentials/odt_state.json"
URL = "https://www.odt.co.nz/news/nz-pm-to-lay-wreath-in-london-txi96avw"

def main():
    jar = {}
    for c in json.load(open(STATE)).get("cookies", []):
        if "odt.co.nz" in c.get("domain", "") or "piano.io" in c.get("domain", ""):
            jar[c["name"]] = c["value"]
    html = httpx.get(URL, cookies=jar, timeout=60, follow_redirects=True).text

    # what happened to the old hooks?
    for sel in ["dateline", "field-name-field-source", "page-header", "breadcrumb"]:
        print(f"[{sel}] count:", html.count(sel))

    # candidate date hooks: time tags, meta article:published_time, JSON-LD
    for m in re.findall(r"<meta[^>]+property=\"article:published_time\"[^>]*>", html)[:3]:
        print("META PUB:", m[:160])
    for m in re.findall(r"<time[^>]*>.*?</time>", html)[:5]:
        print("TIME TAG:", m[:160])
    for m in re.findall(r'"datePublished"\s*:\s*"[^"]+"', html)[:3]:
        print("JSON-LD:", m)

    # candidate author hooks
    for m in re.findall(r'"author"\s*:\s*\{[^}]{0,200}\}', html)[:3]:
        print("JSON-LD AUTHOR:", m[:200])
    for m in re.findall(r'<meta[^>]+name="author"[^>]*>', html)[:3]:
        print("META AUTHOR:", m[:160])
    for m in re.findall(r'class="[^"]*author[^"]*"[^>]*>.{0,80}', html)[:6]:
        print("CLASS AUTHOR:", m[:160])
    # byline-ish visible text patterns
    for m in re.findall(r"(?:By|BY)\s+[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){1,3}", html)[:5]:
        print("BYLINE TEXT:", repr(m))

    # date-adjacent visible text (e.g. '12 Nov, 2026' or 'Wednesday, 11 November 2026')
    for m in re.findall(r"\d{1,2}\s+\w+\s*,?\s*20\d{2}|\w+day,?\s+\d{1,2}\s+\w+\s+20\d{2}", html)[:8]:
        print("DATE TEXT:", repr(m))

main()
