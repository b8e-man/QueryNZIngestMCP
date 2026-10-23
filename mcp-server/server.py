#!/usr/bin/env python3
"""Query NZ Ingest MCP — primitive operations over the government-publication corpora.

Design rules (IDEA-001):
- Primitives are MEASUREMENTS or RECORD RETURNS. Never conclusions.
- Every primitive declares its type in its docstring:
  READ (records -> records) / REDUCER (records -> statistics) / ROUTER (records -> named subset).
- Thresholds are first-class and auditable: every mint records what it excluded and why.
- Family B (integrity) signals ride alongside every content read: coverage, extraction
  yield, slot-fill, freshness. Silent loss is the failure mode this exists to prevent.

Transport: MCP Streamable HTTP on 127.0.0.1:8646/mcp (see corpora.yaml).
Metering: every tool call is appended to metering.jsonl (per-call, not per-seat).
"""

import hashlib
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone

import yaml
from mcp.server.mcpserver import MCPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "corpora.yaml")
METER_F = os.path.join(BASE, "metering.jsonl")
MINTED_F = os.path.join(BASE, "minted_corpora.jsonl")
MAX_RAW_INDEX = 20000        # cap raw-page bodies held in memory per docs corpus

TAG_RE = re.compile(r"<(script|style)[^>]*>[\s\S]*?</\1>|<[^>]+>", re.I)
WS_RE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    return WS_RE.sub(" ", TAG_RE.sub(" ", html)).strip()


def norm_date(v) -> str:
    if not v:
        return ""
    s = str(v).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else s[:10]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def meter(tool: str, params: dict, n_results: int, ms: float) -> None:
    """Per-call metering record. params are hashed, not stored raw."""
    rec = {
        "ts": now_iso(),
        "tool": tool,
        "params_sha": hashlib.sha256(
            json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16],
        "n_results": n_results,
        "ms": round(ms, 1),
    }
    try:
        with open(METER_F, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _resolve_page(pages_dir: str, rel: str):
    """Path conventions differ per corpus (bare relative vs pages/-prefixed)."""
    for cand in (os.path.join(pages_dir, rel),
                 os.path.join(os.path.dirname(pages_dir), rel),
                 os.path.join(pages_dir, os.path.basename(rel))):
        if os.path.exists(cand):
            return cand
    return None


class Corpus:
    """One mounted corpus with an in-memory index, reloaded on file mtime change."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.records = []          # [{id, date, title, text, raw}]
        self.captured = 0          # capture-registry denominator (docs corpora)
        self.indexed_raw = 0       # raw-page bodies included in search
        self.gap_reason = ""       # why indexed < captured, if so
        self.last_date = ""
        self.null_dates = 0
        self._mtimes = {}
        self._lock = threading.Lock()
        self.reload(force=True)

    def _stat(self) -> dict:
        out = {}
        for key in ("extracted_file", "captures_file", "record_file"):
            p = self.cfg.get(key)
            if p and os.path.exists(p):
                out[key] = os.path.getmtime(p)
        return out

    def reload(self, force: bool = False):
        if not force and self._stat() == self._mtimes:
            return
        with self._lock:
            self._mtimes = self._stat()
            self.records = []
            self.captured = 0
            self.indexed_raw = 0
            self.gap_reason = ""
            self.null_dates = 0
            if self.cfg.get("kind") == "docs":
                self._load_docs()
            else:
                self._load_records()
            self._finalize()

    def _load_jsonl(self, path: str):
        if not path or not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def _row_to_rec(self, row: dict, text: str):
        rid = str(row.get(self.cfg["id_field"]) or row.get("url")
                  or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16])
        return {
            "id": rid,
            "date": norm_date(row.get(self.cfg["date_field"])),
            "title": str(row.get(self.cfg.get("title_field", "")) or "")[:300],
            "text": text,
            "raw": row,
        }

    def _load_docs(self):
        pages = self.cfg.get("pages_dir")
        extracted = {}
        for row in self._load_jsonl(self.cfg.get("extracted_file")):
            status = row.get("status")
            if status is not None and status != "ok":
                continue        # challenged/failed capture rows are not records
            if (row.get("kind") and not row.get("body_text")
                    and not row.get("path")):
                continue        # bare registry row (manifest kind=...)
            parts = [str(row.get(k, "")) for k in ("title", "body_text", "html_title")]
            if not row.get("body_text") and row.get("path") and pages:
                fpath = _resolve_page(pages, row["path"])
                if fpath:
                    with open(fpath, encoding="utf-8", errors="replace") as fh:
                        parts.append(strip_html(fh.read()))
            text = WS_RE.sub(" ", " ".join(parts))
            rec = self._row_to_rec(row, text)
            extracted[rec["id"]] = rec
            if not rec["date"]:
                self.null_dates += 1
        self.records = list(extracted.values())

        # capture registry = coverage denominator (beehive: done.jsonl;
        # wayback: manifest rows) so un-captured-but-expected gaps stay visible
        cap_path = self.cfg.get("captures_file")
        pages = self.cfg.get("pages_dir")
        n_cap = 0
        raw_added = 0
        for row in self._load_jsonl(cap_path):
            ok = row.get("status") == "ok" or row.get("kind") == "doc"
            if not ok:
                continue
            n_cap += 1
            rid = str(row.get(self.cfg["id_field"]) or row.get("url") or "")
            if rid in extracted or not pages:
                continue
            fname = row.get("path") or ""
            if fname and raw_added < MAX_RAW_INDEX:
                fpath = _resolve_page(pages, fname)
                if fpath:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        body = strip_html(f.read())
                    self.records.append({"id": rid, "date": norm_date(row.get("fetched_at")),
                                         "title": str(row.get("html_title") or "")[:300],
                                         "text": body, "raw": row})
                    raw_added += 1
        self.captured = max(n_cap, len(self.records))
        self.indexed_raw = raw_added
        if len(self.records) < n_cap:
            self.gap_reason = (f"{n_cap - len(self.records)} captured docs not in search "
                               f"index (raw-index cap {MAX_RAW_INDEX})")

    def _load_records(self):
        for row in self._load_jsonl(self.cfg.get("record_file")):
            text = " ".join(str(v) for v in row.values() if isinstance(v, str))
            rec = self._row_to_rec(row, WS_RE.sub(" ", text))
            self.records.append(rec)
            if not rec["date"]:
                self.null_dates += 1
        self.captured = len(self.records)

    def _finalize(self):
        dates = [r["date"] for r in self.records if r["date"]]
        self.last_date = max(dates) if dates else ""
        self.words = sum(len(r["text"].split()) for r in self.records)


CFG = yaml.safe_load(open(CONFIG))
MEASURE_CFG = CFG.get("measure", {})
CORPORA = {n: Corpus(n, c) for n, c in CFG["corpora"].items()}

mcp = MCPServer(
    name="query-nz-ingest",
    version="0.1.0",
    instructions=("Primitive operations over NZ government-publication corpora. "
                  "Tools return records and measurements with provenance and integrity "
                  "signals. They never return conclusions."),
)


def _select_corpora(corpus: str | None):
    if corpus is None:
        return list(CORPORA), None
    if corpus.startswith("mint:"):
        return None, corpus[5:]
    if corpus in CORPORA:
        return [corpus], None
    return None, None


def _fresh(name: str) -> Corpus:
    CORPORA[name].reload()
    return CORPORA[name]


def _integrity(c: Corpus) -> dict:
    """Family B signals — returned with every content read."""
    n = len(c.records)
    return {
        "records": n,
        "captured": c.captured,
        "search_coverage": round(n / c.captured, 4) if c.captured else 1.0,
        "coverage_gap_reason": c.gap_reason,
        "null_date_rate": round(c.null_dates / n, 4) if n else 0.0,
        "last_record_date": c.last_date,
    }


def _provenance(name: str, rec: dict) -> dict:
    raw = rec.get("raw") or {}
    prov = {"corpus": name, "record_id": rec["id"]}
    for k in ("url", "snapshot_url", "sha256", "fetched_at", "source_file",
              "status", "bytes", "content_encoding"):
        if raw.get(k):
            prov[k] = raw[k]
    extraction = None
    if raw.get("body_text") and raw.get("extracted_at"):
        extraction = {"model": raw.get("model"), "extracted_at": raw.get("extracted_at"),
                      "topics": raw.get("topics"), "quotes": raw.get("quotes")}
    prov["extraction"] = extraction
    return prov


def _parse_ymd(s: str) -> str:
    return norm_date(s)


@mcp.tool()
def corpora() -> dict:
    """READ (control plane). Manifest of mounted corpora with integrity signals
    (coverage, extraction yield, slot-fill, freshness) plus minted corpora.
    Always read this first: it is the error bars for every other tool."""
    t0 = time.time()
    out = []
    for name in CFG["corpora"]:
        c = _fresh(name)
        cfg = c.cfg
        item = {
            "name": name,
            "label": cfg.get("label"),
            "source_category": cfg.get("source_category"),
            **_integrity(c),
        }
        if cfg.get("kind") == "docs" and cfg.get("extracted_file"):
            n_extracted = sum(1 for r in c.records
                              if (r.get("raw") or {}).get("extracted_at"))
            if n_extracted:
                item["extraction_yield"] = (round(n_extracted / c.captured, 4)
                                            if c.captured else 0.0)
                item["extracted_records"] = n_extracted
        age_h = None
        if c.last_date:
            try:
                dt = datetime.fromisoformat(c.last_date).replace(tzinfo=timezone.utc)
                age_h = round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)
            except ValueError:
                pass
        item["last_record_age_hours"] = age_h
        item["freshness_sla_hours"] = cfg.get("freshness_sla_hours")
        item["freshness_ok"] = (age_h is not None and cfg.get("freshness_sla_hours")
                                and age_h <= cfg["freshness_sla_hours"])
        out.append(item)
    minted = _load_minted()
    meter("corpora", {}, len(out), (time.time() - t0) * 1000)
    return {"corpora": out, "minted_corpora": minted,
            "note": "Measurements and records only — no conclusions are drawn."}


@mcp.tool()
def search(query: str, corpus: str | None = None, date_from: str | None = None,
           date_to: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    """READ (records -> records). Case-insensitive AND search over indexed text
    (title + body). Covers extracted AND raw-page bodies so un-extracted captures
    stay findable — never silently absent. Returns provenance with every hit and
    coverage numbers so the hit list carries its own error bars."""
    t0 = time.time()
    terms = [t.lower() for t in query.split() if t.strip()]
    hits = []
    scanned = 0
    indexed = 0
    names, mint = _select_corpora(corpus)
    if mint is not None:
        return _search_mint(mint, terms, date_from, date_to, limit, offset, t0)
    if names is None:
        meter("search", {"q": query, "corpus": corpus}, 0, (time.time() - t0) * 1000)
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    for name in names:
        c = _fresh(name)
        indexed += len(c.records)
        for rec in c.records:
            scanned += 1
            d = rec["date"]
            if date_from and d and d < _parse_ymd(date_from):
                continue
            if date_to and d and d > _parse_ymd(date_to):
                continue
            text_l = rec["text"].lower()
            if not all(t in text_l for t in terms):
                continue
            snippet = _snippet(rec["text"], terms[0])
            hits.append({
                "corpus": name,
                "record_id": rec["id"],
                "date": d or None,
                "title": rec["title"] or None,
                "snippet": snippet,
                "provenance": _provenance(name, rec),
            })
    total = len(hits)
    page = hits[offset:offset + max(1, min(limit, 100))]
    meter("search", {"q": query, "corpus": corpus, "from": date_from, "to": date_to},
          total, (time.time() - t0) * 1000)
    return {"hits": page, "total": total, "offset": offset, "limit": limit,
            "scanned_records": scanned, "indexed_records": indexed,
            "note": "Records with provenance — no relevance scoring or conclusions."}


def _snippet(text: str, term: str, width: int = 140) -> str:
    i = text.lower().find(term)
    if i < 0:
        return text[:width]
    a = max(0, i - width // 2)
    return text[a:a + width]


def _search_mint(name, terms, date_from, date_to, limit, offset, t0):
    mint = _load_minted(name)
    if not mint:
        meter("search", {"mint": name}, 0, (time.time() - t0) * 1000)
        return {"error": f"no minted corpus named {name!r}", "minted_corpora": _load_minted()}
    ids = set(mint.get("included_ids", []))
    hits = []
    for cname, idsel in mint.get("corpus_ids", {}).items():
        c = _fresh(cname)
        sel = set(idsel)
        for rec in c.records:
            if rec["id"] not in sel or rec["id"] not in ids:
                continue
            d = rec["date"]
            if date_from and d and d < _parse_ymd(date_from):
                continue
            if date_to and d and d > _parse_ymd(date_to):
                continue
            text_l = rec["text"].lower()
            if terms and not all(t in text_l for t in terms):
                continue
            hits.append({"corpus": cname, "record_id": rec["id"], "date": d or None,
                         "title": rec["title"] or None,
                         "snippet": _snippet(rec["text"], terms[0]) if terms else None,
                         "provenance": _provenance(cname, rec),
                         "minted_into": name})
    total = len(hits)
    page = hits[offset:offset + max(1, min(limit, 100))]
    meter("search", {"mint": name}, total, (time.time() - t0) * 1000)
    return {"hits": page, "total": total, "offset": offset, "limit": limit,
            "mint_definition": {k: mint[k] for k in ("name", "threshold", "measure_kind",
                                                     "keywords", "created_at")
                                if k in mint},
            "note": "Subset minted by threshold — see minted_corpora for exclusions."}


@mcp.tool()
def get(record_id: str, corpus: str | None = None) -> dict:
    """READ (record -> record). One record in full: text, provenance chain
    (source URL, capture, sha, snapshot), and extraction (model, topics, quotes)
    or extraction: null when not extracted. Never summarised — raw record."""
    t0 = time.time()
    names, _ = _select_corpora(corpus)
    if names is None:
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    for name in names:
        c = _fresh(name)
        for rec in c.records:
            if rec["id"] == record_id:
                out = {"corpus": name, "record": {k: rec["raw"].get(k)
                                                  for k in rec["raw"]},
                       "text": rec["text"], "provenance": _provenance(name, rec)}
                meter("get", {"id": record_id, "corpus": corpus}, 1,
                      (time.time() - t0) * 1000)
                return out
    meter("get", {"id": record_id, "corpus": corpus}, 0, (time.time() - t0) * 1000)
    return {"error": "not found", "record_id": record_id}


@mcp.tool()
def recent(since: str, corpus: str | None = None, limit: int = 50) -> dict:
    """READ (delta). Records with date >= since (ISO date). The intake-monitoring
    primitive: what has arrived in the corpus since a point in time."""
    t0 = time.time()
    since_d = _parse_ymd(since)
    names, _ = _select_corpora(corpus)
    if names is None:
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    hits = []
    for name in names:
        c = _fresh(name)
        for rec in c.records:
            if rec["date"] and rec["date"] >= since_d:
                hits.append({"corpus": name, "record_id": rec["id"], "date": rec["date"],
                             "title": rec["title"] or None,
                             "provenance": _provenance(name, rec)})
    hits.sort(key=lambda r: r["date"], reverse=True)
    meter("recent", {"since": since, "corpus": corpus}, len(hits),
          (time.time() - t0) * 1000)
    return {"records": hits[:max(1, min(limit, 500))], "total": len(hits),
            "since": since_d}


@mcp.tool()
def measure(keywords: list[str], corpora_filter: list[str] | None = None,
            measure_kind: str = "count", date_from: str | None = None,
            date_to: str | None = None,
            mint_name: str | None = None, mint_threshold: float | None = None) -> dict:
    """REDUCER (records -> statistics), optionally ROUTER (records -> named subset).
    Keyword x corpus matrix with three separable measures (IDEA-001 §3):
    count (raw), rate (per 10k words), salience (weighted log-odds with informative
    Dirichlet prior, z-scored). Every cell carries n_docs and a low_n flag —
    small corpora are annotated, never hidden. With mint_name + mint_threshold,
    records at/above the threshold (on the chosen measure) are minted into a named
    subset; the audit records every exclusion and its value."""
    t0 = time.time()
    if not keywords:
        return {"error": "no keywords"}
    if measure_kind not in ("count", "rate", "salience"):
        return {"error": "measure_kind must be count|rate|salience"}
    kws = [k.lower() for k in keywords]
    names = ([n for n in corpora_filter if n in CORPORA]
             if corpora_filter else list(CORPORA))
    stats = {}           # name -> per-kw counts + totals
    per_doc = {}         # name -> id -> per-kw counts (for mint audit)
    global_counts = {k: 0 for k in kws}
    global_words = 0
    for name in names:
        c = _fresh(name)
        dmap = {k: 0 for k in kws}
        docs = {}
        words = 0
        n_docs = 0
        for rec in c.records:
            d = rec["date"]
            if date_from and d and d < _parse_ymd(date_from):
                continue
            if date_to and d and d > _parse_ymd(date_to):
                continue
            text_l = rec["text"].lower()
            hits = {}
            for k in kws:
                n = text_l.count(k)
                if n:
                    dmap[k] += n
                    hits[k] = n
            if hits:
                docs[rec["id"]] = {"hits": hits,
                                   "words": len(rec["text"].split())}
            words += len(rec["text"].split())
            n_docs += 1
        stats[name] = {"counts": dmap, "words": words, "n_docs": n_docs}
        per_doc[name] = docs
        for k in kws:
            global_counts[k] += dmap[k]
        global_words += words

    cells = []
    rate_per = float(MEASURE_CFG.get("rate_per", 10000))
    prior = float(MEASURE_CFG.get("prior_strength", 200.0))
    low_n = int(MEASURE_CFG.get("low_n_docs", 5))
    weights = MEASURE_CFG.get("source_weights") or {}
    for name in names:
        st = stats[name]
        for k in kws:
            y = st["counts"][k]
            n = max(st["words"], 1)
            cell = {
                "keyword": k,
                "corpus": name,
                "count": y,
                "corpus_words": st["words"],
                "n_docs": st["n_docs"],
                "rate_per_10k": round(y / n * rate_per, 3),
                "low_n": st["n_docs"] < low_n,
            }
            if measure_kind == "salience":
                y_rest = global_counts[k] - y
                n_rest = max(global_words - st["words"], 1)
                aw = prior * ((global_counts[k] + 0.5) / (global_words + 1.0))
                lo = (math.log((y + aw) / (n + prior - y - aw))
                      - math.log((y_rest + aw) / (n_rest + prior - y_rest - aw)))
                var = 1.0 / (y + aw) + 1.0 / (y_rest + aw)
                cell["salience"] = round(lo, 4)
                cell["z"] = round(lo / math.sqrt(var), 3)
            w = weights.get(name)
            if w:
                cell["judgement_weight"] = w
                cell["weighted_" + measure_kind] = round(
                    cell.get({"count": "count", "rate": "rate_per_10k",
                              "salience": "salience"}[measure_kind], 0) * float(w), 4)
            cells.append(cell)

    out = {"cells": cells, "measure_kind": measure_kind,
           "prior_strength": prior if measure_kind == "salience" else None,
           "rate_per": rate_per,
           "note": ("Cells carry n_docs and low_n flags. Salience = weighted log-odds "
                    "vs the rest (Monroe et al. 2008). Judgement weights are human-set, "
                    "not derivable.")}
    if mint_name is not None and mint_threshold is not None:
        if measure_kind == "salience":
            out["mint"] = {"error": "salience is corpus-level; mint on count or rate"}
        else:
            out["mint"] = _mint(mint_name, kws, measure_kind, float(mint_threshold),
                                per_doc, stats, names, t0)
    meter("measure", {"keywords": kws, "kind": measure_kind, "corpora": names},
          len(cells), (time.time() - t0) * 1000)
    return out


def _mint(name, kws, measure_kind, threshold, per_doc, stats, names, t0):
    """Router: mint a named subset. Records EVERY disposition (included/excluded
    with the doc's value and the threshold) — thresholds never drop silently."""
    rate_per = float(MEASURE_CFG.get("rate_per", 10000))
    included, excluded = [], []
    corpus_ids = {}
    for cname in names:
        st = stats[cname]
        sel = []
        for rid, entry in per_doc[cname].items():
            value = sum(entry["hits"].values())
            if measure_kind == "rate":
                value = value / max(entry["words"], 1) * rate_per
            entry = {"record_id": rid, "value": round(float(value), 3)}
            if value >= threshold:
                included.append(rid)
                sel.append(rid)
            else:
                entry["reason"] = f"value {value:.3f} < threshold {threshold}"
                excluded.append(entry)
        corpus_ids[cname] = sel
    mint_rec = {
        "name": name,
        "created_at": now_iso(),
        "keywords": kws,
        "measure_kind": measure_kind,
        "threshold": threshold,
        "included_ids": included,
        "corpus_ids": corpus_ids,
        "excluded": excluded[:2000],
        "excluded_total": len(excluded),
        "excluded_recorded": min(len(excluded), 2000),
    }
    with open(MINTED_F, "a") as f:
        f.write(json.dumps(mint_rec, ensure_ascii=False) + "\n")
    return {"name": name, "included": len(included), "excluded": len(excluded),
            "excluded_audit_truncated": len(excluded) > 2000,
            "searchable_as": f"mint:{name}"}


def _load_minted(name: str | None = None):
    if not os.path.exists(MINTED_F):
        return [] if name is None else None
    out = []
    with open(MINTED_F, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if name is not None:
                if r.get("name") == name:
                    return r
            else:
                out.append({"name": r.get("name"), "created_at": r.get("created_at"),
                            "keywords": r.get("keywords"),
                            "measure_kind": r.get("measure_kind"),
                            "threshold": r.get("threshold"),
                            "included": len(r.get("included_ids", [])),
                            "excluded_total": r.get("excluded_total")})
    return out if name is None else None


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "corpora": len(CORPORA), "ts": now_iso()})


if __name__ == "__main__":
    srv = CFG.get("server", {})
    mcp.run(transport="streamable-http", host=srv.get("host", "127.0.0.1"),
            port=int(srv.get("port", 8646)),
            streamable_http_path=srv.get("streamable_http_path", "/mcp"))
