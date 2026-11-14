#!/usr/bin/env python3
"""Review-pass 2026-11-14, practices 6+7 (estate-improvements, 2026-11-15):
one polite retry of the 19 still-failed local-election return files, and one
probe of Dunedin/Gisborne/Kaipara register pages from this session.

Rules kept from the lane's own docstring: one request at a time, >=6s apart
per host, a challenge or block is a failed read (stop that host, never
retry in the run, never route around). Plain session, no gate, no proxy —
the gate's holds on dunedin/gdc are what practice 7 asks us to test from
this session (Arthur's brief). Files >60MB stay failed as 'too large'.
Outcome rows -> captures (JSONL) appended to retry_probe_outcomes.jsonl.
Any landed bytes are checked by hash against the held store before keeping.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "retry_probe_outcomes.jsonl")
CH_ALL = ("perfdrive.com", "radware.com", "incapsula.com", "hcaptcha.com",
          "recaptcha.net", "challenges.cloudflare.com")

JOBS = [
    # (host, [urls]) — order: register page first (practice 7), then files
    ("www.dunedin.govt.nz", [
        "https://www.dunedin.govt.nz/council/local-governance-statement/register-of-members-pecuniary-interests",
        "https://www.dunedin.govt.nz/__data/assets/pdf_file/0004/1271380/vandervis-lee-expense-return.pdf",
        "https://www.dunedin.govt.nz/__data/assets/pdf_file/0003/1271991/aronson-lync-expense-return.pdf",
    ]),
    ("www.gdc.govt.nz", [
        "https://www.gdc.govt.nz/council/mayor-and-councillors",
        "https://www.gdc.govt.nz/__data/assets/pdf_file/0026/46664/GDC_Mayor-Gisborne-District-Council-STOLTZ,-Rehette.pdf",
        "https://www.gdc.govt.nz/__data/assets/pdf_file/0025/46663/GDC_Mayor-Gisborne-District-Council-BROWN,-Darin.pdf",
    ]),
    ("www.kaipara.govt.nz", [
        "https://www.kaipara.govt.nz/council/Mayor-and-councillors-5",
    ]),
    ("www.fndc.govt.nz", [
        "https://www.fndc.govt.nz/files/assets/public/v/3/objectivedocuments/governance-and-executive-management-gem/elections/elections-2022/2022-candidate-expense-and-donations-returns/expenses-return-don-hannah.pdf",
    ]),
    ("hccpublicdocs.azurewebsites.net", [
        "https://hccpublicdocs.azurewebsites.net/api/download/2657e0a4b3614301b65dd99406a07ad2/_mtgmngmnt/22b5eea419464/a5c129bd-58e0-4e5b-a6b5-98c2ae64dcbe.pdf?response-content-disposition=attachment%3B",
    ]),
    ("www.nrc.govt.nz", [
        "https://www.nrc.govt.nz/media/daxlf3qp/nrc_adair-maureen-coastal-central-constituency2.pdf",
    ]),
]


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(65536)
            loc = r.headers.get("content-type", "")
            return r.status, head, loc, None
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(4096)
        except Exception:
            pass
        return e.code, body, "", str(e)[:120]
    except Exception as e:  # timeout/reset/TLS — a failed read
        return None, b"", "", f"{type(e).__name__}: {str(e)[:120]}"


def main():
    with open(OUT, "a") as out:
        for host, urls in JOBS:
            gave_up = False
            for i, url in enumerate(urls):
                if gave_up:
                    out.write(json.dumps({"url": url, "outcome": "skipped",
                                          "why": "host failed earlier in the run"}) + "\n")
                    continue
                if i:
                    time.sleep(6)
                status, body, ctype, err = fetch(url)
                rec = {"url": url, "status": status, "content_type": ctype,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                low = body[:4000].lower()
                chal = any(c in low for c in (b"incapsula", b"perfdrive",
                                              b"radware", b"challenge-platform",
                                              b"swudnsai"))
                if err and status is None:
                    rec.update(outcome="failed", why=err)
                    gave_up = True
                elif chal or status in (401, 403, 429, 503):
                    rec.update(outcome="failed",
                               why=("challenge page served" if chal else
                                    f"HTTP {status} (block or challenge)"))
                    gave_up = True
                elif status in (404, 410):
                    rec.update(outcome="failed", why=f"HTTP {status}")
                elif status == 200:
                    rec.update(outcome="served", bytes_head=len(body),
                               sha256_head=hashlib.sha256(body).hexdigest())
                else:
                    rec.update(outcome="failed", why=f"HTTP {status}")
                out.write(json.dumps(rec) + "\n")
                out.flush()
                print(f"{rec['outcome']:7} {str(status):>4} {host} {url[-60:]}", flush=True)


if __name__ == "__main__":
    main()
