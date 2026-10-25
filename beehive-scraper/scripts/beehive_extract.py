#!/usr/bin/env python3
"""Beehive extraction stage — deterministic metadata + LLM topics/quotes.

Reads captured bodies (via done.jsonl -> data/pages/), extracts:
  deterministic: url, type, title, published_at, ministers[], portfolios[],
                 body_text, word_count
  LLM (Nous deepseek-v4.1-flash): topics[], quotes[{text, speaker}]

Writes one record per (url, sha256) to /opt/data/beehive-scraper/extracted.jsonl.
Raw HTML in data/pages/ is NEVER touched — this is a downstream stage.

Idempotent: records already in extracted.jsonl (same url+sha) are skipped.
Re-run after a body is re-captured (sha changes) to re-extract.

Exit semantics (cron no_agent): silent + exit 0 on success or nothing to do;
stderr + exit 1 on failure so the scheduler alerts.

Auth: reads /opt/data/shared/nous_auth.json fresh on every call (Hermes
refreshes that store continuously). On 401, best-effort OAuth2 refresh grant
against the portal; if that fails, exit 1 (cron alert).
"""

import argparse
import html as htmllib
import json
import os
import re
import sys
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/beehive-scraper"
DONE_F = os.path.join(BASE, "done.jsonl")
OUT_F = os.path.join(BASE, "extracted.jsonl")
AUTH_F = "/opt/data/shared/nous_auth.json"
FAIL_F= os.path.join(BASE, "failures.jsonl")
MODEL = "deepseek/deepseek-v4-flash"  # non-thinking ~3s/doc clean JSON;
                                      # v4.1-flash reasons too long for bulk
MAX_BODY_CHARS = 12000   # LLM input cap per doc
FALLBACK_MODEL = "z-ai/glm-5.3-flash"   # for docs v4-flash chokes on

RE_TITLE = re.compile(r'<h1 class="article__title[^"]*">\s*(.*?)\s*</h1>', re.S)
RE_DATE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2}T[^"]+)"')
RE_MINISTER = re.compile(
    r'<a href="(/minister/[^"]+)" class="field-group-link minister__link"'
    r'[\s\S]*?minister__title">\s*(.*?)\s*</div>')
RE_PORTFOLIO = re.compile(
    r'<em class="tag tag--portfolio">[\s\S]{0,800}?'
    r'taxonomy-term--type-portfolios[^>]*>\s*<a[^>]*>\s*(.*?)\s*</a>')
RE_BODY_START = re.compile(r'field--name-body[^>]*>')
RE_TOKEN = re.compile(r'<div\b[^>]*>|</div>|<[^>]*>|[^<]+')


def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', htmllib.unescape(s)).strip()


def parse_body(html):
    """Text content of the article body div.

    Pages contain several field--name-body divs (nav/menu blocks too), so all
    candidates are parsed and the longest text wins.
    """
    best = ""
    for m in RE_BODY_START.finditer(html):
        depth = 0
        out = []
        for tok in RE_TOKEN.finditer(html[m.end():]):
            t = tok.group(0)
            if t.startswith("</div"):
                depth -= 1
                if depth < 0:
                    break
            elif t.startswith("<div"):
                depth += 1
            elif t.startswith("<"):
                continue          # any non-div tag: skip entirely
            elif t.strip():
                out.append(t.strip())
        text = re.sub(r'\s+', ' ', htmllib.unescape(" ".join(out))).strip()
        if len(text) > len(best):
            best = text
    return best


def parse_page(url, html):
    t = RE_TITLE.search(html)
    d = RE_DATE.search(html)
    body = parse_body(html)
    return {
        "url": url,
        "type": next((t2 for t2 in ("release", "speech", "feature")
                      if f"/{t2}/" in url), "page"),
        "title": strip_tags(t.group(1)) if t else "",
        "published_at": d.group(1) if d else "",
        "ministers": [{"name": strip_tags(n), "slug": s.split("/")[-1]}
                      for s, n in RE_MINISTER.findall(html)],
        "portfolios": [strip_tags(p) for p in RE_PORTFOLIO.findall(html)],
        "body_text": body,
        "word_count": len(body.split()),
    }


PROMPT = """You extract structured data from a New Zealand government publication (Beehive.govt.nz).
Given the text below, return ONLY a JSON object:
{"topics": ["3-7 short NZ policy topic labels, e.g. 'transport', 'health', 'education', 'trade', 'climate'"],
 "quotes": [{"text": "verbatim quote", "speaker": "who said it (person's name, or empty string if the document does not attribute)"}]}
Rules: quotes MUST be verbatim from the text (in quotation marks or clearly attributable speech); if there are none, use []. No commentary, JSON only.

TEXT:
"""


def _chat(prompt, token, base_url, max_tokens, model=MODEL):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    budget = max(12, min(180, DEADLINE[0] - time.time()))
    with urllib.request.urlopen(req, timeout=budget) as r:
        resp = json.loads(r.read())
    choice = resp["choices"][0]
    return choice["message"].get("content"), choice.get("finish_reason")


def llm_extract(body_text, token, base_url, model=None):
    """One shot; one retry on truncation/parse failure with a firmer prompt."""
    model = model or MODEL
    prompt = PROMPT + body_text[:MAX_BODY_CHARS]
    content, finish = _chat(prompt, token, base_url, 4000, model)
    if not content or finish == "length":
        content, finish = _chat(
            prompt + "\n\nREMINDER: respond with ONLY the JSON object. "
            "Escape double quotes inside strings. Keep it short.",
            token, base_url, 8000, model)
    if not content:
        raise ValueError("null LLM content (reasoning truncation)")
    m = re.search(r'\{[\s\S]*\}', content)
    if not m:
        raise ValueError(f"no JSON in LLM output: {content[:120]!r}")
    try:
        data = json.loads(m.group(0), strict=False)
    except json.JSONDecodeError:
        fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', m.group(0))
        data = json.loads(fixed, strict=False)
    topics = [str(t) for t in data.get("topics", [])][:7]
    quotes = [{"text": str(q.get("text", ""))[:500],
               "speaker": str(q.get("speaker", ""))[:120]}
              for q in data.get("quotes", []) if q.get("text")]
    return topics, quotes


PROXY_URL="http://127.0.0.1:8645/v1"   # hermes proxy (see hermes_proxy_watchdog.sh):
    # attaches Nous creds itself, handles single-use refresh-token rotation.
    # NEVER call portal /api/oauth/token from scripts — reuse detection revokes
    # the whole session chain (hermes_cli/auth.py warns explicitly).


class Transient(Exception):
    """Network/auth hiccup — retry next tick, never burns the fail cap."""


TRANSIENT_CODES = {401, 403, 408, 429, 500, 502, 503, 504}
DEADLINE = [0.0]


def is_transient(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code in TRANSIENT_CODES
    return isinstance(e, (urllib.error.URLError, socket.timeout,
                          TimeoutError, ConnectionError)) or "timed out" in str(e).lower()


def get_auth():
    return "proxy", PROXY_URL, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--time-budget", type=int, default=90,
                    help="stop after N seconds (cron runner kills at ~120s)")
    args = ap.parse_args()

    done = {}          # url -> (path, sha) for ok bodies
    with open(DONE_F) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("status") == "ok" and r.get("path"):
                    done[r["url"]] = (r["path"], r.get("sha256", ""))
            except Exception:
                pass

    seen = set()       # (url, sha) already extracted
    if os.path.exists(OUT_F):
        with open(OUT_F) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    seen.add((r["url"], r.get("sha256", "")))
                except Exception:
                    pass

    fail_ct = {}
    if os.path.exists(FAIL_F):
        with open(FAIL_F) as f:
            for line in f:
                try:
                    u = json.loads(line)["url"]
                    fail_ct[u] = fail_ct.get(u, 0) + 1
                except Exception:
                    pass
    # docs that failed 5+ times are poisoned (bad markup/API edge) — stop retrying
    todo = [(u, p, s) for u, (p, s) in done.items()
            if (u, s) not in seen and fail_ct.get(u, 0) < 5]
    if not todo:
        sys.exit(0)

    def work(item):
        url, path, sha = item
        with open(os.path.join(BASE, "data", "pages", path),
                  encoding="utf-8") as f:
            html = f.read()
        rec = parse_page(url, html)
        rec["sha256"] = sha
        rec["source_file"] = path
        rec["model"] = MODEL
        token, base_url, _ = get_auth()
        try:
            rec["topics"], rec["quotes"] = llm_extract(
                rec["body_text"], token, base_url, MODEL)
        except Exception as e:
            if is_transient(e):
                raise Transient(str(e)[:150])
            if time.time() > DEADLINE[0] - 20:
                raise Transient(str(e)[:150])   # no time for fallback; retry next tick
            # deterministic odd doc — one try with the fallback model
            rec["model"] = FALLBACK_MODEL
            rec["topics"], rec["quotes"] = llm_extract(
                rec["body_text"], token, base_url, FALLBACK_MODEL)
        rec["extracted_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        return rec

    from concurrent.futures import ThreadPoolExecutor, as_completed
    ok = failed = transient = 0
    errors = []
    batch = todo[:args.limit]
    t0 = time.time()
    DEADLINE[0] = t0 + args.time_budget
    done_n = 0
    out = open(OUT_F, "a")
    ex = ThreadPoolExecutor(max_workers=12)
    try:
        i = 0
        while i < len(batch):
            remaining = args.time_budget - (time.time() - t0)
            if remaining <= 2:
                break
            wave = batch[i:i + 24]
            i += 24
            futs = {ex.submit(work, it): it for it in wave}
            try:
                for fut in as_completed(futs, timeout=max(2, remaining)):
                    done_n += 1
                    try:
                        rec = fut.result()
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        out.flush()
                        ok += 1
                    except Transient:
                        transient += 1          # no FAIL_F burn: auth/net hiccups
                    except Exception as e:
                        failed += 1
                        errors.append(f"{futs[fut][0]}: {e}"[:150])
                        with open(FAIL_F, "a") as ff:
                            ff.write(json.dumps({"url": futs[fut][0],
                                                 "error": str(e)[:150],
                                                 "ts": datetime.now(timezone.utc).isoformat(
                                                     timespec="seconds")}) + "\n")
            except TimeoutError:
                break        # slow wave hit the budget — resume next tick
    finally:
        out.close()
        ex.shutdown(wait=False, cancel_futures=True)
    # alert only on real trouble: total failure or heavy failure rate.
    # A couple of stubborn docs are normal — they retry (capped) next run.
    if failed and (ok == 0 or failed > max(3, (ok + failed) // 4)):
        print(f"beehive extract: {ok} ok, {failed} failed, {transient} transient. "
              f"Errors: {'; '.join(errors)}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
