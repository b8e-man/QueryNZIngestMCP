#!/bin/bash
# hansard debates tick — cron no_agent wrapper.
# Recency window only (the 2024-11-20 back run is a one-shot). Silent when
# nothing new — the script prints a line only when it records something.
exec /opt/data/parliament-scraper/.venv/bin/python \
  /opt/data/parliament-scraper/hansard_debates.py \
  --from "$(date -u -d '21 days ago' +%F)" --time-budget 90
