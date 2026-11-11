"""ARCHIVE sweep for sources that publish a way into their back-catalogue.

    python -m newsscrapers.backwalk --source berl.co.nz
    python -m newsscrapers.backwalk --source scoop.co.nz --max-sitemaps 4 --limit 3000
    python -m newsscrapers.backwalk            # every source that declares an archive

Two ways a module declares its archive (2026-08-24, B11 ruling 28):
  * `discover_archive` — a hand-built coroutine (berl, motu, nzier: paged listings).
  * `ARCHIVE = {"index": <sitemap-index url>, "article_re": <regex or None>,
                "polite": <seconds>}` — the generic sitemap-index walker
    (genericrss.make_sitemap_archive_discover), oldest sub-sitemap first, with
    RESUME: sub-sitemaps fully collected are recorded in
    var/backwalk/<source>.json and skipped next run, so each invocation
    advances into the part of the archive we do not hold. `--max-sitemaps`
    bounds the listing fetches per run; `--limit` bounds article fetches
    (applied AFTER the pre-fetch dedup — base.run_source).

Reuses base.run_source verbatim — same politeness, same dedup, same parked
landing — with the module's discover swapped and the recency cutoff opened
right up. Idempotent: the pre-fetch URL dedup and content-hash dedup make a
re-run cost listing pages only. A coverage note per run lands in the state
file (runs: when, sitemaps walked, discovered, landed) — the record ruling
28 asks for ("per-source earliest post_date matches the archive floor").
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from . import base, genericrss
from .registry import REGISTRY

STATE_DIR = Path(__file__).resolve().parents[2] / "var" / "backwalk"


def load_state(source: str) -> dict:
    p = STATE_DIR / f"{source}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"source": source, "done": [], "runs": []}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{state['source']}.json").write_text(json.dumps(state, indent=1))


def completed_subsitemaps(walked: list[tuple[str, int]], limit: int) -> list[str]:
    """Which walked sub-sitemaps were FULLY fetched, given run_source's
    items[:limit] cut. `walked` is [(url, cumulative_discovered)] in walk order;
    a sub-sitemap is complete iff its cumulative count is within `limit` (dedup
    only removes urls, so pre-dedup cumulative <= limit guarantees fully
    fetched). Sub-sitemaps past the cut stay open — never marked done unfetched."""
    return [sub for sub, cum in walked if cum <= limit]


def stall_report(walked: list[tuple[str, int]], limit: int, prev_open: str | None) -> str | None:
    """L1611 (2026-08-24): the walk is STALLED when the first still-open
    (limit-cut) sub-sitemap this run is the SAME one left open last run — its
    own article count exceeds --limit, so no run at this limit will ever mark
    it done and the resume silently never advances (times.co.nz/stoppress
    stalled at 0 this way). Returns the log line, or None."""
    prev_cum = 0
    for sub, cum in walked:
        if cum > limit:
            if sub == prev_open:
                own = cum - prev_cum
                return (f"STALL: sub-sitemap {sub} has {own}>{limit} articles — "
                        f"it can never complete at this --limit; raise it")
            return None                 # cut, but a different sub: progress
        prev_cum = cum
    return None


def _archive_shim(mod, discover):
    ns = {k: getattr(mod, k) for k in dir(mod) if not k.startswith("_")}
    ns["discover"] = discover
    return SimpleNamespace(**ns)


def archive_discover(mod, source: str, state: dict, max_sitemaps: int | None):
    """The discover coroutine for a module's archive, or None if it has none."""
    if hasattr(mod, "discover_archive"):
        return mod.discover_archive
    spec = getattr(mod, "ARCHIVE", None)
    if not spec:
        return None
    done = set(state.get("done", []))
    walked: list[tuple[str, int]] = []          # (sub-sitemap url, cumulative discovered)

    def progress(sub: str, cumulative: int) -> None:
        walked.append((sub, cumulative))

    def census(total: int, remaining: int) -> None:
        state["_census"] = {"index_total": total, "remaining": remaining}

    state["_walked"] = walked
    return genericrss.make_sitemap_archive_discover(
        spec["index"], spec.get("article_re"), sitemap_re=spec.get("sitemap_re"),
        polite=spec.get("polite", getattr(mod, "POLITE_SLEEP", base.POLITE_SLEEP)),
        oldest_first=spec.get("oldest_first", True),
        skip_done=lambda u: u in done, progress=progress, max_sitemaps=max_sitemaps,
        census=census)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="one registry key that declares an archive")
    ap.add_argument("--limit", type=int, default=3000, help="article fetches per run (after dedup)")
    ap.add_argument("--max-sitemaps", type=int, default=None, help="sub-sitemaps walked per run (ARCHIVE sources)")
    ap.add_argument("--reset", action="store_true", help="forget the resume state for --source")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    failures = 0
    for name, entry in REGISTRY.items():
        if args.source and name != args.source:
            continue
        mod = importlib.import_module(f"newsscrapers.{entry.module}")
        state = {"source": name, "done": [], "runs": []} if args.reset else load_state(name)
        disc = archive_discover(mod, name, state, args.max_sitemaps)
        if disc is None:
            if args.source:
                print(f"== {name}: no discover_archive / ARCHIVE — nothing to walk")
                return 1
            continue
        print(f"== {name} ARCHIVE walk (polite {getattr(mod, 'POLITE_SLEEP', base.POLITE_SLEEP)}s; "
              f"{len(state['done'])} sub-sitemaps already done)")
        try:
            stats = await base.run_source(_archive_shim(mod, disc), hours=24 * 365 * 30,
                                          limit=args.limit, dry=args.dry)
            print(f"   {stats}")
            walked = state.pop("_walked", [])
            cen = state.pop("_census", None)
            if cen:
                # C313: say how much is LEFT. Without the denominator this
                # lane had run 378 times and could not answer "when does it
                # finish", although the index it fetches every run knows:
                # `len(subs)` was computed and discarded. The rate IS measured
                # (9 sub-sitemaps per run x 12 runs a day = 108 days of archive
                # per day of wall clock, 2026-10-06), so the total is the only
                # missing term — and this line supplies it from the next tick on.
                done_n, total = len(state["done"]), cen["index_total"]
                print(f"   index: {done_n:,} of {total:,} sub-sitemaps done "
                      f"({done_n / max(total, 1):.1%}), {cen['remaining']:,} to go")
            if not args.dry:
                # A sub-sitemap is DONE only if EVERY url it listed was inside
                # this run's fetch window. run_source sets discovered = the total
                # across all walked sub-sitemaps (pre-dedup), then fetches the
                # first `limit` (post-dedup, in sub-sitemap order). Dedup only
                # REMOVES already-held urls, so a sub-sitemap whose CUMULATIVE
                # discovered count is <= limit is guaranteed fully fetched; one
                # whose cumulative exceeds limit was tail-cut and stays open.
                # (The old rule `walked[:-1]` wrongly marked every-but-the-last
                # done — dropping whole tail sub-sitemaps into skip_done forever
                # when a cut spanned more than one; code-audit finding 2026-08-24.)
                complete = completed_subsitemaps(walked, args.limit)
                stall = stall_report(walked, args.limit, state.get("open"))
                if stall:
                    print(f"   {stall}")
                opens = [s for s, c in walked if c > args.limit]
                state["open"] = opens[0] if opens else None
                state["done"] = sorted(set(state["done"]) | set(complete))
                state["runs"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "sitemaps_walked": len(walked), "sub_sitemaps_completed": len(complete),
                                      **(cen or {}),
                                      "open": state["open"], "stall": bool(stall), "stats": stats})
                save_state(state)
        except Exception as e:  # noqa: BLE001 — one archive must not kill the rest
            print(f"   ARCHIVE WALK FAILED: {type(e).__name__}: {e}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
