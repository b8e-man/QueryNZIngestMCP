#!/bin/bash
# GETS discovery — public lists (freshness) + Wayback CDX (history).
# Silent unless new URLs land or a source is systemically failing.
cd /opt/data/gets-scraper || { echo "gets-discover: cannot cd"; exit 1; }
OUT=$(python3 gets_discover.py --time-budget 90 2>&1)
RC=$?
OUT2=$(python3 gets_cdx_discover.py --time-budget 60 2>&1)
BOTH="$OUT
$OUT2"
ADDED=$(echo "$BOTH" | grep -oP 'added=\K[0-9]+' | awk '{s+=$1} END {print s}')
FAILED=$(echo "$BOTH" | grep -c "fails=[1-9]\|failed (")
if [ $RC -ne 0 ]; then
  echo "gets-discover exited $RC:"; echo "$BOTH"; exit 1
fi
if [ "${ADDED:-0}" -gt 0 ]; then
  echo "gets-discover: ${ADDED} new tender URLs queued."; echo "$BOTH"
elif [ "${FAILED:-0}" -gt 0 ]; then
  echo "gets-discover: 0 added, source failures:"; echo "$BOTH"
fi
exit 0
