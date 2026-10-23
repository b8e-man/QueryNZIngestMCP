#!/usr/bin/env bash
# Watchdog: keep the Query NZ Ingest MCP server (port 8646) alive.
# Silent when healthy; one line only when it had to act.
set -u

if curl -sf -m 4 http://127.0.0.1:8646/health >/dev/null 2>&1; then
  exit 0
fi

if pgrep -f "qnz-mcp/server.py" >/dev/null 2>&1; then
  echo "qnz-mcp process up but :8646/health down @ $(date '+%H:%M:%S')"
  exit 0
fi

setsid /opt/data/qnz-mcp/.venv/bin/python /opt/data/qnz-mcp/server.py \
  >> /opt/data/qnz-mcp/server.log 2>&1 < /dev/null &
sleep 2
if curl -sf -m 4 http://127.0.0.1:8646/health >/dev/null 2>&1; then
  echo "qnz-mcp was down — restarted @ $(date '+%Y-%m-%d %H:%M:%S')"
else
  echo "qnz-mcp was down and restart FAILED — see /opt/data/qnz-mcp/server.log"
fi
