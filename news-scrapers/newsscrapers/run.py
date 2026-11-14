"""newsscrapers runner — one polite sweep over the registry.

    python -m newsscrapers.run                    # all runnable news sources
    python -m newsscrapers.run --source rnz.co.nz
    python -m newsscrapers.run --dry --limit 3    # discovery+extract, no landing
    python -m newsscrapers.run --status           # readiness report, no fetching

Sources run SEQUENTIALLY (one host at a time; base's POLITE_SLEEP paces within
a host). Blocked sources are skipped with a reason unless their credentials
are present. Exit policy (ruling 211, 2026-09-06): a news source reddens the
unit (exit 1) only after THREE consecutive failures of that same source
(newsscrapers.streaks); a single transient is a ledger line and the sweep
exits 0 when the rest landed. Per-article errors are counted, logged and
non-fatal.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys

from newsscrapers import base, streaks
from newsscrapers.registry import REGISTRY, runnable

# per-source wall-clock bound: one stuck outlet (a hung browser page, a slow
# challenge loop) must cost this much at most and never eat the sweep. Tunable
# for tests via NWS_SOURCE_TIMEOUT.
SOURCE_TIMEOUT = int(os.environ.get("NWS_SOURCE_TIMEOUT") or 280)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="one registry key (default: every runnable news source)")
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--limit", type=int, default=100, help="max articles per source")
    ap.add_argument("--dry", action="store_true", help="discover+extract only, land nothing")
    ap.add_argument("--status", action="store_true", help="print readiness and exit")
    args = ap.parse_args()

    if args.status:
        for name, e in REGISTRY.items():
            ok, why = runnable(name)
            print(f"  {'RUN ' if ok else 'SKIP'}  {name:<20} [{e.category}] {why}")
        return 0

    names = [args.source] if args.source else list(REGISTRY)
    failures = 0
    runs = streaks.load() if not args.dry else {}
    for name in names:
        ok, why = runnable(name)
        if not ok:
            print(f"== {name}: SKIP — {why}")
            continue
        mod = importlib.import_module(f"newsscrapers.{REGISTRY[name].module}")
        print(f"== {name} ({why})")
        try:
            stats = await asyncio.wait_for(
                base.run_source(mod, hours=args.hours, limit=args.limit, dry=args.dry),
                timeout=SOURCE_TIMEOUT)
            print(f"   {stats}")
            if not args.dry:
                streaks.record(runs, name, failed=False)
        except Exception as e:  # noqa: BLE001 — one source must not kill the sweep
            print(f"   SOURCE FAILED: {type(e).__name__}: {e}")
            # exit-code policy (ruling 211): a news source reddens the unit only
            # on its THIRD consecutive failure — one transient is a ledger line;
            # "other"-category corpora fail soft regardless — a decision-body
            # site being down is a log line, not an aborted daily tick (the
            # ourauckland 403 lesson, 2026-07-26). A --dry run touches no state.
            if REGISTRY[name].category == "news" and not args.dry:
                streak, reddens = streaks.record(runs, name, failed=True)
                streaks.ledger(name, streak, reddens, f"{type(e).__name__}: {e}")
                if streaks.is_parked(runs, name):
                    # PARKED (queue 10): this attempt was the scheduled probe —
                    # recorded, not counted; one success un-parks it
                    state = f"PARKED (≥{streaks.PARK_AFTER}; probed each sweep, un-parks on a success)"
                else:
                    state = "RED" if reddens else "transient (ledgered)"
                print(f"   streak {streak}/{streaks.THRESHOLD} → {state}")
                if reddens:
                    failures += 1
    if not args.dry:
        streaks.save(runs)
        if streaks.parked(runs):
            print(f"== parked news sources (not counted): {', '.join(streaks.parked(runs))}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
