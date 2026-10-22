#!/bin/bash
# parliament.nz scraper tick — run via cron (no_agent script)
# Uses the venv python that has playwright installed.
cd /opt/data/parliament-scraper
.venv/bin/python scrape_pb.py --tier2-budget 3 --pdf-days 14
.venv/bin/python scrape_records.py
