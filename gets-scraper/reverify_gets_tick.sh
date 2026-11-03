#!/bin/bash
# Re-verify GETS tender pages (suppression/change detection) — split from the
# old composite reverify tick (120s hard-kill). Silent when nothing changed.
OUT=$(python3 /opt/data/gets-scraper/gets_reverify.py --limit 30 --time-budget 80 2>&1)
RC=$?
if [ $RC -ne 0 ]; then echo "reverify-gets exited $RC:"; echo "$OUT"; exit 1; fi
EV=$(echo "$OUT" | grep -oP 'events=\K[0-9]+' | awk '{s+=$1} END {print s}')
if [ "${EV:-0}" -gt 0 ]; then echo "reverify-gets: ${EV} change events:"; echo "$OUT"; fi
exit 0
