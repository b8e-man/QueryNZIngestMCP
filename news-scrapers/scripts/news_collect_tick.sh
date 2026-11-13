#!/usr/bin/env bash
# Daily news collector (the estate asked for estate-news at the outlets'
# daily cadence; ask estate-news@serve-67-from-2026-11-11). Runs the
# newsscrapers fleet over the last 30h window; quiet when nothing landed.
set -u
# subscriber logins (the estate's handed-over creds, 2026-11-11) — lifts
# businessdesk (paywall), nbr (login) and newsroom (Jetpack SSO form login,
# automated + verified 2026-11-11 with the corrected password; state mints
# to newsroom_state.json). Values never leave /opt/data/evs-credentials
# (600).
set -a
. /opt/data/evs-credentials/newsscrapers.env
. /opt/data/evs-credentials/odt.env
. /opt/data/evs-credentials/newsroom.env
. /opt/data/evs-credentials/nzme.env
set +a
cd /opt/data/news-scrapers/ingestion || exit 1
OUT=$(PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright \
  ../.venv/bin/python -m newsscrapers.run --hours 30 --limit 250 2>&1)
RC=$?
LANDED=$(echo "$OUT" | grep -oE 'fetched=[0-9]+' | tail -1 | grep -oE '[0-9]+')
ERRS=$(echo "$OUT" | grep -oE 'errors=[0-9]+' | tail -1 | grep -oE '[0-9]+')
if [ "$RC" -ne 0 ]; then
  echo "news tick exited $RC:"
  echo "$OUT" | tail -5
  exit 1
fi
if [ "${LANDED:-0}" -gt 0 ] || [ "${ERRS:-0}" -gt 0 ]; then
  echo "news tick: $OUT" | tail -3
fi
exit 0
