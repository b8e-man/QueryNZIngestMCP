#!/usr/bin/env bash
# comments capture tick — estate-comments forward lane
# (ask estate-news-comments@2026-11-18). Rotating chunk over the 18 proven
# hosts so each run fits the no_agent window; slow polite pace is enforced
# in the collector (4s between fetches). Quiet when nothing landed and
# nothing failed.
set -u
cd /opt/data/news-scrapers/ingestion || exit 1
PY=/opt/data/news-scrapers/.venv/bin/python

STATE=/opt/data/news-scrapers/data-comments/.tick_rotation
CHUNK=${COMMENTS_CHUNK:-6}
BUDGET=${COMMENTS_BUDGET:-8}

HOSTS=$($PY - <<'EOF'
import comments_capture as cc
print("\n".join(sorted(cc.HOST_FAMILY)))
EOF
)
[ -z "$HOSTS" ] && { echo "comments tick: no hosts"; exit 1; }
mapfile -t ALL <<< "$HOSTS"
N=${#ALL[@]}
IDX=$(cat "$STATE" 2>/dev/null || echo 0)
case "$IDX" in (*[!0-9]*|"") IDX=0;; esac
[ "$IDX" -ge "$N" ] && IDX=0

OUT=""
i=0
while [ "$i" -lt "$CHUNK" ] && [ "$i" -lt "$N" ]; do
  H=${ALL[$(( (IDX + i) % N ))]}
  RES=$(timeout 480 "$PY" comments_capture.py --host "$H" --budget "$BUDGET" 2>&1)
  LINE=$(echo "$RES" | tail -1)
  case "$LINE" in
    *"captured=0 errors=0") ;;
    *) OUT="$OUT
  $H: $LINE" ;;
  esac
  i=$(( i + 1 ))
done
echo $(( (IDX + CHUNK) % N )) > "$STATE"
if [ -n "$OUT" ]; then
  echo "comments tick @$IDX/$N:$OUT"
fi
exit 0
