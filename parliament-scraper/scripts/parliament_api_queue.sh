#!/bin/bash
# parliament API queue tick — cron no_agent wrapper (drains WQ/bills/books/...).
exec /opt/data/parliament-scraper/.venv/bin/python /opt/data/scripts/parliament_api_queue.py --time-budget 95
