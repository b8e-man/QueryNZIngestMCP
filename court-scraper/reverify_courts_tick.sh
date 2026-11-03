#!/bin/bash
# Re-verify courts (suppression/takedown + change detection) — split from the
# old composite reverify tick (chained 270s budgets vs 120s cron hard-kill,
# which starved the Hansard step). Silent when nothing changed.
OUT=$(python3 /opt/data/court-scraper/reverify_courts.py --limit 30 --time-budget 80 2>&1)
RC=$?
if [ $RC -ne 0 ]; then echo "reverify-courts exited $RC:"; echo "$OUT"; exit 1; fi
EV=$(echo "$OUT" | grep -oP 'events=\K[0-9]+' | awk '{s+=$1} END {print s}')
if [ "${EV:-0}" -gt 0 ]; then echo "reverify-courts: ${EV} change events:"; echo "$OUT"; fi
exit 0
