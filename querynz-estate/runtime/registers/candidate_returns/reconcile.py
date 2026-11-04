"""Ruling 66 (Arthur, 21 October 13:00), for every political-donation
document: where a document's parts do not sum to its printed total, a
difference below $100 is reconciled and the row carries an `issue` naming
the signed difference and which parts; a difference of $100 or more is
unreconciled and set aside as before. The published total is the printed
one; the difference is never folded into it. Pure.

    difference(parts, printed) -> int         cents, parts minus printed
    within(parts, printed) -> bool            the difference is below RECONCILE_TOLERANCE_CENTS ($100 exactly is not)
    issue(parts, printed, what) -> str|None   None when equal to the cent; else "-50.00: what was summed against what"
"""
from decimal import ROUND_HALF_UP, Decimal

RECONCILE_TOLERANCE_CENTS = 10000


def cents(x) -> int:
    return int((Decimal(str(x)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def difference(parts, printed) -> int:
    return cents(parts) - cents(printed)


def within(parts, printed) -> bool:
    return abs(difference(parts, printed)) < RECONCILE_TOLERANCE_CENTS


def issue(parts, printed, what: str):
    d = difference(parts, printed)
    return None if d == 0 else f"{d / 100:+,.2f}: {what}"


def join(issues) -> str:
    """Several issues on one row, in order; None when there are none."""
    return "; ".join(i for i in issues if i) or None
