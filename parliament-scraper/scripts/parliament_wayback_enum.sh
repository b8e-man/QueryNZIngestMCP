#!/bin/bash
# parliament wayback enum tick — cron no_agent wrapper (daily queue refresh).
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/parliament-scraper/wayback_enum.py
