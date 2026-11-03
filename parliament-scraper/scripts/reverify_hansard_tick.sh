#!/bin/bash
# Re-verify Hansard PDFs (corrected drafts detection) — split from the old
# composite reverify tick (120s hard-kill starved this step entirely).
# Silent when nothing changed.
OUT=$(python3 /opt/data/parliament-scraper/reverify_hansard.py --limit 30 --time-budget 80 2>&1)
RC=$?
if [ $RC -ne 0 ]; then echo "reverify-hansard exited $RC:"; echo "$OUT"; exit 1; fi
EV=$(echo "$OUT" | grep -oP 'events=\K[0-9]+' | awk '{s+=$1} END {print s}')
if [ "${EV:-0}" -gt 0 ]; then echo "reverify-hansard: ${EV} change events:"; echo "$OUT"; fi
exit 0
