#!/bin/bash
# GETS tender capture tick — cron no_agent wrapper.
# Queue drain of gets.govt.nz detail pages; silent when nothing to do.
exec python3 /opt/data/gets-scraper/gets_capture.py --time-budget 80 --limit 40
