#!/bin/bash
# Court CDX discovery — retries buckets Wayback dropped (503/504).
# Silent unless new URLs land or Wayback is systemically failing.
cd /opt/data/court-scraper || { echo "court-cdx: cannot cd to court-scraper"; exit 1; }
OUT=$(python3 discover_cdx.py 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "court-cdx discover exited $RC:"; echo "$OUT"; exit 1
fi
if echo "$OUT" | grep -q "nothing to do"; then
  exit 0   # fully discovered — silent
fi
ADDED=$(echo "$OUT" | grep -oP 'added=\K[0-9]+' | tail -1)
FAILED=$(echo "$OUT" | grep -c "failed:")
if [ "${ADDED:-0}" -gt 0 ]; then
  echo "court-cdx: ${ADDED} new case URLs queued."; echo "$OUT"
elif [ "$FAILED" -gt 0 ]; then
  echo "court-cdx: 0 added, ${FAILED} prefixes still failing (Wayback CDX degraded):"; echo "$OUT"
fi
exit 0
