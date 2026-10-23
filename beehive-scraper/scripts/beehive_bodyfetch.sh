#!/bin/bash
# beehive bodyfetch tick — cron no_agent wrapper (bare filename requirement).
# Needs the parliament-scraper venv (playwright) + the correct browsers path.
export PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/scripts/beehive_bodyfetch.py
