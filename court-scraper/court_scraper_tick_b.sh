#!/bin/bash
# court judgments capture tick B (staggered twin) — cron no_agent wrapper.
# Same queue drain as court_scraper_tick.sh, offset ~2 min in the 5-min cycle.
# flock -n -E 0: skip silently if the main tick is still running.
exec flock -n -E 0 /tmp/court_scraper.tick.lock python3 /opt/data/court-scraper/court_scraper.py --time-budget 110 --limit 60
