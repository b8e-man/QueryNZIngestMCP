#!/usr/bin/env python3
"""Index-core contract battery (no SDK, no network, plain asserts).

Encodes the served contract's load semantics: stable arrival order and seq
across rebuilds, incremental tailing, duplicate-id enrichment, sidecar
compaction equivalence, fail-loud id resolution, glob re-expansion, and the
capture/annotation block shapes. Run: python3 tests/test_index.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from index import Corpus  # noqa: E402

TMP = tempfile.mkdtemp(prefix="qnz-index-test-")
STATE = os.path.join(TMP, "state")
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + ((" — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def row(uid, text="body", **kw):
    r = {"uid": uid, "url": "httpx://example.invalid/" + uid,
         "title": "t-" + uid, "text": text,
         "fetched_at": "2026-01-0" + uid[-1] + "T00:00:00+00:00"}
    r.update(kw)
    return r


def cfg_for(recfile, **kw):
    c = {"id_field": "uid", "date_field": "fetched_at", "title_field": "title",
         "record_file": recfile, "state_dir": STATE}
    c.update(kw)
    return c


# 1. arrival order + stable seq across rebuild (a row removed mid-file, a new
#    row appended: existing positions must not move; the new row lands last)
f1 = os.path.join(TMP, "recs.jsonl")
write_jsonl(f1, [row("u1"), row("u2"), row("u3")])
c1 = Corpus("t-order", cfg_for(f1))
seqs = {r["id"]: r["seq"] for r in c1.records}
check("order: 3 recs, seqs 0..2", len(c1.records) == 3
      and sorted(r["seq"] for r in c1.records) == [0, 1, 2])
write_jsonl(f1, [row("u1"), row("u3"), row("u4")])   # u2 removed, u4 appended
c1.reload()
seqs2 = {r["id"]: r["seq"] for r in c1.records}
check("order: seq stable for surviving rows",
      seqs2.get("u1") == seqs["u1"] and seqs2.get("u3") == seqs["u3"],
      (seqs, seqs2))
check("order: new row lands at the end",
      seqs2.get("u4") == max(seqs2.values()), seqs2)

# 2. incremental tailing (append without rewrite)
with open(f1, "a") as f:
    f.write(json.dumps(row("u5")) + "\n")
c1.reload()
check("tail: appended row picked up without rebuild",
      any(r["id"] == "u5" for r in c1.records) and len(c1.records) == 4)

# 3. duplicate-id enrichment: later rows fill missing fields and move
#    updated_at (append-only corrections)
f2 = os.path.join(TMP, "dupes.jsonl")
write_jsonl(f2, [row("d1", text="alpha")])
c2 = Corpus("t-dupe", cfg_for(f2))
u0 = c2.records[0]["updated_at"]
write_jsonl(f2, [row("d1", text="alpha"), row("d1", text="alpha", extra="filled")])
c2.reload()
check("dupe: one record for the id", len(c2.records) == 1)
check("dupe: missing field enriched",
      c2.records[0]["fields"].get("extra") == "filled")
check("dupe: enrichment moves updated_at", c2.records[0]["updated_at"] >= u0)

# 4. sidecar compaction equivalence: seqs identical after churn + compact,
#    and the compacted file is exactly the effective state
f3 = os.path.join(TMP, "compact.jsonl")
write_jsonl(f3, [row("k%d" % i) for i in range(30)])
c3 = Corpus("t-compact", cfg_for(f3, compact_min_lines=10))
before = {r["id"]: r["seq"] for r in c3.records}
for n in range(4):                       # churn: rewrite content 4x
    write_jsonl(f3, [row("k%d" % i, text="v%d-%d" % (i, n)) for i in range(30)])
    c3.reload()
for n in range(3):                       # churn the sidecar log itself
    for i in range(30):
        c3._sidecar_put("k%d" % i, before["k%d" % i], "h%d-%d" % (i, n))
    c3._sidecar_flush()
side = os.path.join(STATE, "t-compact.jsonl")
log_lines = sum(1 for _ in open(side))
check("compact: log grew past the threshold", log_lines > 10, log_lines)
c4 = Corpus("t-compact", cfg_for(f3, compact_min_lines=10))   # fresh load
after = {r["id"]: r["seq"] for r in c4.records}
check("compact: seqs identical after compaction", before == after,
      (before, after))
n_after = sum(1 for _ in open(side))
check("compact: sidecar far below the churned log",
      len(c4._persist) == 30 and n_after < log_lines,
      (len(c4._persist), n_after, log_lines))

# 5. fail-loud: id_field matches nothing and no url -> refuse to load
f5 = os.path.join(TMP, "badid.jsonl")
write_jsonl(f5, [{"noid": "x", "title": "orphan"}])
try:
    Corpus("t-badid", {"id_field": "uid", "record_file": f5, "state_dir": STATE})
    check("fail-loud: missing id fields raise", False, "no exception raised")
except ValueError as e:
    check("fail-loud: missing id fields raise", "refusing to load" in str(e))

# 6. glob re-expansion: a new matching file triggers pickup without restart
pat = os.path.join(TMP, "globdir", "part-*.jsonl")
os.makedirs(os.path.join(TMP, "globdir"))
write_jsonl(os.path.join(TMP, "globdir", "part-1.jsonl"), [row("g1")])
c6 = Corpus("t-glob", cfg_for(pat))
check("glob: first file loaded", len(c6.records) == 1)
write_jsonl(os.path.join(TMP, "globdir", "part-2.jsonl"), [row("g2")])
c6.reload()
check("glob: new file appears -> picked up",
      sorted(r["id"] for r in c6.records) == ["g1", "g2"])

# 7. capture + annotation blocks
f7 = os.path.join(TMP, "blocks.jsonl")
write_jsonl(f7, [row("b1", model="extractor-v1", topics="politics",
                     http_status=200, sha256="ab" * 32)])
c7 = Corpus("t-blocks", cfg_for(f7))
r = c7.records[0]
check("blocks: capture keys gathered",
      r.get("capture", {}).get("http_status") == 200
      and r.get("capture", {}).get("sha256") == "ab" * 32)
check("blocks: model-made fields flagged in annotation",
      r.get("annotation", {}).get("fields") == ["topics"]
      and r["annotation"]["generator"] == "extractor-v1")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ALL INDEX CONTRACT TESTS PASS")
