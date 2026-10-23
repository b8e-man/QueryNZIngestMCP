#!/usr/bin/env bash
# Watchdog: keep `hermes proxy start` (Nous auth proxy for external scripts,
# port 8645) alive. Silent when healthy; one line only when it had to act.
# Scripts MUST use this proxy for LLM calls — never call the portal refresh
# endpoint directly (single-use refresh tokens; reuse revokes the session).
set -u

if curl -sf -m 4 http://localhost:8645/health >/dev/null 2>&1; then
  exit 0
fi

if pgrep -f "hermes proxy start" >/dev/null 2>&1; then
  echo "hermes proxy process up but :8645/health down @ $(date '+%H:%M:%S')"
  exit 0
fi

setsid /opt/hermes/.venv/bin/hermes proxy start --provider nous \
  --host 127.0.0.1 --port 8645 >> /opt/data/hermes_proxy.log 2>&1 < /dev/null &
sleep 2
if curl -sf -m 4 http://localhost:8645/health >/dev/null 2>&1; then
  echo "hermes proxy was down — restarted @ $(date '+%Y-%m-%d %H:%M:%S')"
else
  echo "hermes proxy was down and restart FAILED — see /opt/data/hermes_proxy.log"
fi
