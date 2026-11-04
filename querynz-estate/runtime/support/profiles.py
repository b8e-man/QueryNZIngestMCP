"""Document profiles (the estate's reading profiles), rebuilt for capture.

The estate's `support.profiles` served the profile ledger its readers and
extractors use; only the lanes' proposed profiles were handed over
(`profiles-proposed.jsonl` beside each lane). This module keeps the contract
the lanes call — `profiles.profile(slug)` / `profiles.profile(slug, path=...)`
returns the newest profile dict for the slug, or None:

  1. the explicit `path` (a lane's proposed lines), then
  2. `runtime/profiles-data/*.jsonl` (a ledger an operator can drop lines in).

The estate's own readers use its own profiles module against its own ledger.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.environ.get("QV4_PROFILES") or os.path.join(
    os.path.dirname(HERE), "profiles-data")


def _load(path: str):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def profile(slug: str, path: str = None, **kw):
    """The newest profile for `slug` (by `version`), or None."""
    paths = []
    if path:
        paths.append(path)
    if os.path.isdir(LEDGER):
        for name in sorted(os.listdir(LEDGER)):
            if name.endswith(".jsonl"):
                paths.append(os.path.join(LEDGER, name))
    best = None
    for p in paths:
        for rec in _load(p):
            if rec.get("slug") == slug:
                if best is None or (rec.get("version") or 0) > (best.get("version") or 0):
                    best = rec
    return best
