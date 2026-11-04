"""The lane's checks against the world outside it (contract: the lane).

1. The frozen site. Its current release's `data/home.json` carries, for
   every party, the large donations it shows by year (`disclosed_by_year`,
   bucketed by the day the party received the gift) and their count
   (`disclosed_n`). Every party-year the frozen site shows is compared with
   the declarations this lane holds from the Commission's table for the
   same party and year; a difference is a card, never a silent fix. The
   frozen site reads only the 2023 regime, so the earlier regimes are
   counted apart, not compared.
2. The form's own total: the Commission prints the amount twice, in its
   table and on the scanned declaration. Where a page reading or the
   scan's typed text layer gives the total, the load compares the two
   (`form_check`); here they are counted.
3. Ruling 66: the declarations whose itemised gifts reconcile to the
   amount only within $100 carry an `issue`; here they are counted
   (`issues`), each printed with its difference, never folded.

Either way a difference is printed, and fails the check unless a card in
`cards/` names it (the party and year, or the declaration's key): a
difference is a card, never a silent fix, and a carded one is still shown.

    frozen()                       ({(party, year): total}, {party: count})
    compare(rows, frozen_by_year, frozen_n)
    issues(rows)                   [(key, issue)] of the rows carrying one (ruling 66)
    verdict(rows, by_year, n, cards)  (differences no card names, lines): the job's gate (load.job)
    python -m registers.disclosures.check [--schema disclosures] [--database querynz_v4]

Read-only.
"""
import glob
import json
import os
import sys

OLD_LIVE = os.environ.get("QV4_OLD_LIVE") or "/home/user/Git Repos/QueryNZ_V3"
HOME_JSON = os.path.join(OLD_LIVE, "var", "pi-snapshot", "current", "data", "home.json")
CARDS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "cards")
COMPARED = "over-20000-from-2023"
TOLERANCE = 0.005


def frozen(path: str = None) -> tuple:
    with open(path or HOME_JSON, encoding="utf-8") as f:
        home = json.load(f)
    by_year, n = {}, {}
    for p in home.get("parties", []):
        for y, v in (p.get("disclosed_by_year") or {}).items():
            by_year[(p["party"], int(y))] = float(v)
        if p.get("disclosed_n"):
            n[p["party"]] = int(p["disclosed_n"])
    return by_year, n


def compare(rows: list, frozen_by_year: dict, frozen_n: dict) -> dict:
    """rows: dicts with party, party_label, regime, amount, given_on."""
    ours, count, earlier, unresolved = {}, {}, 0, {}
    for r in rows:
        if r["regime"] != COMPARED:
            earlier += 1
            continue
        if not r.get("party"):
            unresolved[r["party_label"]] = unresolved.get(r["party_label"], 0) + 1
            continue
        k = (r["party"], int(str(r["given_on"])[:4]))
        ours[k] = round(ours.get(k, 0.0) + float(r["amount"]), 2)
        count[r["party"]] = count.get(r["party"], 0) + 1
    equal, differ = [], []
    for k in sorted(set(ours) | set(frozen_by_year)):
        a, b = ours.get(k, 0.0), frozen_by_year.get(k, 0.0)
        (equal if abs(a - b) <= TOLERANCE else differ).append({"party": k[0], "year": k[1], "ours": a, "frozen": b})
    counts = [{"party": p, "ours": count.get(p, 0), "frozen": frozen_n.get(p, 0)}
              for p in sorted(set(count) | set(frozen_n)) if count.get(p, 0) != frozen_n.get(p, 0)]
    return {"equal": equal, "differ": differ, "count_differs": counts, "earlier_regimes": earlier,
            "unresolved_parties": unresolved}


def issues(rows: list) -> list:
    """[(key, issue)] for every row whose parts reconcile only within the tolerance (ruling 66)."""
    return [(r["key"], r["issue"]) for r in rows if r.get("issue")]


def carded(cards_dir: str = None) -> str:
    """Every card's text, for `card_for` to search."""
    text = []
    for p in sorted(glob.glob(os.path.join(cards_dir or CARDS, "*.md"))):
        with open(p, encoding="utf-8") as f:
            text.append(f"{os.path.basename(p)[:-3]}\n{f.read()}")
    return "\n\x00".join(text)


def card_for(needle: str, cards: str):
    """The name of the first card whose text holds `needle`, or None."""
    for block in cards.split("\n\x00"):
        if needle in block:
            return block.split("\n", 1)[0]
    return None


def held(conn, relation: str) -> list:
    """The declarations of `relation` (a schema's `declarations`, or the
    sample's `disclosures_declarations`), as dicts."""
    cur = conn.execute(f"SELECT key, party, party_label, regime, amount, given_on, form_total, form_check, "
                       f"issue FROM {relation}")
    return [dict(zip([d[0] for d in cur.description], r)) for r in cur]


def verdict(rows: list, frozen_by_year: dict, frozen_n: dict, cards: str) -> tuple:
    """(differences no card names, the lines to print): the whole check."""
    forms = {}
    for r in rows:
        forms[r["form_check"]] = forms.get(r["form_check"], 0) + 1
    out = compare(rows, frozen_by_year, frozen_n)
    uncarded, lines = 0, []
    lines.append(f"equal: {len(out['equal'])} party-years; differ: {len(out['differ'])}; "
                 f"earlier regimes held, not on the frozen site: {out['earlier_regimes']}")
    for d in out["differ"]:
        card = card_for(f"{d['party']} {d['year']}", cards) or card_for(f"{_short(d['party'])} {d['year']}", cards)
        uncarded += card is None
        lines.append(f"  DIFFERS {d['party']} {d['year']}: ours {d['ours']:.2f}, frozen {d['frozen']:.2f}; card: {card or 'NONE'}")
    for c in out["count_differs"]:
        lines.append(f"  count {c['party']}: ours {c['ours']}, frozen {c['frozen']}")
    for label, n in sorted(out["unresolved_parties"].items()):
        lines.append(f"  not a registered party in keys.parties: {label!r} ({n})")
    lines.append("the form's own total against the table: " + ", ".join(f"{k} {v}" for k, v in sorted(forms.items())))
    for r in rows:
        if r["form_check"] == "differs":
            card = card_for(r["key"], cards)
            uncarded += card is None
            lines.append(f"  FORM DIFFERS {r['key']}: table {r['amount']:.2f}, form {r['form_total']:.2f}; card: {card or 'NONE'}")
    flagged = issues(rows)
    lines.append(f"reconciled with an issue (ruling 66, below $100): {len(flagged)}")
    for key, why in flagged:
        lines.append(f"  ISSUE {key}: {why}")
    lines.append(f"differences with no card: {uncarded}")
    return uncarded, lines


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    schema = argv[argv.index("--schema") + 1] if "--schema" in argv else "disclosures"
    database = argv[argv.index("--database") + 1] if "--database" in argv else "querynz_v4"
    from support import db
    with db.connect(db.READ_KEY if database == "querynz_v4" else db.OWNER_KEY, database) as conn:
        rows = held(conn, f"{schema}.declarations")
    uncarded, lines = verdict(rows, *frozen(), carded())
    for line in lines:
        print(line)
    return 1 if uncarded else 0


def _short(party: str) -> str:
    """'The New Zealand National Party' → 'National', as the cards name it."""
    return party.replace("The New Zealand ", "").replace("New Zealand ", "").replace(" Party", "")


if __name__ == "__main__":
    sys.exit(main())
