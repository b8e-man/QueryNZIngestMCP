"""Per-source failure streaks — the news sweep's exit policy (ruling 211).

A news source that fails hard reddens the unit only after THRESHOLD
consecutive failures of that same source; a single transient (an RSS 500,
a read timeout) is a ledger line, and the unit exits clean when the rest of
the sweep landed. Three in a row is an outage, not weather, and turns the
board red exactly as the 2026-07-26 all-or-nothing policy did.

State: var/newsscrapers/streaks.json  {source: consecutive_failures}
Ledger: var/audits/newsscrapers_transients.jsonl — one line per failure,
carrying the streak it made and whether it reddened the unit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

THRESHOLD = 3
# PARKING (queue 10, 2026-09-18 — the greystar streak of 09-13→09-15: a source
# that stays dead reddened the unit four times a day for ever and the phone
# rang each time; ruling 211 had no ceiling). At PARK_AFTER consecutive
# failures a source is PARKED: the sweep still attempts it every run (that is
# the scheduled probe) and one success un-parks it, but its failures no
# longer redden the unit — recorded in the ledger as `parked`, named by
# T7.12. Abstain semantics, reversible, no state beyond the streak count.
PARK_AFTER = 6
_VAR = Path(__file__).resolve().parents[2] / "var"
STATE_FILE = _VAR / "newsscrapers" / "streaks.json"
LEDGER = _VAR / "audits" / "newsscrapers_transients.jsonl"


def load(path: Path = STATE_FILE) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in raw.items() if isinstance(v, int) and v > 0}


def save(streaks: dict[str, int], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in sorted(streaks.items()) if v > 0}, indent=1))
    tmp.replace(path)


def record(streaks: dict[str, int], source: str, failed: bool,
           threshold: int = THRESHOLD) -> tuple[int, bool]:
    """Apply one source outcome. Returns (streak_after, reddens).

    Pure on `streaks` (mutated in place): a success resets the source's
    streak to 0; a failure increments it and reddens iff streak >= threshold.
    """
    if not failed:
        streaks.pop(source, None)
        return 0, False
    streaks[source] = streaks.get(source, 0) + 1
    n = streaks[source]
    return n, threshold <= n < PARK_AFTER      # parked (>= PARK_AFTER) never reddens


def is_parked(streaks: dict[str, int], source: str) -> bool:
    return streaks.get(source, 0) >= PARK_AFTER


def parked(streaks: dict[str, int]) -> list[str]:
    """The sources currently parked, for the sweep's print and T7.12's line."""
    return sorted(s for s, n in streaks.items() if n >= PARK_AFTER)


def ledger(source: str, streak: int, reddens: bool, error: str,
           path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": source, "streak": streak, "threshold": THRESHOLD,
            "reddens": reddens, "parked": streak >= PARK_AFTER, "park_after": PARK_AFTER,
            "rule": "ruling-211-consecutive-failures",
            "error": error[:300],
        }) + "\n")
