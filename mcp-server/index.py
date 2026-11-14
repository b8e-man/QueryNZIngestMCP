"""Query NZ Ingest MCP - corpus index core.

One mounted corpus, indexed in stable ARRIVAL order: a record's position never
changes once assigned, new records land at the end. Cursor paging, the change
feed and schema publication all rest on that. This module is dependency-light
on purpose so the index semantics can be tested without booting the server
(see tests/test_index.py).
"""
import bisect
import glob
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

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


def _field_get(row: dict, key: str):
    """Field accessor with list/dict paths for title/text columns:
    plain key ('case_name'), list index ('names[0]'), nested ('urls[0].url')."""
    if key in row:
        return row[key]
    cur = row
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", key):
        if part.startswith("["):
            if not isinstance(cur, list):
                return None
            i = int(part[1:-1])
            cur = cur[i] if i < len(cur) else None
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
    return cur


def _flatten_str(v, out: list):
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _flatten_str(x, out)
    elif isinstance(v, list):
        for x in v:
            _flatten_str(x, out)


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
        self._schema_cache = None
        self._lock = threading.Lock()
        self._persist = {}         # id -> [seq, content-hash] — durable state
        self._sidecar_log = []     # sidecar lines awaiting flush
        self._next_seq = 0
        self._vstats = {"rows": 0, "id_hashed": 0, "date_missing": 0}
        self._load_sidecar()
        self.reload(force=True)

    def _files(self):
        return [p for p in (self.cfg.get("extracted_file"),
                            self.cfg.get("captures_file"),
                            *self._record_files()) if p]

    def _record_files(self):
        """`record_file` may be a path, a list of paths, or a glob (e.g. the
        news corpora's per-outlet manifests). Globs re-expand on every call,
        so a newly appeared outlet manifest triggers the rebuild check."""
        rf = self.cfg.get("record_file")
        if not rf:
            return []
        items = rf if isinstance(rf, list) else [rf]
        out = []
        for it in items:
            if any(ch in it for ch in "*?["):
                out.extend(sorted(glob.glob(it)))
            else:
                out.append(it)
        return out

    def _needs_rebuild(self) -> bool:
        for p in self._files():
            try:
                st = os.stat(p)
            except OSError:
                continue
            prev = self._src.get(p)
            if prev is None:
                return True                      # newly appeared file
            psize, pmtime, psample = prev
            if st.st_size < psize:
                return True                      # rewritten / truncated
            if st.st_size == psize:
                if st.st_mtime_ns != pmtime:
                    return True                  # same-size rewrite
                if psample and self._sample(p, st.st_size) != psample:
                    return True                  # same size+mtime, rewritten
        return False

    @staticmethod
    def _sample(path: str, size: int) -> str:
        """Content fingerprint of three small windows (head/mid/tail).

        The FS here gives identical st_mtime values for rewrites inside one
        second, so size+mtime cannot detect a same-size rewrite (measured
        2026-11-15). Three 256-byte reads catch it at negligible cost."""
        try:
            with open(path, "rb") as f:
                chunks = []
                for pos in (0, max(0, size // 2 - 128), max(0, size - 256)):
                    f.seek(pos)
                    chunks.append(f.read(256))
            return hashlib.sha1(b"".join(chunks)).hexdigest()
        except OSError:
            return ""

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

    def _validate_fields(self):
        """Loud on absent named fields (config reality check): an id_field no
        row carries would silently hash-id every record; a date_field absent
        everywhere degrades to None dates. Per-field, not all-or-nothing."""
        v = self._vstats
        if not v["rows"]:
            return
        if v["id_hashed"] == v["rows"]:
            raise ValueError(
                f"corpus {self.name}: id_field {self.cfg.get('id_field')!r} "
                f"matches no row and no row carries url - every id would be a "
                f"content hash (refusing to load; fix the config)")
        if v["id_hashed"]:
            print(f"[load] WARN {self.name}: {v['id_hashed']}/{v['rows']} rows "
                  f"carry neither id_field nor url; ids are content hashes",
                  file=sys.stderr)
        if self.cfg.get("date_field") and v["date_missing"] == v["rows"]:
            print(f"[load] WARN {self.name}: date_field "
                  f"{self.cfg.get('date_field')!r} absent from all rows; "
                  f"dates degrade to None", file=sys.stderr)

    def reload(self, force: bool = False):
        _t0 = time.time()
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
            self.records.sort(key=lambda r: r["seq"])
            self._sidecar_flush()
            self._gen += 1
            self._fresh_cache = None
            self._validate_fields()
        if _t0 is not None:
            print(f"[load] {self.name}: {len(self.records)} recs "
                  f"in {(time.time() - _t0) * 1000:.0f}ms", file=sys.stderr)

    def _read_new(self, path):
        """Rows appended to an append-only JSONL file since the last read."""
        if not path or not os.path.exists(path):
            return
        try:
            st = os.stat(path)
        except OSError:
            return
        off = self._offs.get(path, 0)
        self._src[path] = (st.st_size, st.st_mtime_ns,
                           self._sample(path, st.st_size))
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

    # -- durable per-id state (stable seq + content hash) --------------------
    # Written append-only, last line per id wins. Keeps `seq` — and therefore
    # feed positions — stable across rebuilds: removals or in-place rewrites
    # in source files no longer move other records to a lower position.
    def _sidecar_path(self) -> str:
        d = self.cfg.get("state_dir") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "state")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, self.name + ".jsonl")

    def _load_sidecar(self):
        path = self._sidecar_path()
        n_lines = 0
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    n_lines += 1
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    self._persist[r["id"]] = [r["seq"], r.get("h", "")]
        except FileNotFoundError:
            pass
        self._next_seq = max((v[0] for v in self._persist.values()),
                             default=-1) + 1
        # compaction: the sidecar is a log with last-line-per-id semantics; if
        # churn has left it far ahead of the effective state, rewrite it once
        # (atomic replace) so boot never re-parses years of duplicates. seq
        # assignments are preserved exactly - cursors stay valid.
        eff = len(self._persist)
        min_lines = int(self.cfg.get("compact_min_lines") or 2000)
        if n_lines > min_lines and n_lines > 2 * max(eff, 1):
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                for rid, (seq, h) in self._persist.items():
                    f.write(json.dumps({"id": rid, "seq": seq, "h": h}) + "\n")
            os.replace(tmp, path)
            print(f"[load] compacted sidecar {self.name}: {n_lines} -> {eff} lines",
                  file=sys.stderr)

    def _sidecar_put(self, rid: str, seq: int, h: str):
        self._persist[rid] = [seq, h]
        self._sidecar_log.append(json.dumps({"id": rid, "seq": seq, "h": h}))

    def _sidecar_flush(self):
        if not self._sidecar_log:
            return
        with open(self._sidecar_path(), "a") as f:
            f.write("\n".join(self._sidecar_log) + "\n")
        self._sidecar_log = []

    def _date_val(self, row: dict):
        dfk = self.cfg.get("date_field", "")
        dfk = dfk if isinstance(dfk, list) else [dfk]
        return next((row.get(k) for k in dfk if k and row.get(k)), None)

    def _row_to_rec(self, row: dict, text: str, arrived: str = "") -> dict:
        self._vstats["rows"] += 1
        if not self._date_val(row):
            self._vstats["date_missing"] += 1
        _raw_id = row.get(self.cfg["id_field"]) or row.get("url")
        if not _raw_id:
            self._vstats["id_hashed"] += 1
        rid = str(_raw_id) if _raw_id else hashlib.sha256(
            json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]
        tf = self.cfg.get("title_field", "")
        tfs = tf if isinstance(tf, list) else [tf]
        title = next((str(_field_get(row, k)) for k in tfs
                      if k and _field_get(row, k)), "")
        rec = {
            "id": rid,
            "date": norm_date(self._date_val(row)),
            "title": title[:300],
            "text": text,
            "fields": dict(row),
            "arrived": arrived or str(row.get("fetched_at")
                                      or row.get("_fetched_at")
                                      or row.get("_collected")
                                      or row.get("fetched") or ""),
            # when this version of the record landed (source-provided stamps)
            "updated_at": str(row.get("extracted_at") or row.get("fetched_at")
                              or row.get("_fetched_at")
                              or row.get("_collected") or row.get("fetched")
                              or row.get("lastModified") or ""),
        }
        # semantic content hash: separates "row re-stamped, same content"
        # from "row rewritten in place with new content" (_append/_update)
        rec["_chash"] = hashlib.sha1(
            (title + "\n" + text).encode("utf-8", "replace")).hexdigest()
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
        # `file_fields` (optional, ordered): which row key holds the retained
        # bytes' name relative to path_root. Default preserves the old chain.
        _ff = self.cfg.get("file_fields") or ["path", "raw_file"]
        rf = next((row.get(k) for k in _ff if row.get(k)), None)
        if rf:
            # resolution aid only — the raw `path`/`raw_file` stays
            # as-received in fields/capture. An absolute value (estate
            # manifests' `file`: /opt/data/querynz-estate/store/…) is the
            # store address itself — use verbatim, never re-root it.
            # Relative values resolve under: path_root, then the record
            # file's own dir (Hansard raw/hansard_*.pdf), then pages_dir
            # (docs corpora captures).
            rf = str(rf)
            if os.path.isabs(rf):
                rec["file"] = rf
            else:
                base = (proot
                        or os.path.dirname(
                            self.cfg.get("record_file", "")
                            if isinstance(self.cfg.get("record_file"), str)
                            else "")
                        or self.cfg.get("pages_dir"))
                if base:
                    rec["file"] = os.path.join(base, rf.lstrip("/"))
        return rec

    def _append(self, rec: dict) -> dict:
        rid, h = rec["id"], rec.get("_chash", "")
        ent = self._persist.get(rid)
        if ent is not None:
            rec["seq"] = ent[0]                  # stable across rebuilds
            if ent[1] and ent[1] != h:
                # content changed while the row's own stamps stood still
                rec["updated_at"] = now_iso()
            if ent[1] != h:
                self._sidecar_put(rid, ent[0], h)
        else:
            rec["seq"] = self._next_seq
            self._next_seq += 1
            self._sidecar_put(rid, rec["seq"], h)
        self.records.append(rec)
        self._by_id[rid] = rec
        self._seen.add(rid)
        return rec

    def _update(self, rec: dict, row: dict):
        old = self._by_id[rec["id"]]
        nh = rec.get("_chash", "")
        changed = bool(nh) and nh != old.get("_chash")
        old["date"], old["title"] = rec["date"], rec["title"]
        old["text"], old["fields"] = rec["text"], rec["fields"]
        old["updated_at"] = (now_iso() if changed
                             else (rec.get("updated_at") or now_iso()))
        if nh:
            if changed:
                self._sidecar_put(old["id"], old["seq"], nh)
            old["_chash"] = nh
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
                if row.get("reason") and not old.get("fields", {}).get("reason"):
                    # append-only repair (2026-11-15 practice 1): a reasoned
                    # terminal row must lift its why onto the served record
                    old.setdefault("fields", {})["reason"] = row["reason"]
                    old["updated_at"] = now_iso()
                old["capture"] = dict(row)
                if row.get("path") and pages:
                    f = _resolve_page(pages, row["path"])
                    if f:
                        old["file"] = f
                continue
            rec = staged.pop(rid, None)
            if rec is None:
                rec = self._row_to_rec(row, raw_text(row))
            if row.get("fetched_at"):
                rec["arrived"] = row["fetched_at"]
            rec["capture"] = dict(row)   # provenance: as-received, unfaked
            if row.get("path") and pages:
                f = _resolve_page(pages, row["path"])
                if f:
                    rec["file"] = f
            self._append(rec)

        for rec in staged.values():              # pass 3: extracted-only tail
            self._append(rec)

    def _load_records(self):
        for path in self._record_files():
            self._load_records_file(path)

    def _load_records_file(self, path):
        for row in self._read_new(path):
            raw = row.get("text")
            # rows that already carry a text field reuse it as the search
            # text (same object — no duplicate of a 300KB body in RAM)
            if isinstance(raw, str):
                text = raw
            elif self.cfg.get("text_fields"):
                # search text from named columns only (list/dict flattened);
                # e.g. estate manifests: names[] + urls[].url are the handles
                vals = []
                for k in self.cfg["text_fields"]:
                    _flatten_str(_field_get(row, k), vals)
                text = " ".join(vals)
            else:
                text = " ".join(str(v) for v in row.values()
                                if isinstance(v, str))
            rec = self._row_to_rec(row, text)
            if rec["id"] in self._by_id:
                # duplicate id: first record keeps its capture bytes, but
                # later rows ENRICH missing fields (append-only corrections,
                # e.g. GETS page_fields backfill 2026-11-03). Enrichment
                # moves updated_at so the change feed shows it.
                old = self._by_id[rec["id"]]
                added = False
                for k, v in (rec.get("fields") or {}).items():
                    if v not in (None, "") and old.get("fields", {}).get(k) in (None, ""):
                        old.setdefault("fields", {})[k] = v
                        added = True
                for k in ("doc_date", "citation", "file", "capture"):
                    if rec.get(k) and not old.get(k):
                        old[k] = rec[k]
                        added = True
                if added:
                    if rec.get("_chash"):
                        old["_chash"] = rec["_chash"]
                    old["updated_at"] = now_iso()
                continue
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

    # -- schema (the field registry a consumer diffs against) --
    def schema(self) -> dict:
        """The complete field list a served record can carry: the row's own
        keys plus the serve-layer envelope. schema_hash moves whenever the
        shape does — consumers watch it instead of being surprised."""
        if self._schema_cache is None or self._schema_cache[0] != self._gen:
            fields = set()
            for r in self.records:
                fields.update(r["fields"].keys())
            fields |= {"seq", "id", "date", "title", "text", "updated_at",
                       "capture", "file", "file_uri", "annotation"}
            fl = sorted(fields)
            h = hashlib.sha1("\n".join(fl).encode()).hexdigest()[:16]
            self._schema_cache = (self._gen, {"fields": fl, "schema_hash": h})
        return self._schema_cache[1]
