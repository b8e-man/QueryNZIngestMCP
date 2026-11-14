#!/usr/bin/env python3
"""One-shot rearchitecture splitter (2026-11-15 pass).

Moves the corpus index core out of server.py into index.py, with three
additions: sidecar compaction, fail-loud id/date field validation, and
per-corpus load timing. Line ranges are moved verbatim (anchor-asserted);
no transcription.
"""
import os

QP = "/opt/data/qnz-mcp"
src = open(os.path.join(QP, "server.py")).read().splitlines(keepends=True)

def seg(a, b):  # 1-indexed inclusive
    return "".join(src[a - 1:b])

# -- anchors (fail loudly if the file has moved) ------------------------------
assert src[42].startswith("BASE ="), src[42]
assert src[46].startswith("RAW_INDEX_CAP"), src[46]
assert src[48].startswith("TAG_RE"), src[48]
assert src[71].startswith("def strip_html"), src[71]
assert src[121].startswith("def meter"), src[121]
assert src[137].startswith("def _resolve_page"), src[137]
assert src[146].startswith("class Corpus"), src[146]
assert src[575].startswith("CFG ="), src[575]

INDEX_HEADER = '''"""Query NZ Ingest MCP - corpus index core.

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

'''

index_py = (INDEX_HEADER
            + seg(47, 47)          # RAW_INDEX_CAP
            + seg(49, 50)          # TAG_RE, WS_RE
            + seg(52, 69)          # ANNOTATION_FIELDS, CAPTURE_KEYS, TEXT_FIELD_KEYS
            + seg(72, 120)         # strip_html .. now_iso
            + seg(138, 144)        # _resolve_page
            + seg(147, 573))       # class Corpus

# -- addition 1: counted id resolution + validation ---------------------------
old_rid = '''        rid = str(row.get(self.cfg["id_field"]) or row.get("url")
                  or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16])'''
new_rid = '''        _raw_id = row.get(self.cfg["id_field"]) or row.get("url")
        if not _raw_id:
            self._vstats["id_hashed"] += 1
        rid = str(_raw_id) if _raw_id else hashlib.sha256(
            json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]'''
assert old_rid in index_py
index_py = index_py.replace(old_rid, new_rid, 1)

old_top = '''    def _row_to_rec(self, row: dict, text: str, arrived: str = "") -> dict:'''
new_top = '''    def _row_to_rec(self, row: dict, text: str, arrived: str = "") -> dict:
        self._vstats["rows"] += 1
        if not row.get(self._date_val(row)):
            self._vstats["date_missing"] += 1'''
assert old_top in index_py
index_py = index_py.replace(old_top, new_top, 1)

# -- addition 2: vstats counter init in __init__ ------------------------------
old_init = '''        self._next_seq = 0
        self._load_sidecar()'''
new_init = '''        self._next_seq = 0
        self._vstats = {"rows": 0, "id_hashed": 0, "date_missing": 0}
        self._load_sidecar()'''
assert old_init in index_py
index_py = index_py.replace(old_init, new_init, 1)

# -- addition 3: sidecar compaction at load -----------------------------------
old_sc = '''        self._next_seq = max((v[0] for v in self._persist.values()),
                             default=-1) + 1'''
new_sc = '''        self._next_seq = max((v[0] for v in self._persist.values()),
                             default=-1) + 1
        # compaction: the sidecar is a log with last-line-per-id semantics; if
        # churn has left it far ahead of the effective state, rewrite it once
        # (atomic replace) so boot never re-parses years of duplicates. seq
        # assignments are preserved exactly - cursors stay valid.
        eff = len(self._persist)
        if n_lines > 2000 and n_lines > 2 * max(eff, 1):
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                for rid, (seq, h) in self._persist.items():
                    f.write(json.dumps({"id": rid, "seq": seq, "h": h}) + "\\n")
            os.replace(tmp, path)
            print(f"[load] compacted sidecar {self.name}: {n_lines} -> {eff} lines",
                  file=sys.stderr)'''
assert old_sc in index_py
index_py = index_py.replace(old_sc, new_sc, 1)

old_sl = '''    def _load_sidecar(self):
        try:
            with open(self._sidecar_path()) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    self._persist[r["id"]] = [r["seq"], r.get("h", "")]
        except FileNotFoundError:
            pass'''
new_sl = '''    def _load_sidecar(self):
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
            pass'''
assert old_sl in index_py
index_py = index_py.replace(old_sl, new_sl, 1)

# -- addition 4: fail-loud field validation + load timing at end of reload() ---
old_rel = '''            self._gen += 1
            self._fresh_cache = None'''
new_rel = '''            self._gen += 1
            self._fresh_cache = None
            self._validate_fields()
        if _t0 is not None:
            print(f"[load] {self.name}: {len(self.records)} recs "
                  f"in {(time.time() - _t0) * 1000:.0f}ms", file=sys.stderr)'''
assert old_rel in index_py
index_py = index_py.replace(old_rel, new_rel, 1)

old_reload = '''    def reload(self, force: bool = False):
        with self._lock:'''
new_reload = '''    def _validate_fields(self):
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
        with self._lock:'''
assert old_reload in index_py
index_py = index_py.replace(old_reload, new_reload, 1)

with open(os.path.join(QP, "index.py"), "w") as f:
    f.write(index_py)

# -- rebuild server.py: keep everything outside the moved ranges --------------
SERVER_ADDITION = "from index import (Corpus, TEXT_FIELD_KEYS, now_iso, norm_date)\n"
server_py = (seg(1, 42)              # docstring + imports
             + seg(43, 46)           # BASE, CONFIG, METER_F, MINTED_F
             + SERVER_ADDITION
             + seg(122, 135)         # meter
             + seg(576, 1727))       # CFG load .. end
with open(os.path.join(QP, "server.py"), "w") as f:
    f.write(server_py)

import py_compile
for name in ("server.py", "index.py"):
    py_compile.compile(os.path.join(QP, name), doraise=True)
print("split written + compiled: server.py %d lines, index.py %d lines"
      % (len(server_py.splitlines()), len(index_py.splitlines())))
