#!/bin/bash
# court sources discovery tick — cron no_agent wrapper.
# ERA + HRRT + HPDT + Waitangi Tribunal -> queue.jsonl (budgeted/resumable;
# the underlying discoverer keeps state across the 120s hard-kill).
# 2026-11-03: + MoJ forms Solr estate (Tenancy TTV2 / ARLA / IPT+RSAA IPTV2)
# + Teachers Disciplinary Tribunal list pages.
python3 /opt/data/court-scraper/discover_new_sources.py --budget 55
python3 /opt/data/court-scraper/discover_moj_solr.py --budget 45
python3 /opt/data/court-scraper/discover_teachers.py --budget 15
exit 0
