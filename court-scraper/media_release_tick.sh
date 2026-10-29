#!/bin/bash
# Media release lane tick — courtsofnz communications (NOT judgments).
# Own doc type: kind=media_release, pdfs/media-releases/. Silent on no news.
cd /opt/data/court-scraper || { echo "media-lane: cannot cd"; exit 1; }
OUT=$(python3 media_release_discover.py 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  echo "media-lane exited $RC:"; echo "$OUT"; exit 1
fi
[ -n "$OUT" ] && echo "$OUT"
exit 0
