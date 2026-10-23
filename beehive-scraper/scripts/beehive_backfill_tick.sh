#!/bin/bash
# beehive historical backfill tick — cron no_agent wrapper.
# Drains backfill_queue.jsonl (built by beehive_backfill.py) through the
# residential proxy. Silent when the queue is drained.
export PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/scripts/beehive_bodyfetch.py \
  --queue /opt/data/beehive-scraper/backfill_queue.jsonl --limit 90 --time-budget 95
