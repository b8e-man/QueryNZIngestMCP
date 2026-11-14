#!/usr/bin/env bash
# News collector tick (chunked, resumable). The estate asked for estate-news
# at the outlets' daily cadence (ask estate-news@serve-67-from-2026-11-11).
# Each invocation sweeps a ROTATING CHUNK of the runnable registry (state:
# .tick_rotation) so a run always fits the no_agent script cap and a kill
# costs only the in-flight chunk; hourly runs rotate the full fleet well
# inside a day. Per-source wall-clock bound (timeout + run.py's own
# NWS_SOURCE_TIMEOUT) keeps one hung outlet from eating the window.
# Quiet when nothing landed and nothing failed.
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
. /opt/data/evs-credentials/stuff.env
set +a
cd /opt/data/news-scrapers/ingestion || exit 1

STATE=/opt/data/news-scrapers/ingestion/.tick_rotation
CHUNK=${NWS_CHUNK:-5}
SRC_TIMEOUT=${NWS_SRC_TIMEOUT:-300}
export PLAYWRIGHT_BROWSERS_PATH=/opt/data/.cache/ms-playwright

LIST=$(../.venv/bin/python -m newsscrapers.run --status 2>/dev/null | awk '$1=="RUN"{print $2}')
[ -z "$LIST" ] && { echo "news tick: no runnable sources"; exit 1; }
mapfile -t ALL <<< "$LIST"
N=${#ALL[@]}
IDX=$(cat "$STATE" 2>/dev/null || echo 0)
case "$IDX" in (*[!0-9]*|"") IDX=0;; esac
[ "$IDX" -ge "$N" ] && IDX=0

SUM=""
RAN=0
LANDED=0
ERRS=0
i=0
while [ "$i" -lt "$CHUNK" ] && [ "$i" -lt "$N" ]; do
  NAME=${ALL[$(( (IDX + i) % N ))]}
  RES=$(timeout "$SRC_TIMEOUT" ../.venv/bin/python -m newsscrapers.run \
        --source "$NAME" --hours 30 --limit 250 2>&1)
  RC=$?
  F=$(echo "$RES" | grep -oE 'fetched=[0-9]+' | tail -1 | grep -oE '[0-9]+')
  E=$(echo "$RES" | grep -oE 'errors=[0-9]+' | tail -1 | grep -oE '[0-9]+')
  LANDED=$(( LANDED + ${F:-0} ))
  ERRS=$(( ERRS + ${E:-0} ))
  RAN=$(( RAN + 1 ))
  if [ "$RC" -ne 0 ]; then
    SUM="$SUM
  $NAME rc=$RC: $(echo "$RES" | tail -1)"
    ERRS=$(( ERRS + 1 ))
  fi
  i=$(( i + 1 ))
done
echo $(( (IDX + RAN) % N )) > "$STATE"

if [ "$LANDED" -gt 0 ] || [ "$ERRS" -gt 0 ]; then
  echo "news tick chunk @$IDX/$N: sources=$RAN fetched=$LANDED errors=$ERRS$SUM"
fi
exit 0
