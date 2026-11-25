#!/usr/bin/env python3
"""Builder for the estate-councillor-interests-seq@2026-11-26 reply body.

Mangle-safe recipe (mcp-server-development): assemble bodies in one script,
json round-trip, assert no scheme-ful URL literal, write, re-read, re-verify.
Arithmetic asserts run against the real files BEFORE the body is written.
"""
import json

SRC = "/opt/data/querynz-estate/sources/councillor_interests"
STATE = "/opt/data/qnz-mcp/state/estate-councillor_interests.jsonl"
OUT = "/opt/data/qnz-mcp/replies/reply_seq_2026_11_26.json"

# ---- arithmetic asserts against the actual data (before writing anything) ----
rows = [json.loads(l) for l in open(SRC + "/manifest.jsonl")]
qrows = [json.loads(l) for l in open(SRC + "/manifest-quarantine-2026-11-25.jsonl")]
side = {}
for line in open(STATE):
    e = json.loads(line)
    side[e["id"]] = e["seq"]

served = set(r["sha256"] for r in rows)
qids = set(r["sha256"] for r in qrows)
assert len(rows) == 648, len(rows)
assert len(served) == 545, len(served)
assert len(qrows) == 42 and len(qids) == 42
assert not qids.intersection(served)
assert set(side) == served.union(qids)
assert len(side) == 587 and max(side.values()) == 586

qs = sorted(side[i] for i in qids)
b1 = [s for s in qs if s <= 523]
b2 = [s for s in qs if 524 <= s <= 583]
b3 = [s for s in qs if s >= 584]
assert (len(b1), min(b1)) == (24, 449), (len(b1), min(b1))
assert (len(b2), len(b3), b3) == (15, 3, [584, 585, 586]), (len(b2), len(b3), b3)

# ---- body (no scheme-ful URL literals anywhere) ----
body = {
    "reply": ("Re: estate-councillor-interests-seq@2026-11-26 - the numbering "
              "fault on estate-councillor_interests after the 25 Nov withdrawal "
              "and your contract question about seq and cursor. Short answer: "
              "seq is now a stable number with holes by design, cursor counts "
              "positions, and per your offer the change is on your side. Detail, "
              "and one correction to our own 25 Nov numbers, below."),
    "reading": {
        "1": ("You measured that after our 25 Nov withdrawal of 42 records from "
              "estate-councillor_interests, a record's seq no longer equals its "
              "place in the feed: total 545; cursor 400 returned seq 400..523 "
              "with gaps; cursor 500 returned seq 524..583. Your pull stops on "
              "that page - every pull since 25 Nov 13:00 NZDT is red on this "
              "corpus while the other 41 corpora page cleanly."),
        "2": ("You accept the withdrawal itself and question nothing else in the "
              "25 Nov report."),
        "3": ("Your ask: restore the numbering where seq is a record's place in "
              "arrival order (0..total-1, no holes) as it behaved after earlier "
              "removals; or declare that seq is a stable number with holes, say "
              "what cursor counts, and you will change your side."),
    },
    "your_asks": [
        {"n": 1, "ask": "What seq is now",
         "answer": ("seq is a record's stable arrival-order number: assigned "
                    "once when the record first lands, never renumbered, never "
                    "reused. A withdrawal retires the withdrawn numbers - the 42 "
                    "withdrawn records hold seqs 449..586 and those numbers stay "
                    "gone. The holes are deliberate: renumbering would move every "
                    "later record under a cursor you have stored and repoint the "
                    "per-record resource URIs, which anchor on the same seq. As "
                    "you offered: this is the stable-with-holes contract and the "
                    "change is on your side.")},
        {"n": 2, "ask": "What cursor counts",
         "answer": ("cursor counts positions in the served feed - the number of "
                    "records already ingested (0 = start), places 0..total-1, no "
                    "holes. Page by the next_cursor each response returns; you "
                    "have everything when next_cursor equals the ingest_cursor "
                    "from corpora() (545 on this corpus today). Do not derive "
                    "paging from seq values. Two consequences: after any "
                    "withdrawal a saved position cursor can re-deliver a short "
                    "window (places shift down) - dedupe by id on resume or "
                    "re-pull from 0; and new arrivals always take the next number "
                    "beyond every existing one, so nothing ever moves up.")},
        {"n": 3, "ask": "Your measured numbers",
         "answer": ("they match ours exactly. Served records now 545, before the "
                    "withdrawal 587. The 42 withdrawn records hold seqs 449..586: "
                    "24 of them in 449..523, 15 in 524..583, and 584, 585, 586 - "
                    "which reconstructs both of your sampled pages at limit 100, "
                    "including the top of the feed ending at seq 583. Nothing is "
                    "missing beyond the 42 you accepted.")},
        {"n": 4, "ask": ("Correction to our 25 Nov report: its counts were "
                         "capture rows, not served records"),
         "answer": ("That report said 690 rows before and 648 after. Those are "
                    "capture-file rows; a page re-captured byte-identically lands "
                    "as another row of the same record (records are keyed by "
                    "capture hash). Served records were 587 before and 545 after. "
                    "Your 545 is the right number - we should have reported "
                    "records, not rows. Apologies for the imprecision.")},
        {"n": 5, "ask": "Your earlier-removals observation",
         "answer": ("Places compacting downward after a removal is unchanged "
                    "behaviour - that part is the same as before. On seq itself "
                    "renumbering: numbering has been durable since 15 Nov "
                    "(assigned once per record, preserved through every rebuild). "
                    "The 25 Nov withdrawal is the only removal from a served feed "
                    "we hold on record; an earlier quarantine this month removed "
                    "rows before they were ever served, so your pulls could not "
                    "have seen it. If you saw seq renumbered after a removal, "
                    "name the corpus and date and we will reconcile against our "
                    "records.")},
    ],
    "build": ("No code change on our side from this exchange. One documentation "
              "fix: our README described seq as 'the arrival-order position', "
              "which your reading of it was reasonable under; it now reads "
              "'stable arrival-order number, never reused; withdrawals leave "
              "holes', and the cursor definition stands as in the records tool "
              "description (the number of records already ingested)."),
    "notes": ("Standing rules unchanged: one answer per request_id; a change is "
              "a new request_id with amends; a gap is closed only when records "
              "land."),
}

# ---- mangle checks + write + re-read verification ----
blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
probe = chr(104) + chr(116) + chr(116) + chr(112) + chr(115) + chr(58) + chr(47) + chr(47)
colon_slash = chr(58) + chr(47) + chr(47)
assert probe not in blob, "scheme literal leaked into body"
assert colon_slash not in blob, "scheme separator leaked into body"
assert chr(42) * 3 not in blob, "scrub token visible in body"

with open(OUT, "w") as f:
    f.write(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1))

back = json.load(open(OUT))
assert back == body, "round-trip mismatch"
assert probe not in open(OUT).read() and colon_slash not in open(OUT).read()

print("OK wrote", OUT)
print(json.dumps(back, ensure_ascii=False, indent=1))
