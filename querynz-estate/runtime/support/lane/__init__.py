"""The lane's contract (plan 1.9; docs/contracts/lane.md).

A lane is the code that captures one source and reads it into its register:
one lane, one source, one folder `registers/<lane>/`. It has, and the
check here looks for:

  spec.md        the five-line spec: owns, reads, publishes, its one outside
                 check, its scheduled jobs. Checked at every merge
  capture.py     how its documents arrive (one of the three cases of 1.10)
  read.py        the reading, run from the document profile, through the
                 reader contract; re-reads one document or one day's file alone
  tables.sql     its tables, in its own schema and its `_private` twin;
                 every table defined here and nowhere else
  publish.sql    its published views in `pub`
  check.py       its one figure checked against the outside world
  sample.list     the documents and keys its tests need: hashes and keys only
  pane.md        how its rows appear in a pane of the board
  tests/         its tests; the fast tier runs them on the sample

and at run time a catch log (one line per item it could not process, with
the stage and the reason) and a run record (support.jobrun). Items in equal
items out plus items set aside.

`check_folder(path)` returns the problems as plain lines. The merge gate
runs it on every lane the branch touches (step 1b wires it).
"""
import os
import re

PIECES = ("spec.md", "capture.py", "read.py", "tables.sql", "publish.sql", "check.py", "sample.list", "pane.md")
SPEC_LINES = ("owns", "reads", "publishes", "outside check", "jobs")
_HASH_OR_KEY = re.compile(r"^(#.*|[0-9a-f]{64}(\s+\S.*)?|key:\s*\S.*)$")


def check_spec(text: str) -> list:
    """Five lines, each starting with its heading word and a colon."""
    out = []
    lines = [l.strip() for l in (text or "").splitlines() if l.strip() and not l.startswith("#")]
    for want in SPEC_LINES:
        if not any(l.lower().startswith(want + ":") for l in lines):
            out.append(f"spec.md has no `{want}:` line")
    if len(lines) > 12:
        out.append(f"spec.md is {len(lines)} lines; five is the shape")
    return out


def check_sample(text: str) -> list:
    """Hashes and keys only: no bytes, no rows, no personal data."""
    out = []
    for i, line in enumerate((text or "").splitlines(), 1):
        if line.strip() and not _HASH_OR_KEY.match(line.strip()):
            out.append(f"sample.list:{i}: not a sha256 or a `key:` line")
    return out


def check_folder(path: str) -> list:
    out = []
    name = os.path.basename(path.rstrip("/"))
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        out.append(f"lane folder `{name}` is not a schema name")
    for p in PIECES:
        if not os.path.isfile(os.path.join(path, p)):
            out.append(f"{name}: missing {p}")
    if not os.path.isdir(os.path.join(path, "tests")):
        out.append(f"{name}: missing tests/")
    spec = os.path.join(path, "spec.md")
    if os.path.isfile(spec):
        out += [f"{name}: {p}" for p in check_spec(open(spec, encoding="utf-8").read())]
    sample = os.path.join(path, "sample.list")
    if os.path.isfile(sample):
        out += [f"{name}: {p}" for p in check_sample(open(sample, encoding="utf-8").read())]
    tables = os.path.join(path, "tables.sql")
    if os.path.isfile(tables):
        sql = open(tables, encoding="utf-8").read()
        for m in re.finditer(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)\.", sql, re.I):
            if m.group(1) not in (name, name + "_private"):
                out.append(f"{name}: tables.sql creates a table in `{m.group(1)}`, not its own schema")
    return out
