#!/bin/bash
# parliament wayback batch tick — cron no_agent wrapper.
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/parliament-scraper/wayback_batch.py --limit 25 --time-budget 95
