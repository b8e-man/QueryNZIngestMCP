"""Run records for `qv4-` jobs (plan: "Shared things on the boxes": every
scheduled job has a record of each run).

One line per run, appended to `<live>/checks/runs.jsonl`: the job, the box,
when it started and ended, whether it was ok, one line of detail, and any
figures the job wants kept (a peak, a count). Step 2's scheduler moves this
into its own tables; until then the file is the record and the board reads
it. Stdlib only."""
import datetime as dt
import json
import os
import socket

LIVE = os.environ.get("QV4_LIVE") or "/home/user/querynzv4-work/live"
RUNS = os.path.join(LIVE, "checks", "runs.jsonl")


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def record(job: str, ok: bool, detail: str, started: dt.datetime, extra: dict = None, path: str = None) -> dict:
    ended = now()
    rec = {"job": job, "host": socket.gethostname(), "started": started.isoformat(timespec="seconds"),
           "ended": ended.isoformat(timespec="seconds"),
           "seconds": round((ended - started).total_seconds(), 1), "ok": bool(ok), "detail": detail}
    if extra:
        rec.update(extra)
    path = path or RUNS
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def last_run(job: str, path: str = None) -> dict:
    """The newest record for a job, or None."""
    path = path or RUNS
    out = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("job") == job:
                    out = rec
    except OSError:
        return None
    return out
