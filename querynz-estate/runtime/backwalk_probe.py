#!/usr/bin/env python3
"""Backwalk test steps: one bounded HISTORICAL step per lane that has not
gathered all history, to prove the fill path end to end. Same politeness as
the trials: --anytime is the estate's supervised-proof hook; every lane stops
itself at its request cap; a refusal stops it and holds the host."""
import os, subprocess, time, json

RUNTIME = "/opt/data/querynz-estate/runtime"
PY = os.path.join(RUNTIME, ".venv", "bin", "python")
ENV = dict(os.environ,
           QV4_LIVE=os.path.join(RUNTIME, "live"),
           QV4_DOCS="/opt/data/querynz-estate/store",
           QV4_SOURCES="/opt/data/querynz-estate/sources",
           QV4_POSITIONS=os.path.join(RUNTIME, "docs", "legal", "positions"),
           DISPLAY=":99",
           PLAYWRIGHT_BROWSERS_PATH="/opt/data/.cache/ms-playwright")

PROBES = [
    # courts JDO back catalogue, a historical year the walk has not reached
    ("backwalk-jdo-2005", ["-m", "registers.courts.own", "--jdo", "--year", "2005",
                           "--court", "High Court", "--anytime", "--max-requests", "4", "--budget-s", "90"]),
    # ERA determinations, its earliest year band
    ("backwalk-era-2000", ["-m", "registers.courts.own", "--era", "--year", "2000",
                           "--anytime", "--max-requests", "4", "--budget-s", "90"]),
    # the Ministry's decisions finder (tranche 2), one trial step
    ("backwalk-finder", ["-m", "registers.courts.own", "--finder",
                         "--anytime", "--max-requests", "4", "--budget-s", "90"]),
]

out = []
for name, args in PROBES:
    t0 = time.time()
    try:
        p = subprocess.run([PY] + args, cwd=RUNTIME, env=ENV,
                           capture_output=True, text=True, timeout=150)
        tail = (p.stdout or "")[-500:].replace("\n", " | ")
        line = f"{name}\texit={p.returncode}\t{int(time.time()-t0)}s\t{tail}"
        if p.returncode != 0 and p.stderr:
            line += " || ERR " + p.stderr[-200:].replace("\n", " | ")
    except subprocess.TimeoutExpired:
        line = f"{name}\tTIMEOUT\t{int(time.time()-t0)}s"
    out.append(line)
    print(line, flush=True)

with open(os.path.join(RUNTIME, "backwalk_results.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
print("DONE", flush=True)
