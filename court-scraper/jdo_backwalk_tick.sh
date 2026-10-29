#!/bin/bash
# JDO backwalk tick — historical enumeration, cron wrapper (bare filename).
# Silent unless new PDFs land or the walk completes/fails.
cd /opt/data/court-scraper || { echo "jdo-backwalk: cannot cd"; exit 1; }
OUT=$(python3 jdo_backwalk.py --max-windows 12 --time-budget 100 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "jdo-backwalk exited $RC:"; echo "$OUT"; exit 1
fi
[ -n "$OUT" ] && echo "$OUT"
exit 0
