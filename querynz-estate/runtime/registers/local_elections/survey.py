"""The survey (tranche a): where each council publishes its candidates'
returns of electoral donations and expenses, through the fetch gate only.

Per host, at most: the home page, the sitemap the robots file names (or
`/sitemap.xml`), up to `MAX_CHILD_SITEMAPS` child sitemaps, and the pages a
sitemap or the home page names whose address says returns, donations,
expenses or elections (at most `MAX_PAGES` per host). Every answer is kept
in the scratch folder by sha256 with its status; nothing is printed but
addresses, statuses and counts. A 403, 429, 5xx or challenge page is a
failed read (hard limit 6): logged, the host is not asked again this run.

    python -m registers.local_elections.survey [--hosts a,b] [--out DIR]
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse

import support.fetchgate as fg

SCRATCH = os.environ.get("QV4_SCRATCH") or "/home/user/querynzv4-work/scratch/local-elections-1"
POSITIONS = os.environ.get("QV4_POSITIONS") or None
HERE = os.path.dirname(os.path.abspath(__file__))
POSITION = os.path.join(HERE, "position", "local-election-candidate-returns.md")
MAX_CHILD_SITEMAPS = 6
MAX_PAGES = 4
FLOOR_S = 5.0
#: the hosts a survey of one place for many councils asks first; the rest of the position's list is the councils
COLLECTED = ("electionz.com", "electionservices.co.nz", "lgnz.co.nz", "votelocal.co.nz")
RETURNS_WORDS = re.compile(r"donation|expense|electoral-return|candidate-return|returns-of-elect|elector[a-z-]*return", re.I)
ELECTION_WORDS = re.compile(r"election", re.I)
TERMS_WORDS = re.compile(r"copyright|terms-of-use|terms-and-conditions|disclaimer|/terms\b|legal", re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)""", re.I)


class FloorPacer(fg.Pacer):
    """The gate's pacer with the lane's floor under it: never faster than FLOOR_S to one host."""

    def wait(self, host: str, floor: float) -> float:
        return super().wait(host, max(floor, FLOOR_S))


PACER = FloorPacer()


def hosts_of_position(path: str = POSITION) -> list:
    with open(path, encoding="utf-8") as f:
        m = re.search(r"^hosts:\s*(.+)$", f.read(), re.M)
    return [h.strip() for h in m.group(1).split(",") if h.strip()]


def rank(url: str) -> int:
    """Lower is better: a returns page first, an election page second."""
    u = urllib.parse.urlsplit(url.lower()).path
    if RETURNS_WORDS.search(u) and ELECTION_WORDS.search(u):
        return 0
    if RETURNS_WORDS.search(u):
        return 1 if not u.endswith((".pdf", ".docx", ".xlsx")) else 2
    if ELECTION_WORDS.search(u):
        return 3
    return 9


def links(body: bytes, base: str) -> list:
    text = body.decode("utf-8", "replace")
    out = []
    for h in HREF.findall(text):
        h = html.unescape(h).strip()
        if h.startswith(("mailto:", "tel:", "javascript:")):
            continue
        out.append(urllib.parse.urljoin(base, h))
    return out


class Survey:
    def __init__(self, out: str):
        self.out = out
        self.store = os.path.join(out, "bytes")
        os.makedirs(self.store, exist_ok=True)
        self.log = open(os.path.join(out, "survey.jsonl"), "a", encoding="utf-8")

    def get(self, url: str, host_state: dict, what: str):
        if host_state.get("blocked"):
            return None
        try:
            r = fg.open_url(url, timeout=40, positions_dir=POSITIONS, pacer=PACER, max_bytes=8 << 20)
        except fg.Refused as e:
            row = {"host": host_state["host"], "url": url, "what": what, "refused": str(e)[:300]}
            self.log.write(json.dumps(row) + "\n"); self.log.flush()
            return None
        except Exception as e:  # noqa: BLE001 — a transport failure is a failed read
            row = {"host": host_state["host"], "url": url, "what": what, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            self.log.write(json.dumps(row) + "\n"); self.log.flush()
            host_state.setdefault("errors", 0)
            host_state["errors"] += 1
            if host_state["errors"] >= 2:
                host_state["blocked"] = "two transport failures"
            return None
        sha = hashlib.sha256(r.body).hexdigest() if r.body else ""
        if sha:
            p = os.path.join(self.store, sha)
            if not os.path.exists(p):
                with open(p, "wb") as f:
                    f.write(r.body)
        row = {"host": host_state["host"], "url": url, "what": what, "status": r.status, "sha256": sha,
               "size": len(r.body), "blocked": r.blocked, "location": r.location}
        self.log.write(json.dumps(row) + "\n"); self.log.flush()
        if r.blocked:
            host_state["blocked"] = r.blocked
            return None
        return r

    def host(self, host: str) -> dict:
        st = {"host": host}
        base = f"https://www.{host}/" if host.count(".") <= 2 and not host.startswith("www.") else f"https://{host}/"
        home = self.get(base, st, "home")
        if home is None or home.status != 200:
            if home is not None and home.location:
                home = self.get(home.location, st, "home-redirect") if fg.host_of(home.location).endswith(host) else home
            if home is None or home.status != 200:
                bare = f"https://{host}/"
                if bare != base:
                    home = self.get(bare, st, "home-bare")
        if home is None or home.status != 200:
            st["home"] = "no answer"
            return st
        st["home"] = home.url
        root = f"{urllib.parse.urlsplit(home.url).scheme}://{urllib.parse.urlsplit(home.url).netloc}"
        found = set(links(home.body, home.url))
        st["terms"] = sorted({u for u in found if TERMS_WORDS.search(u) and fg.host_of(u).endswith(host)})[:4]
        rob = fg._ROBOTS.get(fg.host_of(home.url))
        maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rob.text) if rob and rob.text else []
        maps = maps or [root + "/sitemap.xml"]
        seen_maps = 0
        queue = list(maps[:3])
        while queue and seen_maps < MAX_CHILD_SITEMAPS:
            m = queue.pop(0)
            if not fg.host_of(m).endswith(host):
                continue
            r = self.get(m, st, "sitemap")
            seen_maps += 1
            if r is None or r.status != 200:
                continue
            locs = LOC.findall(r.body.decode("utf-8", "replace"))
            if b"<sitemapindex" in r.body[:2000]:
                kids = sorted(locs, key=lambda u: (0 if re.search(r"page|content|general", u, re.I) else 1))
                queue.extend(kids)
            else:
                found.update(locs)
        st["sitemap_urls"] = len(found)
        cands = sorted({u for u in found if rank(u) < 9 and fg.host_of(u).endswith(host)}, key=lambda u: (rank(u), len(u)))
        st["candidates"] = cands[:40]
        st["pages"] = []
        for u in [c for c in cands if rank(c) in (0, 1, 3)][:MAX_PAGES]:
            r = self.get(u, st, "page")
            if r is None:
                continue
            files = [l for l in links(r.body, u) if re.search(r"\.(pdf|xlsx?|docx?)(\?|$)", l, re.I)]
            st["pages"].append({"url": u, "status": r.status, "sha256": hashlib.sha256(r.body).hexdigest() if r.body else "",
                                "files": len(files), "returns_files": len([f for f in files if RETURNS_WORDS.search(f) or re.search(r"return", f, re.I)])})
        return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", default="")
    ap.add_argument("--verify", default="", help="a candidates file: council, terms, listing addresses")
    ap.add_argument("--councils", action="store_true", help="every host of the position but the collected ones")
    ap.add_argument("--out", default=os.path.join(SCRATCH, "survey"))
    a = ap.parse_args(argv)
    if a.verify:
        os.makedirs(a.out, exist_ok=True)
        verify(a.verify, a.out)
        return 0
    hosts = [h for h in a.hosts.split(",") if h] or hosts_of_position()
    if a.councils:
        hosts = [h for h in hosts if h not in COLLECTED]
    s = Survey(a.out)
    with open(os.path.join(a.out, "hosts.jsonl"), "a", encoding="utf-8") as f:
        for h in hosts:
            st = s.host(h)
            f.write(json.dumps(st) + "\n"); f.flush()
            best = [p for p in st.get("pages", []) if p["returns_files"]]
            print(f"{h}: home={'ok' if st.get('home') not in (None, 'no answer') else 'NO'} "
                  f"blocked={bool(st.get('blocked'))} sitemap_urls={st.get('sitemap_urls', 0)} "
                  f"cands={len(st.get('candidates', []))} pages_with_returns={len(best)}", flush=True)
    return 0



# ── the verification of the discovered pages (the survey's second half) ─────────

def verify(candidates: str, out: str) -> None:
    """For each line `council<TAB>terms or -<TAB>listing addresses`: the terms page (from the home page's own
    links when none is given), each listing page, and one level of the sub-listings a listing names, through the
    gate; the reading's counts by year. One line of JSON per council in `out/verify.jsonl`."""
    from registers.local_elections import read
    s = Survey(out)
    with open(candidates, encoding="utf-8") as f, open(os.path.join(out, "verify.jsonl"), "a", encoding="utf-8") as w:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            council, terms, urls = line.rstrip("\n").split("\t")
            urls = urls.split()
            host = fg.host_of(urls[0])
            st = {"host": host}
            rec = {"council": council, "terms": [], "pages": []}
            if terms == "-":
                home = s.get(f"https://{host}/", st, "home")
                if home is not None and home.status == 200:
                    terms_links = sorted({u for u in links(home.body, home.url)
                                          if TERMS_WORDS.search(u) and fg.host_of(u).endswith(host.replace("www.", ""))})
                    terms = " ".join(terms_links[:2])
            for t in (terms.split() if terms != "-" else []):
                r = s.get(t, st, "terms")
                rec["terms"].append({"url": t, "status": r.status if r else None,
                                     "sha256": hashlib.sha256(r.body).hexdigest() if r and r.body else ""})
            queue = [(u, 0) for u in urls]
            seen = set()
            while queue and len(seen) < 10:
                u, depth = queue.pop(0)
                if u in seen:
                    continue
                seen.add(u)
                r = s.get(u, st, "listing")
                p = {"url": u, "depth": depth, "status": r.status if r else None, "blocked": st.get("blocked", ""),
                     "location": r.location if r else ""}
                if r is not None and r.status == 200:
                    p["sha256"] = hashlib.sha256(r.body).hexdigest()
                    o = read.read_listing(r.body, u, council)
                    years = {}
                    for row in o["rows"]:
                        years[str(row["election_year"])] = years.get(str(row["election_year"]), 0) + 1
                    p.update(rows=len(o["rows"]), years=years, not_returns=o["not_returns"], follow=o["follow"][:8])
                    if depth == 0:
                        queue += [(x, 1) for x in o["follow"][:4]]
                rec["pages"].append(p)
            rec["blocked"] = st.get("blocked", "")
            w.write(json.dumps(rec, ensure_ascii=False) + "\n")
            w.flush()
            tot = sum(p.get("rows", 0) for p in rec["pages"])
            print(f"{council}: terms {len(rec['terms'])}, pages {len(rec['pages'])}, returns {tot}"
                  + (f", BLOCKED {rec['blocked'][:60]}" if rec["blocked"] else ""), flush=True)


if __name__ == "__main__":
    sys.exit(main())
