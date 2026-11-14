#!/usr/bin/env python3
"""Fresh-recent trial for every estate lane: tiny budget, --anytime (the
estate's own 'by hand: a proof' hook), one at a time. Logs one summary line
per lane to trial_results.txt. Nothing here forces past a refusal: the lanes
stop themselves on a failed read and the gate holds the host."""
import os, subprocess, time, json

RUNTIME = "/opt/data/querynz-estate/runtime"
PY = os.path.join(RUNTIME, ".venv", "bin", "python")
SOURCES = "/opt/data/querynz-estate/sources"
RESULTS = os.path.join(RUNTIME, "trial_results.txt")

ENV = dict(os.environ,
           QV4_LIVE=os.path.join(RUNTIME, "live"),
           QV4_DOCS="/opt/data/querynz-estate/store",
           QV4_SOURCES=SOURCES,
           QV4_POSITIONS=os.path.join(RUNTIME, "docs", "legal", "positions"),
           DISPLAY=":99",
           PLAYWRIGHT_BROWSERS_PATH="/opt/data/.cache/ms-playwright")

LANES = [
    ("bp-decisions",       ["-m", "registers.building_practitioners.capture", "--anytime", "--budget-s", "60", "--max-pages", "4"]),
    ("bp-register",        ["-m", "registers.building_practitioners.capture", "--register", "--anytime", "--budget-s", "60"]),
    ("charities",          ["-m", "registers.charities.capture", "--anytime", "--budget-s", "60", "--max-pages", "3"]),
    ("commerce_commission",["-m", "registers.commerce_commission.capture", "--anytime", "--budget-s", "60", "--max-pages", "3"]),
    ("council_minutes",    ["-m", "registers.council_minutes.capture", "--anytime", "--budget-s", "60", "--max-docs", "3"]),
    ("council_procurement",["-m", "registers.council_procurement.capture", "--anytime"]),
    ("councillor_interests",["-m", "registers.councillor_interests.capture", "--anytime", "--budget-s", "60"]),
    ("courts-jdo",         ["-m", "registers.courts.own", "--jdo", "--anytime", "--max-requests", "8", "--budget-s", "60"]),
    ("courts-era",         ["-m", "registers.courts.own", "--era", "--anytime", "--max-requests", "8", "--budget-s", "60"]),
    ("elections-candidate-returns", ["elections_nz.py", "--lane", "candidate_returns", "--budget-s", "60"]),
    ("elections-disclosures",       ["elections_nz.py", "--lane", "disclosures", "--budget-s", "60"]),
    ("fma",                ["-m", "registers.fma.capture", "--anytime", "--budget-s", "60", "--max-pages", "3"]),
    ("grants",             ["-m", "registers.grants.capture", "--anytime", "--budget-s", "60", "--max-requests", "12"]),
    ("iwi_directory",      ["-m", "registers.iwi_directory.capture", "--anytime", "--budget-s", "60", "--max-pages", "8"]),
    ("local_elections-listings", ["-m", "registers.local_elections.capture", "listings", "--anytime", "--budget-s", "60"]),
    ("local_elections-files",    ["-m", "registers.local_elections.capture", "files", "--anytime", "--budget-s", "60", "--max-files", "2"]),
    ("real_estate_authority",["-m", "registers.real_estate_authority.capture", "--anytime", "--budget-s", "60", "--max-items", "30"]),
    ("settlement_commitments",["-m", "registers.settlement_commitments.capture", "--anytime"]),
    ("tenancy_tribunal",   ["-m", "registers.tenancy_tribunal.capture", "--anytime", "--budget-s", "60", "--max-items", "30"]),
    ("worksafe",           ["-m", "registers.worksafe.capture", "--anytime", "--budget-s", "60", "--max-pages", "3"]),
]

def manifest_count():
    counts = {}
    for name in sorted(os.listdir(SOURCES)):
        m = os.path.join(SOURCES, name, "manifest.jsonl")
        try:
            with open(m, "rb") as f:
                counts[name] = sum(1 for _ in f)
        except OSError:
            pass
    return counts

out = []
before = manifest_count()
out.append(("baseline", json.dumps(before)))
print("BASELINE", json.dumps(before), flush=True)

for name, args in LANES:
    t0 = time.time()
    try:
        p = subprocess.run([PY] + args, cwd=RUNTIME, env=ENV,
                           capture_output=True, text=True, timeout=150)
        tail = (p.stdout or "")[-400:].replace("\n", " | ")
        line = f"{name}\texit={p.returncode}\t{int(time.time()-t0)}s\t{tail}"
        if p.returncode != 0 and p.stderr:
            line += " || ERR " + p.stderr[-200:].replace("\n", " | ")
    except subprocess.TimeoutExpired:
        line = f"{name}\tTIMEOUT\t{int(time.time()-t0)}s"
    out.append((name, line))
    print(line, flush=True)

after = manifest_count()
delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
print("MANIFEST_DELTA", json.dumps(delta), flush=True)
out.append(("delta", json.dumps(delta)))

with open(RESULTS, "w", encoding="utf-8") as f:
    for _, line in out:
        f.write(line + "\n")
print("DONE", flush=True)
