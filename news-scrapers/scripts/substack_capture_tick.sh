#!/usr/bin/env bash
# substack capture tick — estate-substack forward lane
# (ask estate-substack@2026-11-18). Sweeps all 13 publications (archive
# listing + new free posts + falling comment re-captures); slow polite
# pace enforced in the collector. Quiet when nothing landed and nothing
# failed.
set -u
cd /opt/data/news-scrapers/ingestion || exit 1
PY=/opt/data/news-scrapers/.venv/bin/python

RES=$(timeout 480 "$PY" substack_capture.py --budget 20 2>&1)
RC=$?
LINE=$(echo "$RES" | tail -1)
ERRS=$(echo "$RES" | grep -c ": .*http [0-9]" || true)
case "$LINE" in
  *"records=0 errors=0") exit 0 ;;
esac
echo "substack tick: $LINE"
[ "$RC" -ne 0 ] && { echo "substack tick rc=$RC: $(echo "$RES" | tail -3)"; exit 1; }
exit 0
