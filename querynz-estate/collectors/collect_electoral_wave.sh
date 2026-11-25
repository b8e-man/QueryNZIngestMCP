#!/usr/bin/env bash
# EC collector WAVE (committed: EC waves 11-24 / 12-01 / 12-08, all current
# 12-15). One spaced re-attempt wave: re-queue every failed read once + re-sweep
# listing pages for new documents. Same bounded budget and pacing as the tick;
# the hourly tick drains any queue the wave leaves behind. Watchdog convention:
# silent when nothing landed; the run report when it did or when the site
# blocked us.
set -u
OUT=$(DISPLAY=:99 PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright \
  /opt/data/news-scrapers/.venv/bin/python /opt/data/scripts/collect_electoral.py \
  --browser --wave --max-fetches 150 --max-seconds 1200 2>&1)
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "collect_electoral wave exited $RC:"
  echo "$OUT" | tail -5
  exit 1
fi
if echo "$OUT" | grep -q "BLOCKED"; then
  echo "$OUT"
  exit 0
fi
LANDED=$(echo "$OUT" | grep -oE "'landed': [0-9]+" | grep -oE '[0-9]+' | paste -sd+ | bc 2>/dev/null || echo 0)
if [ "${LANDED:-0}" -gt 0 ]; then
  echo "$OUT"
fi
exit 0
