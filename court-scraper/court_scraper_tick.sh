#!/bin/bash
# court judgments capture tick — cron no_agent wrapper.
# RSS freshness + queue drain; silent when nothing to do.
# flock -n -E 0: skip silently if the staggered twin tick is still running.
exec flock -n -E 0 /tmp/court_scraper.tick.lock python3 /opt/data/court-scraper/court_scraper.py --time-budget 110 --limit 60
