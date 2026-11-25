#!/usr/bin/env bash
# authors capture tick — estate-news-authors-2026-11-15 lane.
# Rotating chunk over the estate-news host list; slow polite pace in the
# collector; weekly refresh; challenges never re-hammered. Quiet when
# nothing landed and nothing failed.
set -u
cd /opt/data/news-scrapers/ingestion || exit 1
PY=/opt/data/news-scrapers/.venv/bin/python
STATE=/opt/data/news-scrapers/data-authors/.tick_rotation
CHUNK=${AUTHORS_CHUNK:-8}
RES=""
i=0
HOSTS=$(ls /opt/data/news-scrapers/data)
N=$(echo "$HOSTS" | wc -l)
IDX=$(cat "$STATE" 2>/dev/null || echo 0)
case "$IDX" in (*[!0-9]*|"") IDX=0;; esac
[ "$IDX" -ge "$N" ] && IDX=0
mapfile -t ALL <<< "$HOSTS"
OUT=""
while [ "$i" -lt "$CHUNK" ] && [ "$i" -lt "$N" ]; do
  H=${ALL[$(( (IDX + i) % N ))]}
  R=$(timeout 300 "$PY" authors_capture.py --host "$H" --budget 6 2>&1 | tail -1)
  case "$R" in
    *"found=0 captured=0 errors=0") ;;
    *) OUT="$OUT
  $H: $R" ;;
  esac
  i=$(( i + 1 ))
done
echo $(( (IDX + CHUNK) % N )) > "$STATE"
if [ -n "$OUT" ]; then
  echo "authors tick @$IDX/$N:$OUT"
fi
exit 0
