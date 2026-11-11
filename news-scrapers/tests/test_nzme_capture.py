"""NZME capture-and-hold (ruling 115): discovery drops paywalled/robots-
disallowed /premium/ URLs and keeps real article URLs; the source is wired
held so nothing it lands can be extracted or embedded."""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ingestion"))
sys.path.insert(0, str(REPO / "ops"))
from newsscrapers import nzme  # noqa: E402
from news import review_sources as rs  # noqa: E402


def test_articles_keep_real_urls_and_drop_premium():
    xml = """
    <urlset>
      <url><loc>https://www.nzherald.co.nz/nz/christchurch/some-story/235E2B7LFFAU3LTE5NIS4YKTOM/</loc></url>
      <url><loc>https://www.nzherald.co.nz/business/paywalled/premium/OCKFHROV55EHPARQ24AIFHU6OE/</loc></url>
      <url><loc>https://www.nzherald.co.nz/nz/spring-weather/T5PNS63WBFHQFGEJ5WUNJD2Y6M/</loc></url>
      <url><loc>https://www.nzherald.co.nz/nz/some-section/</loc></url>
    </urlset>"""
    got = nzme._articles(xml)
    assert "235E2B7LFFAU3LTE5NIS4YKTOM/" in got[0]
    assert len(got) == 2                       # two real articles
    assert not any("/premium/" in u for u in got)  # paywalled dropped
    assert not any(u.endswith("/some-section/") for u in got)  # section index dropped


def test_nzme_source_and_urls_are_held():
    # every nzherald.co.nz URL is held whatever the SOURCE label
    assert rs.held_reason(["nzme"], "https://www.nzherald.co.nz/nz/x/ABCDEFGHIJKLMNOPQRSTUVWXYZ/")
    assert "ruling 115" in rs.held_reason(["nzme"], "https://www.nzherald.co.nz/x/ID26CHARSID26CHARSID26CH/")


def test_registry_wires_nzme_ready_under_ruling_169():
    # ruling 12 (QueryNZV4 plan step 1.5, 2026-10-18: NZME out by name) is
    # WITHDRAWN — ruling 169 (Arthur, 2026-11-11): collect the NZME
    # mastheads from 2026-10-18 (nzherald) / 2026-10-17 (businessdesk), when
    # the old estate's scrapers stopped. Capture-and-hold (ruling 115) stands.
    from newsscrapers import registry
    e = registry.REGISTRY["nzherald.co.nz"]
    assert e.module == "nzme" and e.status == "ready"
    b = registry.REGISTRY["businessdesk.co.nz"]
    # login lane verified working 2026-11-11 (Arc identity flow, Arthur's
    # account): runs when the creds are present; unauthenticated it serves
    # subscriber teasers only (100 thin / 0 landed, measured 2026-11-11).
    assert b.module == "businessdesk" and b.status == "blocked:credentials"
    assert b.creds_env == ("BUSINESSDESK_EMAIL", "BUSINESSDESK_PASSWORD")
