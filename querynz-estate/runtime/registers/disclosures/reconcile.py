"""Ruling 66 (Arthur, 21 October 13:00), for every political-donation
document: where a document's parts do not sum to its printed total, a
difference below $100 is reconciled and the row carries an issue naming
the difference and the parts; $100 or more is unreconciled, as before.
The published total is always the printed one. Here the parts are the
gifts a declaration itemises, against the amount the Commission prints
(`read.items_check`). The scanned form's total against the table is two
printings of one figure, not parts, and stays to the cent (`form_check`).

    RECONCILE_TOLERANCE_CENTS      10000: below it is reconciled; exactly $100 is not
    cents(x)                       a figure in whole cents, half up
    difference(parts, printed)     cents, parts minus printed (signed)
    within(parts, printed)         the difference is below the tolerance
    issue(parts, printed, what)    None when equal to the cent; else "+0.16: what"
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
