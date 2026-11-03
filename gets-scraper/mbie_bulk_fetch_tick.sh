#!/bin/bash
# MBIE bulk-award CSV fetch (IPRoyal residential; Incapsula-walled) — split
# from the old composite tick (120s hard-kill). Expected to fail politely
# until the node1 home-IP path runs; errors are surfaced, not hidden.
cd /opt/data/gets-scraper || { echo "mbie-bulk: cannot cd"; exit 1; }
OUT=$(PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright /opt/data/parliament-scraper/.venv/bin/python mbie_bulk_fetch.py --time-budget 55 2>&1)
RC=$?
if [ $RC -ne 0 ]; then echo "mbie-bulk exited $RC:"; echo "$OUT"; exit 1; fi
ADDED=$(echo "$OUT" | grep -oP 'added=\K[0-9]+' | awk '{s+=$1} END {print s}')
if [ "${ADDED:-0}" -gt 0 ]; then echo "mbie-bulk: ${ADDED} rows added."; echo "$OUT"; fi
exit 0
