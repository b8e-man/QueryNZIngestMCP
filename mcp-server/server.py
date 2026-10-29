#!/usr/bin/env python3
"""Query NZ Ingest MCP — the contents of the corpora, nothing else.

Design rules:
- The server reports WHAT the database holds: records, counts, date ranges,
  freshness, statistics — and per-record capture provenance (as-received
  hash, fetch time, HTTP status). Model-made fields carry an `annotation`
  block naming them and their generator; `updated_at` moves when a record
  is re-processed.
- Consumers are expected to ingest the ENTIRE corpus through this interface.
  `records` paginates in stable arrival order with a resumable cursor — the
  bulk-ingestion path.
- Fresh records land at the end of that order. `corpora()` reports counts and
  recent-arrival counts, so a consumer always knows when there is new data
  to pull; `records(cursor=...)` delivers it.
- Statistics are measurements with error bars (n_docs, low_n flags), never
  conclusions.

Transport: MCP Streamable HTTP on 0.0.0.0:8646/mcp (see corpora.yaml).
Metering: every tool call is appended to metering.jsonl (per-call).
"""

import bisect
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import yaml
from mcp.server.mcpserver import MCPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "corpora.yaml")
METER_F = os.path.join(BASE, "metering.jsonl")
MINTED_F = os.path.join(BASE, "minted_corpora.jsonl")
RAW_INDEX_CAP = 120000       # safety ceiling only; never reached (queue < 70k)

TAG_RE = re.compile(r"<(script|style)[^>]*>[\s\S]*?</\1>|<[^>]+>", re.I)
WS_RE = re.compile(r"\s+")

# Model-made fields — flagged in a per-record `annotation` block so consumers
# store them as annotation, never as fact (regex-derived fields are not
# flagged). Ruling: capture provenance and processing metadata are EXPOSED.
ANNOTATION_FIELDS = {"topics", "quotes"}

# Capture-provenance keys gathered into a uniform `capture` block (rows that
# have no separate capture layer — API/aggregator corpora — carry whatever
# of this they recorded; key names are never invented).
CAPTURE_KEYS = ("url", "final_url", "source_url", "snapshot_url",
                "fetched_at", "fetched", "_collected", "http_status",
                "status", "sha256", "raw_file", "path", "source_file",
                "bytes", "ts")


# Field names that hold the database's text bodies (dropped from
# include_text=false responses; long strings are dropped by heuristic too).
TEXT_FIELD_KEYS = {"text", "body_text", "body", "content", "html",
                   "questionText", "answerText"}


def strip_html(html: str) -> str:
    return WS_RE.sub(" ", TAG_RE.sub(" ", html)).strip()


def norm_date(v) -> str:
    if not v:
        return ""
    s = str(v).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    if re.match(r"^\d{8,14}$", s):        # wayback ts: 20060902092214
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def meter(tool: str, params: dict, n_results: int, ms: float) -> None:
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
    for cand in (os.path.join(pages_dir, rel),
                 os.path.join(os.path.dirname(pages_dir), rel),
                 os.path.join(pages_dir, os.path.basename(rel))):
        if os.path.exists(cand):
            return cand
    return None


class Corpus:
    """One mounted corpus, indexed in stable ARRIVAL order.

    Arrival order comes from the append-only capture/registry file (or the
    record file itself): a record's position never changes once assigned, and
    new records always land at the end. That makes `records(cursor=N)` a
    correct incremental-ingestion feed.
    """

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.records = []          # [{seq, id, date, title, text, fields, arrived}]
        self._by_id = {}           # id -> record (in self.records)
        self._content = {}         # id -> record built by the extracted pass
        self._seen = set()         # ids in self.records
        self._offs = {}            # file -> byte offset consumed
        self._src = {}             # file -> (size, mtime) at last read
        self._gen = 0              # bumped whenever the index changes
        self._fresh_cache = None
        self._lock = threading.Lock()
        self.reload(force=True)

    def _files(self):
        return [p for p in (self.cfg.get("extracted_file"),
                            self.cfg.get("captures_file"),
                            self.cfg.get("record_file")) if p]

    def _needs_rebuild(self) -> bool:
        for p in self._files():
            try:
                st = os.stat(p)
            except OSError:
                continue
            prev = self._src.get(p)
            if prev is None:
                return True                      # newly appeared file
            psize, pmtime = prev
            if st.st_size < psize or (st.st_size == psize
                                      and st.st_mtime != pmtime):
                return True                      # rewritten / truncated
        return False

    def _has_new_bytes(self) -> bool:
        for p in self._files():
            try:
                if os.path.getsize(p) != self._offs.get(p, 0):
                    return True
            except OSError:
                continue
        return False

    def _reset(self):
        self.records = []
        self._by_id = {}
        self._content = {}
        self._seen = set()
        self._offs = {}

    def reload(self, force: bool = False):
        with self._lock:
            if not force and not self._needs_rebuild() \
                    and not self._has_new_bytes():
                return
            if self._needs_rebuild():
                self._reset()
            if self.cfg.get("kind") == "docs":
                self._load_docs()
            else:
                self._load_records()
            self._gen += 1
            self._fresh_cache = None

    def _read_new(self, path):
        """Rows appended to an append-only JSONL file since the last read."""
        if not path or not os.path.exists(path):
            return
        try:
            st = os.stat(path)
        except OSError:
            return
        off = self._offs.get(path, 0)
        self._src[path] = (st.st_size, st.st_mtime)
        if st.st_size <= off:
            return
        with open(path, "rb") as f:
            f.seek(off)
            data = f.read()
        cut = data.rfind(b"\n")
        if cut < 0:                              # incomplete trailing line
            return
        self._offs[path] = off + cut + 1
        for line in data[:cut + 1].split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue

    def _row_to_rec(self, row: dict, text: str, arrived: str = "") -> dict:
        rid = str(row.get(self.cfg["id_field"]) or row.get("url")
                  or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16])
        tf = self.cfg.get("title_field", "")
        tfs = tf if isinstance(tf, list) else [tf]
        title = next((str(row[k]) for k in tfs if k and row.get(k)), "")
        rec = {
            "id": rid,
            "date": norm_date(row.get(self.cfg["date_field"])),
            "title": title[:300],
            "text": text,
            "fields": dict(row),
            "arrived": arrived or str(row.get("fetched_at")
                                      or row.get("_fetched_at")
                                      or row.get("_collected")
                                      or row.get("fetched") or ""),
            # when this version of the record landed (source-provided stamps)
            "updated_at": str(row.get("extracted_at") or row.get("fetched_at")
                              or row.get("_collected") or row.get("fetched")
                              or row.get("lastModified") or ""),
        }
        ann = sorted(k for k in ANNOTATION_FIELDS if row.get(k))
        if ann and row.get("model"):
            rec["annotation"] = {"fields": ann,
                                 "generator": str(row.get("model")),
                                 "created_at": str(row.get("extracted_at") or "")}
        cap = {k: row[k] for k in CAPTURE_KEYS
               if k in row and row[k] not in (None, "")}
        if cap:
            rec["capture"] = cap
        proot = self.cfg.get("path_root")
        if proot and row.get("path"):
            # resolution aid only — the raw `path` stays as-received in fields/capture
            rec["file"] = os.path.join(proot, str(row["path"]).lstrip("/"))
        return rec

    def _append(self, rec: dict) -> dict:
        rec["seq"] = len(self.records)
        self.records.append(rec)
        self._by_id[rec["id"]] = rec
        self._seen.add(rec["id"])
        return rec

    def _update(self, rec: dict, row: dict):
        old = self._by_id[rec["id"]]
        old["date"], old["title"] = rec["date"], rec["title"]
        old["text"], old["fields"] = rec["text"], rec["fields"]
        old["updated_at"] = rec.get("updated_at") or now_iso()
        if rec.get("annotation"):
            old["annotation"] = rec["annotation"]
        old.pop("_words", None)
        if rec.get("arrived"):
            old["arrived"] = rec["arrived"]
        if rec.get("file"):
            old["file"] = rec["file"]

    def _load_docs(self):
        pages = self.cfg.get("pages_dir")
        raw_loaded = [0]          # page files read this reload (safety ceiling)

        def raw_text(row):
            parts = [str(row.get("title") or row.get("html_title") or "")]
            if row.get("path") and pages and raw_loaded[0] < RAW_INDEX_CAP:
                fpath = _resolve_page(pages, row["path"])
                if fpath:
                    with open(fpath, encoding="utf-8", errors="replace") as fh:
                        parts.append(strip_html(fh.read()))
                    raw_loaded[0] += 1
            return WS_RE.sub(" ", " ".join(parts))

        ext_path = self.cfg.get("extracted_file")
        cap_path = self.cfg.get("captures_file") or ext_path
        ext_rows = list(self._read_new(ext_path)) if ext_path else []
        if cap_path == ext_path:
            cap_rows = list(ext_rows)            # one file backs both passes
        else:
            cap_rows = list(self._read_new(cap_path)) if cap_path else []

        staged = {}                              # id -> rec, awaiting position
        for row in ext_rows:                     # pass 1: extracted (enrichment)
            status = row.get("status")
            if status is not None and status != "ok":
                continue
            if (row.get("kind") and not row.get("body_text")
                    and not row.get("path")):
                continue
            parts = [str(row.get(k, "")) for k in ("title", "body_text",
                                                   "html_title")]
            if not row.get("body_text") and row.get("path") and pages:
                fpath = _resolve_page(pages, row["path"])
                if fpath:
                    with open(fpath, encoding="utf-8", errors="replace") as fh:
                        parts.append(strip_html(fh.read()))
            rec = self._row_to_rec(row, WS_RE.sub(" ", " ".join(parts)))
            if rec["id"] in self._by_id:         # late extraction: enrich in
                self._update(rec, row)           # place, position never moves
            else:
                staged[rec["id"]] = rec

        for row in cap_rows:                     # pass 2: captures (arrival)
            st, kind = row.get("status"), row.get("kind")
            if st is not None and st != "ok":
                continue
            if kind in ("attempt", "cdx-failed"):
                continue
            rid = str(row.get(self.cfg["id_field"]) or row.get("url") or "")
            if not rid:
                continue
            if rid in self._by_id:
                old = self._by_id[rid]
                if row.get("fetched_at"):
                    old["arrived"] = row["fetched_at"]
                old["capture"] = dict(row)
                continue
            rec = staged.pop(rid, None)
            if rec is None:
                rec = self._row_to_rec(row, raw_text(row))
            if row.get("fetched_at"):
                rec["arrived"] = row["fetched_at"]
            rec["capture"] = dict(row)   # provenance: as-received, unfaked
            self._append(rec)

        for rec in staged.values():              # pass 3: extracted-only tail
            self._append(rec)

    def _load_records(self):
        path = self.cfg.get("record_file")
        for row in self._read_new(path):
            raw = row.get("text")
            # rows that already carry a text field reuse it as the search
            # text (same object — no duplicate of a 300KB body in RAM)
            if isinstance(raw, str):
                text = raw
            else:
                text = " ".join(str(v) for v in row.values()
                                if isinstance(v, str))
            rec = self._row_to_rec(row, text)
            if rec["id"] in self._by_id:
                continue                 # duplicate id: first record wins
            self._append(rec)

    # -- freshness (data-about-the-data, computed from internal timestamps) --
    def freshness(self) -> dict:
        if self._fresh_cache is None or self._fresh_cache[0] != self._gen:
            arr = sorted(r["arrived"] for r in self.records if r.get("arrived"))
            dates = sorted(r["date"] for r in self.records if r["date"])
            self._fresh_cache = (self._gen, arr, dates)
        _, arr, dates = self._fresh_cache
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(
            timespec="seconds")
        return {
            "records": len(self.records),
            "ingest_cursor": len(self.records),
            "date_from": dates[0] if dates else None,
            "date_to": dates[-1] if dates else None,
            "arrivals_last_24h": len(arr) - bisect.bisect_right(arr, cutoff),
            "newest_arrival": arr[-1] if arr else None,
        }


CFG = yaml.safe_load(open(CONFIG))
MEASURE_CFG = CFG.get("measure", {})
CORPORA = {}
for _n, _c in CFG["corpora"].items():
    CORPORA[_n] = Corpus(_n, _c)
    import gc
    gc.collect()          # big corpora: free parse transients before the next

mcp = MCPServer(
    name="query-nz-ingest",
    version="0.2.0",
    instructions=("The contents of NZ government-publication corpora: records, "
                  "counts, date ranges, freshness and statistics. Consumers may "
                  "ingest the full corpus through the `records` tool (stable arrival "
                  "order, resumable cursor; new records land at the end). Each record "
                  "carries capture provenance (as-received hash, fetch time, HTTP "
                  "status); model-made fields are named in an `annotation` block; "
                  "`updated_at` moves when a record changes."))


def _fresh(name: str) -> Corpus:
    CORPORA[name].reload()
    return CORPORA[name]


def _rec_out(r: dict, include_text: bool = True) -> dict:
    out = {"seq": r["seq"], "id": r["id"], **r["fields"]}
    if r["date"] and "date" not in out:
        out["date"] = r["date"]
    if r.get("updated_at"):
        out["updated_at"] = r["updated_at"]
    if r.get("capture"):
        out["capture"] = r["capture"]
    if r.get("file"):
        out["file"] = r["file"]
    if r.get("annotation"):
        out["annotation"] = r["annotation"]
    if include_text:
        out["text"] = r["fields"].get("text") or r["text"]
        return out
    # metadata-only pass: the database's texts stay behind
    for k in list(out):
        v = out[k]
        if k in TEXT_FIELD_KEYS or (isinstance(v, str) and len(v) > 300):
            del out[k]
    return out


def _parse_ymd(s: str) -> str:
    return norm_date(s)


@mcp.tool()
def corpora() -> dict:
    """READ (inventory). What the database holds, per corpus: record count,
    date range, the ingestion cursor (= record count; records are appended in
    stable arrival order), and freshness — how many records landed in the last
    24 hours and when the newest arrived. Read this first; poll it to detect
    fresh records, then pull them with `records`."""
    t0 = time.time()
    out = []
    for name in CFG["corpora"]:
        c = _fresh(name)
        item = {"name": name,
                "label": c.cfg.get("label"),
                "source_category": c.cfg.get("source_category")}
        item.update(c.freshness())
        out.append(item)
    meter("corpora", {}, len(out), (time.time() - t0) * 1000)
    return {"corpora": out,
            "note": "Counts and freshness only. Pull records with `records`."}


@mcp.tool()
def records(corpus: str, cursor: int = 0, limit: int = 50,
            include_text: bool = True, doc_type: str | None = None) -> dict:
    """READ (bulk ingestion). The corpus in stable arrival order, paginated.
    `cursor` is the number of records already ingested (0 = start); each
    response returns the next batch and `next_cursor`. When `next_cursor`
    equals `ingest_cursor` from `corpora()`, the consumer has everything —
    poll `corpora()` for fresh arrivals, then call again with the saved
    cursor to pull only what landed since. Record fields are the database's
    own; each carries capture provenance and, where fields are model-made,
    an annotation block. Set include_text=false for a metadata-only pass.
    `doc_type` filters to one document type (e.g. judgment_pdf,
    media_release) on corpora that declare a doc_type_field; the cursor
    then counts positions within the filtered set."""
    t0 = time.time()
    if corpus not in CORPORA:
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    c = _fresh(corpus)
    cursor = max(0, int(cursor))
    lim = max(1, min(int(limit), 200))
    sel = c.records
    if doc_type:
        dtf = c.cfg.get("doc_type_field")
        if not dtf:
            return {"error": f"corpus {corpus!r} declares no doc_type_field",
                    "corpus": corpus}
        sel = [r for r in c.records if r["fields"].get(dtf) == doc_type]
    batch = sel[cursor:cursor + lim]
    out = [_rec_out(r, include_text) for r in batch]
    meter("records", {"corpus": corpus, "cursor": cursor, "doc_type": doc_type},
          len(out), (time.time() - t0) * 1000)
    return {"corpus": corpus, "total": len(sel), "doc_type": doc_type,
            "cursor": cursor, "next_cursor": cursor + len(out),
            "records": out}


@mcp.tool()
def changes(corpus: str, since: str, cursor: int = 0, limit: int = 100,
            include_text: bool = True) -> dict:
    """READ (change feed). Everything that moved after `since` — fresh
    arrivals AND records whose `updated_at` moved (re-processing) — in
    (updated_at, seq) order, paginated like `records`. `since` is an ISO
    stamp taken from a previous response's updated_at. Page with
    `next_cursor` until empty, then poll again with the newest updated_at
    seen as the next `since`."""
    t0 = time.time()
    if corpus not in CORPORA:
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    c = _fresh(corpus)
    lim = max(1, min(int(limit), 200))
    cursor = max(0, int(cursor))
    sel = sorted((r for r in c.records if r["updated_at"] > since),
                 key=lambda r: (r["updated_at"], r["seq"]))
    page = sel[cursor:cursor + lim]
    out = [_rec_out(r, include_text) for r in page]
    meter("changes", {"corpus": corpus}, len(out), (time.time() - t0) * 1000)
    return {"corpus": corpus, "since": since, "total": len(sel),
            "cursor": cursor, "next_cursor": cursor + len(out),
            "records": out}


@mcp.tool()
def search(query: str, corpus: str | None = None, date_from: str | None = None,
           date_to: str | None = None, limit: int = 20, offset: int = 0,
           doc_type: str | None = None) -> dict:
    """READ (find). Case-insensitive AND search over record text across one
    corpus or all. Empty query browses (use the date filters). Returns
    matching records with a text snippet — summaries of the data, not of
    anything else. `doc_type` restricts to one document type (e.g.
    judgment_pdf, media_release); corpora without a doc_type_field are
    skipped when it is set."""
    t0 = time.time()
    terms = [t.lower() for t in query.split() if t.strip()]
    if corpus is not None and corpus not in CORPORA and not corpus.startswith("mint:"):
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    if corpus is not None and corpus.startswith("mint:"):
        res = _search_mint(corpus[5:], terms, date_from, date_to, limit, offset, t0)
        return res
    hits = []
    rxs = [re.compile(re.escape(t), re.I) for t in terms]
    names = [corpus] if corpus else list(CORPORA)
    for name in names:
        c = _fresh(name)
        dtf = c.cfg.get("doc_type_field") if doc_type else None
        for rec in c.records:
            if doc_type and (not dtf or rec["fields"].get(dtf) != doc_type):
                continue
            d = rec["date"]
            if date_from and d and d < _parse_ymd(date_from):
                continue
            if date_to and d and d > _parse_ymd(date_to):
                continue
            if not all(rx.search(rec["text"]) for rx in rxs):
                continue
            hits.append({"corpus": name, "seq": rec["seq"], "id": rec["id"],
                         "date": d or None, "title": rec["title"] or None,
                         "snippet": _snippet(rec["text"], terms[0]) if terms else None})
    total = len(hits)
    page = hits[offset:offset + max(1, min(limit, 100))]
    meter("search", {"q": query, "corpus": corpus}, total, (time.time() - t0) * 1000)
    return {"hits": page, "total": total, "offset": offset, "limit": limit}


def _snippet(text: str, term: str, width: int = 140) -> str:
    i = text.lower().find(term)
    if i < 0:
        return text[:width]
    a = max(0, i - width // 2)
    return text[a:a + width]


def _search_mint(name, terms, date_from, date_to, limit, offset, t0):
    mint = _load_minted(name)
    if not mint:
        return {"error": f"no minted subset named {name!r}", "minted_subsets": _load_minted()}
    ids = set(mint.get("included_ids", []))
    hits = []
    rxs = [re.compile(re.escape(t), re.I) for t in terms]
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
            if not all(rx.search(rec["text"]) for rx in rxs):
                continue
            hits.append({"corpus": cname, "seq": rec["seq"], "id": rec["id"],
                         "date": d or None, "title": rec["title"] or None,
                         "snippet": _snippet(rec["text"], terms[0]) if terms else None,
                         "subset": name})
    total = len(hits)
    page = hits[offset:offset + max(1, min(limit, 100))]
    meter("search", {"mint": name}, total, (time.time() - t0) * 1000)
    return {"hits": page, "total": total, "offset": offset, "limit": limit,
            "subset_definition": {k: mint[k] for k in ("name", "threshold",
                                                       "measure_kind", "keywords",
                                                       "created_at") if k in mint}}


@mcp.tool()
def get(record_id: str, corpus: str | None = None) -> dict:
    """READ (detail). One record in full — the database's own fields and text,
    nothing else."""
    t0 = time.time()
    if corpus is not None and corpus not in CORPORA:
        return {"error": f"unknown corpus {corpus!r}", "available": list(CORPORA)}
    names = [corpus] if corpus else list(CORPORA)
    for name in names:
        c = _fresh(name)
        for rec in c.records:
            if rec["id"] == record_id:
                meter("get", {"id": record_id, "corpus": corpus}, 1,
                      (time.time() - t0) * 1000)
                return {"corpus": name, **_rec_out(rec, include_text=True)}
    meter("get", {"id": record_id, "corpus": corpus}, 0, (time.time() - t0) * 1000)
    return {"error": "not found", "record_id": record_id}


@mcp.tool()
def measure(keywords: list[str], corpora_filter: list[str] | None = None,
            measure_kind: str = "count", date_from: str | None = None,
            date_to: str | None = None,
            mint_name: str | None = None, mint_threshold: float | None = None) -> dict:
    """REDUCER (statistics), optionally ROUTER (named subset).
    Keyword x corpus matrix with three separable measures:
    count (raw), rate (per 10k words), salience (weighted log-odds with
    informative Dirichlet prior, z-scored). Every cell carries n_docs and a
    low_n flag — small corpora are annotated, never hidden. With mint_name +
    mint_threshold, records at/above the threshold (on count or rate) are
    gathered into a named subset, searchable as corpus='mint:<name>'; every
    exclusion is recorded with its value and the threshold it failed."""
    t0 = time.time()
    if not keywords:
        return {"error": "no keywords"}
    if measure_kind not in ("count", "rate", "salience"):
        return {"error": "measure_kind must be count|rate|salience"}
    kws = [k.lower() for k in keywords]
    kws_rx = [re.compile(re.escape(k), re.I) for k in kws]
    names = ([n for n in corpora_filter if n in CORPORA]
             if corpora_filter else list(CORPORA))
    stats = {}
    per_doc = {}
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
            w = rec.get("_words")
            if w is None:
                w = len(rec["text"].split())
                rec["_words"] = w
            hits = {}
            for rx, k in zip(kws_rx, kws):
                n = sum(1 for _ in rx.finditer(rec["text"]))
                if n:
                    dmap[k] += n
                    hits[k] = n
            if hits:
                docs[rec["id"]] = {"hits": hits, "words": w}
            words += w
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
           "note": ("Cells carry n_docs and low_n flags. Salience = weighted "
                    "log-odds vs the rest of the selected corpora.")}
    if mint_name is not None and mint_threshold is not None:
        if measure_kind == "salience":
            out["mint"] = {"error": "salience is corpus-level; mint on count or rate"}
        else:
            out["mint"] = _mint(mint_name, kws, measure_kind, float(mint_threshold),
                                per_doc, stats, names)
    meter("measure", {"keywords": kws, "kind": measure_kind, "corpora": names},
          len(cells), (time.time() - t0) * 1000)
    return out


def _mint(name, kws, measure_kind, threshold, per_doc, stats, names):
    """Router: mint a named subset. Records EVERY disposition (included vs
    excluded with the record's value and the threshold) — thresholds never
    drop records silently."""
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
            if value >= threshold:
                included.append(rid)
                sel.append(rid)
            else:
                excluded.append({"record_id": rid, "value": round(float(value), 3),
                                 "reason": f"value {value:.3f} < threshold {threshold}"})
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


# -- gaps: completeness measurement (courts corpus vs the NZLII index) -----
GAPS_CFG = CFG.get("gaps", {})
GAP_CITE_RE = re.compile(r"(19|20)(\d{2})[-_]?(NZ[A-Za-z]{2,8})[-_](\d{1,4})(?!\d)")


def _gap_key(series, year, num):
    """Canonical (SERIES, year, num) triple — uppercased series, unpadded
    num (NZLII's index carries '043' and '43' as duplicate URL variants)."""
    return (series.upper(), int(year), str(int(num)))


def _gap_ids_from_files(files):
    ids = set()
    for path in files:
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                for field in ("url", "path", "case_name", "case_slug"):
                    s = urllib.parse.unquote(str(row.get(field) or ""))
                    for m in GAP_CITE_RE.finditer(s):
                        ids.add(_gap_key(m.group(3), m.group(1) + m.group(2),
                                         m.group(4)))
    return ids


@mcp.tool()
def gaps(series: str | None = None, sample: int = 15) -> dict:
    """MEASUREMENT (completeness, courts corpus). Per-series gap analysis
    against the NZLII comparison index — NZLII is used as a COMPARISON
    source only (case IDs as metadata, never content). For each series:
    ids in the comparison index, ids in our own corpus index (filenames/
    URLs/case names), the difference, and how much of the difference has
    been PROBED against the official source (not_on_courtsofnz = verified
    absent from the open official site — the JDO back-catalogue evidence).
    Pass `series` (e.g. 'NZHC') for one series. Numbers are measurements
    with their methodology and caveats attached, not conclusions."""
    t0 = time.time()
    nzlii = set()
    nz_path = GAPS_CFG.get("nzlii_ids_file")
    if nz_path and os.path.exists(nz_path):
        with open(nz_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    nzlii.add(_gap_key(r["series"], r["year"], r["num"]))
                except (ValueError, KeyError):
                    continue
    else:
        return {"error": "comparison index not available",
                "nzlii_ids_file": nz_path}
    ours = _gap_ids_from_files(GAPS_CFG.get("corpus_index_files", []))

    not_on = set()          # (series, year, num) probed & absent officially
    probe_rows = 0
    pp = GAPS_CFG.get("probe_results_file")
    if pp and os.path.exists(pp):
        with open(pp, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    not_on.add(_gap_key(r["series"], r["year"], r["num"]))
                    probe_rows += 1
                except (ValueError, KeyError):
                    continue

    series_sel = {series.upper()} if series else None
    per_series = {}
    for s in sorted({k[0] for k in nzlii | ours}):
        if series_sel and s not in series_sel:
            continue
        nz = {k for k in nzlii if k[0] == s}
        our = {k for k in ours if k[0] == s}
        missing = nz - our
        miss_no = missing & not_on
        per_series[s] = {
            "comparison_index_ids": len(nz),
            "corpus_index_ids": len(our),
            "missing_from_corpus": len(missing),
            "not_on_courtsofnz": len(miss_no),
            "missing_unprobed": len(missing - not_on),
            "ours_only": len(our - nz),
            "missing_sample": [f"[{y}] {s} {n}" for s_, y, n in
                               sorted(missing, key=lambda k: (-k[1], int(k[2])))
                              ][:sample],
        }
    meter("gaps", {"series": series}, len(per_series),
          (time.time() - t0) * 1000)
    return {
        "comparison_source": GAPS_CFG.get("comparison_source"),
        "series": per_series,
        "methodology": {
            "id_mapping": "NZLII URL number == neutral citation "
                          "(verified vs Wayback replay case titles)",
            "corpus_ids_from": "our own filenames/URLs/case names "
                               "(regex-derived, no content used)",
            "not_on_courtsofnz": f"{probe_rows} probe results — cases probed "
                                 "live against the official source (HEAD) "
                                 "and absent; JDO back-catalogue evidence",
        },
        "caveats": [
            "comparison index is Wayback-CDX-derived: both sides carry "
            "Wayback coverage gaps (sparse for very recent cases)",
            "NZLII allocates its own numbers for unreported decisions "
            "(5-digit NZDC-style IDs are not neutral citations)",
            "series whose official filenames carry no citation (coroners, "
            "parts of NZEnvC) match at count level only",
        ],
        "note": "Measurements with their gaps, not conclusions. "
                "Content capture is from official sources only; NZLII "
                "supplies comparison IDs.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "corpora": len(CORPORA), "ts": now_iso()})


if __name__ == "__main__":
    srv = CFG.get("server", {})
    mcp.run(transport="streamable-http", host=srv.get("host", "0.0.0.0"),
            port=int(srv.get("port", 8646)),
            streamable_http_path=srv.get("streamable_http_path", "/mcp"))
