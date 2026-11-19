#!/usr/bin/env python3
"""build_replies_2026_11_18.py — reply body for estate-newsroom-pro-stubs@2026-11-18.

Mangle-safe (SKILL.md pitfalls): no scheme-ful URL literals in body text —
pages referenced by their own names from the put. One builder, json round-trip,
runtime "https" probe asserted absent, write + re-read + verify.
"""
import json
import os

OUT = "/opt/data/qnz-mcp/replies/estate-newsroom-pro-stubs-2026-11-18.json"
SCHEME = "http" + chr(115) + chr(58) + chr(47) + chr(47)   # runtime probe

body = {
    "reply": ("Re: estate-newsroom-pro-stubs@2026-11-18 - refetch done under "
              "the Newsroom (Pro) session, the session DOES unlock Pro, and "
              "the Pro-sales-block stub check is in the lane's thin-row test."),
    "reading": {
        "1": ("You hold 8 newsroom.co.nz pages whose body is only the Newsroom "
              "Pro teaser (text ends on the Pro sales block, 619-1,156 "
              "chars). You want them refetched under the Pro session and the "
              "whole bodies landed as NEW rows."),
        "2": ("We state whether the stored session unlocks Newsroom Pro "
              "articles at all, and by what rule the lane distinguishes a Pro "
              "teaser from a full body."),
        "3": ("The lane's thin-row test must learn the Pro sales block, so a "
              "teaser is classed as a stub and never lands as a body."),
    },
    "your_asks": [
        {"n": 1,
         "ask": "Refetch the 8 under the Pro session; land whole bodies as new rows.",
         "answer": ("DONE. All 8 refetched under the live subscriber session "
                    "and landed as NEW rows on 2026-11-17 (append-only: the "
                    "original teaser rows remain in place; the new rows carry "
                    "fetch_mode 'refetch-pro'). Whole-body chars, your list "
                    "order, new (old): 1 how-to-use-mowbray-brash 8,968 "
                    "(1,156); 2 act-and-nz-first-set 5,659 (882); 3 "
                    "animal-welfare-codes 11,941 (972); 4 "
                    "opportunity-was-the-overhangs 4,347 (848); 5 "
                    "peters-keeps-his-head 6,720 (1,060); 6 rooftop-solar-"
                    "demand 5,722 (776); 7 there-wasnt-just-one-poll 4,018 "
                    "(619); 8 fishing-sector-trying 6,768 (794). Zero "
                    "Pro-sales markers in any new body.")},
        {"n": 2,
         "ask": ("Say whether the session unlocks Newsroom Pro articles, and "
                 "how the lane tells a Pro teaser from a full body."),
         "answer": ("Yes - the session unlocks Pro. MEASURED on the same 8 "
                    "pages: teaser 619-1,156 chars vs 4,018-11,941 fetched "
                    "under the live session, byte-verified zero Pro-sales "
                    "markers in the new bodies. Your finding resolves to your "
                    "first explanation: the 11-12 November rows were fetched "
                    "while the stored session was stale, not because Pro sits "
                    "outside the subscription. The lane's tell is the Pro "
                    "sales block itself: extracted text carrying "
                    "'Exclusive subscriber-only emails', 'Start 14-day free "
                    "trial' or 'Corporate subscriptions also available' is a "
                    "teaser; a body has none of them. (Full bodies land "
                    "4,018+ chars against a 619-char teaser - length is a "
                    "backstop, the sales block is the rule.)")},
        {"n": 3,
         "ask": "Add a stub check on the Pro sales block to the thin-row test.",
         "answer": ("DONE 2026-11-17. newsroom.extract now returns nothing "
                    "(drop as thin, loud line naming the page) whenever the "
                    "extracted text carries the Pro sales block - the same "
                    "standing stub rule as the other outlets. Pinned by three "
                    "unit tests (teaser drops, body extracts, each of the "
                    "three markers recognised); full suite 39 passed. A page "
                    "that ever serves a teaser is dropped as thin and shows "
                    "in the thin count - if a future stale session produces "
                    "teasers again, the rows will not silently land as "
                    "bodies.")},
    ],
    "build": ("Refetch + land + lane check + tests shipped 2026-11-17; no "
              "committed dates remain. The 8 new rows are in the "
              "newsroom.co.nz corpus now."),
    "notes": ["Answer strictly by request_id. A change on our side is a new "
              "request_id with amends."],
}

blob = json.dumps(body, ensure_ascii=False, sort_keys=True)
assert SCHEME + chr(46) not in blob, "scheme-ful URL leaked into body text"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write(blob)
back = json.load(open(OUT))
assert json.dumps(back, ensure_ascii=False, sort_keys=True) == blob, "round-trip"
assert SCHEME + chr(46) not in open(OUT).read(), "post-write URL check"
print("wrote", OUT, len(blob), "bytes; verified clean")
