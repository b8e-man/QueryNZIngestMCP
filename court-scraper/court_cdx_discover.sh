#!/bin/bash
# Court CDX discovery — retries buckets Wayback dropped (503/504).
# Silent unless new URLs land or Wayback is systemically failing.
cd /opt/data/court-scraper || { echo "court-cdx: cannot cd to court-scraper"; exit 1; }
# discover_cdx.py (courtsofnz case-page CDX) PARKED 2026-10-29 — its
# judgment stream is superseded by the JDO ticker/backwalk. Tribunals are
# NOT in JDO's taxonomy, so their CDX discovery stays.
OUT=$(python3 discover_tribunals.py 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "court-cdx discover exited $RC:"; echo "$OUT"; exit 1
fi
OUT2=""; RC2=0
BOTH="$OUT
$OUT2"
ADDED=$(echo "$BOTH" | grep -oP 'added=\K[0-9]+' | awk '{s+=$1} END {print s}')
FAILED=$(echo "$BOTH" | grep -c "failed:\|attempt 3:")
if [ "${ADDED:-0}" -gt 0 ]; then
  echo "court-cdx: ${ADDED} new URLs queued."; echo "$BOTH"
elif [ "$RC2" -ne 0 ] || [ "$FAILED" -gt 0 ]; then
  echo "court-cdx: 0 added, ${FAILED} prefix failures (Wayback CDX degraded):"; echo "$BOTH"
fi
exit 0
