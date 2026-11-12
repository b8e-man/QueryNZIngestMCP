#!/usr/bin/env bash
# Courts finder collector tick (estate-collect@2026-11-13, ruling 172).
# One bounded, resumable chunk: fresh page-1 per jurisdiction + backfill
# cursors. Silent when nothing landed; the run report when it did.
set -u
OUT=$(python3 /opt/data/scripts/collect_courts_finder.py --max-seconds 1200 2>&1)
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "collect_courts_finder tick exited $RC:"
  echo "$OUT" | tail -5
  exit 1
fi
LANDED=$(echo "$OUT" | grep -oE "'landed': [0-9]+" | grep -oE '[0-9]+' | paste -sd+ | bc 2>/dev/null || echo 0)
if [ "${LANDED:-0}" -gt 0 ]; then
  echo "$OUT"
fi
exit 0
