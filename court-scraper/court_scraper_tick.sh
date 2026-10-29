#!/bin/bash
# court judgments capture tick — cron no_agent wrapper.
# RSS freshness + queue drain; silent when nothing to do.
exec python3 /opt/data/court-scraper/court_scraper.py --time-budget 80 --limit 40
