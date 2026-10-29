#!/bin/bash
# JDO "everything new" ticker — cron wrapper (bare filename rule).
# JSON API over plain HTTP; silent unless new decisions land.
cd /opt/data/court-scraper || { echo "jdo-new: cannot cd to court-scraper"; exit 1; }
OUT=$(python3 jdo_new.py 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "jdo-new exited $RC:"; echo "$OUT"; exit 1
fi
[ -n "$OUT" ] && echo "$OUT"
exit 0
