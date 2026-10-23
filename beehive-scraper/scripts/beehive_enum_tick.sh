#!/bin/bash
# beehive speeches/features enumeration tick — cron no_agent wrapper.
# Enumerates live listing pages + Wayback CDX index, queues new URLs for the
# backfill cron, and re-captures the Post-Cabinet feature page on change.
export PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/scripts/beehive_enum_browse.py
