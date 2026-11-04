"""The capture scheduler: fires the estate's capture jobs on the estate's own
timetable, here on this box.

The job catalogue is the estate's `support/scheduler/jobs.toml` — command,
`at_utc` time and `enabled` are read from it at every start, so the
handover's schedule stays the single source of truth. Runs are fired as
subprocesses at their UTC time (their once-nightly pattern), one per lane,
parallel across lanes (each lane talks to its own hosts; the fetch gate
paces per host and holds refused hosts). Each run holds a per-lane flock so
a scheduled run and a manual run never overlap. The lanes write their own
run records to <live>/checks/runs.jsonl (support.jobrun); this scheduler
appends alerts (a crash, or a new gate hold) to <live>/alerts.txt for the
watchdog to deliver.

    python scheduler.py            # run until stopped
    python scheduler.py --list     # what is scheduled
    python scheduler.py --run NAME # fire one job now
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.environ.get("QV4_LIVE") or os.path.join(HERE, "live")
JOBS_TOML = os.path.join(HERE, "support", "scheduler", "jobs.toml")
LOCKDIR = os.path.join(HERE, "locks")
LOGDIR = os.path.join(LIVE, "logs")
ALERTS = os.path.join(LIVE, "alerts.txt")
REFUSALS = os.path.join(LIVE, "checks", "fetch-gate", "refusals.jsonl")
PY = os.path.join(HERE, ".venv", "bin", "python")

ENV = dict(os.environ,
           QV4_LIVE=LIVE,
           QV4_DOCS=os.environ.get("QV4_DOCS") or "/opt/data/querynz-estate/store",
           QV4_SOURCES=os.environ.get("QV4_SOURCES") or "/opt/data/querynz-estate/sources",
           QV4_POSITIONS=os.environ.get("QV4_POSITIONS")
           or os.path.join(HERE, "docs", "legal", "positions"),
           DISPLAY=os.environ.get("DISPLAY") or ":99",
           PLAYWRIGHT_BROWSERS_PATH="/opt/data/.cache/ms-playwright")

#: the handover's capture jobs, in firing order. The courts lane covers
#: sources courts-jdo + courts-finder (--jdo) and courts-era (--era); the
#: council procurement watch stays off (its ruling).
WANTED = [
    "qv4-courts-jdo-capture",
    "qv4-courts-era-capture",
    "qv4-building-practitioners-register-capture",
    "qv4-local-elections-listings",
    "qv4-council-minutes-capture",
    "qv4-tenancy-tribunal-capture",
    "qv4-commerce-commission-capture",
    "qv4-grants-capture",
    "qv4-local-elections-files",
    "qv4-building-practitioners-capture",
    "qv4-real-estate-authority-capture",
    "qv4-fma-capture",
    "qv4-charities-capture",
    "qv4-worksafe-capture",
    "qv4-settlement-commitments-watch",
    "qv4-council-procurement-watch",
    "qv4-councillor-interests-capture",
    "qv4-iwi-directory-capture",
]


def load_jobs():
    with open(JOBS_TOML, "rb") as f:
        catalog = tomllib.load(f)["jobs"]
    out = {}
    for name in WANTED:
        j = catalog.get(name)
        if not j:
            continue
        if not j.get("enabled", True):
            continue
        times = j.get("at_utc")
        if isinstance(times, str):
            times = [times]
        out[name] = {"command": j.get("command"), "at_utc": list(times or [])}
    # the elections.nz lanes: the estate's v4 code only adopted its old
    # browser's downloads; this is the live headed-browser walk
    # (elections_nz.py, Arthur 2026-11-05: "let's get them all. just take
    # it easy if they refuse")
    out["local-candidate-returns"] = {
        "command": ["python", "elections_nz.py", "--lane", "candidate_returns",
                    "--budget-s", "3600"],
        "at_utc": ["09:40"]}
    out["local-disclosures"] = {
        "command": ["python", "elections_nz.py", "--lane", "disclosures",
                    "--budget-s", "3600"],
        "at_utc": ["09:45"]}
    return out


def alert(line: str):
    os.makedirs(LIVE, exist_ok=True)
    with open(ALERTS, "a", encoding="utf-8") as f:
        f.write(dt.datetime.now().astimezone().isoformat(timespec="seconds")
                + "  " + line + "\n")


def n_refusals() -> int:
    try:
        with open(REFUSALS, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def run_one(name: str, spec: dict):
    os.makedirs(LOCKDIR, exist_ok=True)
    os.makedirs(LOGDIR, exist_ok=True)
    lock = open(os.path.join(LOCKDIR, name + ".lock"), "w")
    try:
        import fcntl
        if not fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB):
            print(f"{name}: already running; not fired")
            return
    except ImportError:
        pass
    cmd = list(spec["command"])
    if cmd and cmd[0] == "python":
        cmd[0] = PY
    started = dt.datetime.now().astimezone()
    before = n_refusals()
    logp = os.path.join(LOGDIR, name + ".log")
    try:
        with open(logp, "a", encoding="utf-8") as log:
            log.write(f"--- {started.isoformat(timespec='seconds')}\n")
            log.flush()
            p = subprocess.run(cmd, cwd=HERE, env=ENV, stdout=log,
                               stderr=subprocess.STDOUT, timeout=23 * 3600)
        code = p.returncode
    except Exception as exc:  # noqa: BLE001 — a scheduler crash is an alert
        code = -1
        alert(f"{name}: scheduler could not run it ({type(exc).__name__}: {str(exc)[:200]})")
    after = n_refusals()
    if after > before:
        alert(f"{name}: blocked")
    if code != 0:
        alert(f"{name}: run failed (exit {code})")
    print(f"{name}: exit {code}, {after - before} new holds")


def main(argv):
    jobs = load_jobs()
    if "--list" in argv:
        for name, spec in jobs.items():
            print(name, spec["at_utc"], " ".join(spec["command"]))
        return 0
    if "--run" in argv:
        name = argv[argv.index("--run") + 1]
        run_one(name, jobs[name])
        return 0
    last = {}
    print(f"scheduler up: {len(jobs)} jobs")
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        for name, spec in jobs.items():
            for hhmm in spec["at_utc"]:
                hh, mm = hhmm.split(":")
                fire = now.replace(hour=int(hh), minute=int(mm), second=0,
                                   microsecond=0)
                if now >= fire and last.get(name, dt.datetime.min.replace(
                        tzinfo=dt.timezone.utc)) < fire:
                    last[name] = now
                    print(f"firing {name} at {hhmm} UTC")
                    run_one(name, spec)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
