#!/bin/bash
# GETS tender-history enum — split from the old composite tick (120s hard-kill).
cd /opt/data/gets-scraper || { echo "gets-history-enum: cannot cd"; exit 1; }
OUT=$(python3 gets_history_enum.py --time-budget 80 2>&1)
RC=$?
if [ $RC -ne 0 ]; then echo "gets-history-enum exited $RC:"; echo "$OUT"; exit 1; fi
ADDED=$(echo "$OUT" | grep -oP 'added=\K[0-9]+' | awk '{s+=$1} END {print s}')
FAILED=$(echo "$OUT" | grep -c "fails=[1-9]\|failed (")
if [ "${ADDED:-0}" -gt 0 ]; then
  echo "gets-history-enum: ${ADDED} new tender URLs queued."; echo "$OUT"
elif [ "${FAILED:-0}" -gt 0 ]; then
  echo "gets-history-enum: 0 added, source failures:"; echo "$OUT"
fi
exit 0
