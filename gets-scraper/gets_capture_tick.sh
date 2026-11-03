#!/bin/bash
# GETS tender capture tick — cron no_agent wrapper.
# Queue drain of gets.govt.nz detail pages; silent when nothing to do.
exec flock -n -E 0 /tmp/gets_capture.tick.lock python3 /opt/data/gets-scraper/gets_capture.py --time-budget 110 --limit 60
