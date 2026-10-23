#!/usr/bin/env python3
"""Beehive collector watchdog — zero-LLM, stdlib-only.

Prints an alert ONLY when something is wrong, plus a one-line heartbeat on
Mondays (or with --heartbeat) so silent success is still visible.
Empty stdout on healthy non-heartbeat days = no message.

Checks:
  * collector last_success age (2h cadence -> alert if > 8h)
  * consecutive source errors recorded by the collector
  * feed silence: zero items AND zero edits in the manifest for 7 days
    (Beehive publishes ~3-10 items/day on weekdays; a week of nothing is wrong)
  * bodies queue note (informational; HTML capture is Tier-2, see README)
"""

import json
import os
import sys
from datetime import datetime, timezone

BASE = os.environ.get("BEEHIVE_BASE", "/opt/data/beehive-scraper")
STATE_F = os.path.join(BASE, "state.json")
MANIFEST_F = os.path.join(BASE, "manifest.jsonl")
MAX_AGE_H = 8.0
SILENCE_DAYS = 7
HEARTBEAT_WEEKDAY = 0  # Monday


def load_state():
    try:
        with open(STATE_F) as f:
            return json.load(f)
    except Exception:
        return None


def manifest_window(days):
    """Counts of kind=item / kind=edit in the last `days` days (tail scan)."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    items = edits = 0
    try:
        with open(MANIFEST_F, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            for line in f.read().decode("utf-8", "replace").splitlines():
                try:
                    rec = json.loads(line)
                    ts = datetime.fromisoformat(rec["ts"]).timestamp()
                except Exception:
                    continue
                if ts >= cutoff:
                    if rec.get("kind") == "item":
                        items += 1
                    elif rec.get("kind") == "edit":
                        edits += 1
    except FileNotFoundError:
        pass
    return items, edits


def body_progress():
    """Backfill backlog + bodies captured in the last 24h (done.jsonl tail)."""
    try:
        with open(os.path.join(BASE, "backfill_queue.jsonl")) as f:
            backlog = sum(1 for _ in f)
    except FileNotFoundError:
        backlog = 0
    cutoff = datetime.now(timezone.utc).timestamp() - 86400
    recent = 0
    try:
        with open(os.path.join(BASE, "done.jsonl"), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            for line in f.read().decode("utf-8", "replace").splitlines():
                try:
                    rec = json.loads(line)
                    if rec.get("status") != "ok":
                        continue
                    if datetime.fromisoformat(rec["fetched_at"]).timestamp() >= cutoff:
                        recent += 1
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return backlog, recent


def main():
    now = datetime.now(timezone.utc)
    state = load_state()
    problems = []

    if state is None:
        problems.append("state.json missing/unreadable — collector has never run")
        age_h = None
    else:
        ls = state.get("last_success")
        if not ls:
            problems.append("collector has never completed successfully")
            age_h = None
        else:
            age_h = (now - datetime.fromisoformat(ls)).total_seconds() / 3600
            if age_h > MAX_AGE_H:
                problems.append(f"last success was {age_h:.1f}h ago (expected <3h at 2h cadence)")
        if state.get("consecutive_errors", 0) > 0:
            problems.append(
                f"{state['consecutive_errors']} consecutive run(s) with source errors — "
                f"last: {str(state.get('last_error', ''))[:200]}")

    items7, edits7 = manifest_window(SILENCE_DAYS)
    if not problems and items7 == 0 and edits7 == 0:
        problems.append(f"no items or edits recorded in {SILENCE_DAYS} days — feed capture may be silently broken")
    backlog, recent = body_progress()
    if backlog > 0 and recent == 0:
        problems.append(f"backfill backlog={backlog} but zero bodies captured in 24h — bodyfetch may be stalled")

    try:
        with open(os.path.join(BASE, "pending_pages.jsonl")) as f:
            queued = sum(1 for _ in f)
    except FileNotFoundError:
        queued = 0

    heartbeat = "--heartbeat" in sys.argv or now.weekday() == HEARTBEAT_WEEKDAY
    if problems or heartbeat:
        status = "OK" if not problems else f"{len(problems)} PROBLEM(S)"
        age_s = f"{age_h:.1f}h ago" if age_h is not None else "never"
        print(f"Beehive scraper {status} — items(7d)={items7}, edits(7d)={edits7}, "
              f"last success {age_s}, bodies queued={queued}, backfill backlog={backlog}, "
              f"bodies/24h={recent}, runs={state.get('runs', 0) if state else 0}")
        for p in problems:
            print(f"- {p}")
        if queued:
            print(f"- note: {queued} page bodies queued for Tier-2 capture (HTML is JS-challenged from the VPS; see README)")
    sys.exit(0)


if __name__ == "__main__":
    main()
