#!/bin/bash
# Estate capture watchdog: restart the scheduler if it is dead, deliver any
# alerts it raised. Silent when all is well (empty stdout = no message).
cd /opt/data/querynz-estate/runtime || exit 1
pgrep -x Xvfb >/dev/null || setsid Xvfb :99 -screen 0 1280x900x24 >/dev/null 2>&1 &
if ! pgrep -f 'python scheduler.py' >/dev/null; then
  setsid nohup .venv/bin/python scheduler.py >> live/logs/scheduler.log 2>&1 &
  sleep 2
  echo "estate capture: scheduler was dead, restarted"
fi
if [ -s live/alerts.txt ]; then
  echo "estate capture:"
  cat live/alerts.txt
  : > live/alerts.txt
fi
