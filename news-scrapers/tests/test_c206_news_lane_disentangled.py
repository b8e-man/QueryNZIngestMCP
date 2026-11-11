"""C206: five dead modules kept each other alive in the news package.

The card: *"News-API code disentanglement (daywalker/backfill_era/reassess/client dead;
split live DB helpers)."*

THE LANE ITSELF WAS RETIRED WITH #129 ON 2026-08-28 and `newsscrapers.run` replaced it.
The modules then sat in `ingestion/news/` for six weeks **importing each other** —
`backfill_era` → `daywalker` → `ingest` → `client` — which is what made the package look
live. `first-run.sh` called `news.ingest` behind `|| true` until 2026-09-19, so a fresh
box ran a retired lane, failed, and said nothing.

THE CARD NAMED FOUR AND THERE WERE FIVE: `news/ingest.py` is dead too. Censused
2026-10-08, every import of `news.*` from outside the package:

    review_sources  -> courts/extract, newsscrapers/base, pdfpipe/materialize, a test
    extract         -> ingestion/extract_all.py
    reconcile_ledger-> ops/production/extract-tick.sh
    client / ingest / daywalker / backfill_era / reassess -> NOTHING outside the five

So there were no live DB helpers trapped in the dead modules — the card's second half
turned out to be empty, which is worth saying because "split the live helpers out" was
the reason it had been deferred.

WHAT THE RETIREMENT COST, AND WHERE THE RULE WENT. `test_backfill_era_dsn.py` pinned a
real rule on a dead module's helper: `V3_BACKLOG_DSN` beats `INCOMING_NEWS_URL`, because
on 2026-08-22 a unit moved to an EnvironmentFile connected to node2's read-only STANDBY
and died on its first INSERT. The rule now lives in `estate_dsn` — the first name the
environment sets, no default (ruling 308(a)). What `estate_dsn` does NOT gate is the
ORDER a caller passes the names in, and three live register derives pass
`INCOMING_NEWS_URL` first. That is C534, raised at this close rather than dropped.
"""
import pathlib
import re

import pytest

ING = pathlib.Path(__file__).resolve().parents[1]
REPO = ING.parent
RETIRED = ING / "retired"

#: the five, by the name they had when they were live
GONE = ("client", "ingest", "daywalker", "backfill_era", "reassess")
#: and the three that stayed, each with the consumer that runs it
LIVE = {
    "review_sources": "newsscrapers/base, courts/extract, pdfpipe/materialize",
    "extract": "ingestion/extract_all.py",
    "reconcile_ledger": "ops/production/extract-tick.sh",
}


@pytest.mark.parametrize("mod", GONE)
def test_the_dead_module_is_GONE_from_the_live_package(mod):
    assert not (ING / "news" / f"{mod}.py").exists(), (
        f"news/{mod}.py is back in the live package. If it was revived, name the "
        f"consumer that runs it and delete its row from data-layer/docs/RETIRED.md")


@pytest.mark.parametrize("mod", GONE)
def test_it_is_KEPT_in_retired_not_deleted(mod):
    """Ruling 157: retire means disabled, kept, soaked, never deleted."""
    assert (RETIRED / f"news_{mod}.py").exists(), f"news_{mod}.py is not in retired/"


@pytest.mark.parametrize("mod,consumer", sorted(LIVE.items()))
def test_the_live_module_is_STILL_THERE(mod, consumer):
    """The other half of the census. A disentanglement that took a live module with it
    is the failure this parametrisation exists for — `review_sources` alone is read by
    four callers outside the package."""
    assert (ING / "news" / f"{mod}.py").exists(), f"news/{mod}.py ({consumer}) is gone"


def test_NOTHING_LIVE_IMPORTS_any_of_the_five():
    """The property that makes the retirement real. `ops/retired_register.py --check`
    enforces this estate-wide; this says it in the package's own suite, where somebody
    editing the news lane will see it."""
    bad = []
    for f in sorted(REPO.rglob("*.py")):
        s = str(f.relative_to(REPO))
        if "/.venv/" in s or s.startswith("ingestion/retired/") or "/tests/" in s:
            continue
        txt = f.read_text(errors="ignore")
        for mod in GONE:
            for pat in (rf"^\s*from news\.{mod} import", rf"^\s*import news\.{mod}\b"):
                if re.search(pat, txt, re.M):
                    bad.append(f"{s} imports news.{mod}")
    assert not bad, bad


def test_the_PACKAGE_DOCSTRING_describes_what_is_there():
    """It described `client.py` and `ingest.py` and nothing else — the two most dead
    modules in the package — which is how the lane read as live to anyone who opened it."""
    doc = (ING / "news" / "__init__.py").read_text()
    for mod in LIVE:
        assert mod in doc, f"the package docstring does not name {mod}"
    assert "retired" in doc.lower() and "#129" in doc


@pytest.mark.skip(reason="handover gap 2026-11-09: data-layer/docs/RETIRED.md is "
                         "not in the pack (the packer chose by filename) — request "
                         "it from the integrator, then re-enable")
def test_the_RETIRED_REGISTER_carries_all_five():
    reg = (REPO / "data-layer" / "docs" / "RETIRED.md").read_text()
    for mod in GONE:
        assert f"`news_{mod}.py`" in reg, f"news_{mod}.py has no row in RETIRED.md"


@pytest.mark.skip(reason="handover gap 2026-11-09: retired/test_backfill_era_dsn.py"
                         ".retired is not in the pack — request it from the "
                         "integrator, then re-enable")
def test_the_orphaned_TEST_went_with_its_module_and_is_not_collected():
    """It imported `news.backfill_era`, so leaving it in tests/ would have kept the
    module alive in the import graph — the exact shape this card is about."""
    assert not (ING / "tests" / "test_backfill_era_dsn.py").exists()
    kept = RETIRED / "test_backfill_era_dsn.py.retired"
    assert kept.exists(), "the test was deleted rather than kept"
    assert "V3_BACKLOG_DSN" in kept.read_text()


@pytest.mark.skip(reason="handover gap 2026-11-09: retired/README.md is not in "
                         "the pack — request it from the integrator, then re-enable")
def test_where_the_DSN_RULE_WENT_is_recorded():
    """Retiring a test that pinned a rule without saying where the rule lives is how a
    rule stops being one."""
    readme = (RETIRED / "README.md").read_text()
    assert "estate_dsn" in readme and "C534" in readme
    assert "read-only STANDBY" in readme or "read-only standby" in readme
