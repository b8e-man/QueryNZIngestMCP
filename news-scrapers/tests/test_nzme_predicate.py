"""The nzme premium-drop + Arc-id predicate exists on TWO paths — the fresh
sitemap filter (_articles/_ARTICLE) and the archive walker's ARCHIVE["article_re"]
— and they had to be edited together (2026-08-24 card). Folded 2026-08-30: both
build from the single _ARC_TAIL constant; this battery pins their agreement so a
future edit to one path reddens if the other drifts.

POLICY FLIP 2026-11-13: /premium/ is now ACCEPTED on both paths (measured: 20
of 20 premium URLs served FULL bodies to a plain anonymous fetch; Arthur's word
behind the robots route). The battery below pins the new policy AND the
agreement invariant — the premium column moved, the drift hazard did not."""
import re

from newsscrapers import nzme


def _fresh_accepts(url: str) -> bool:
    xml = f"<loc>{url}</loc>"
    return url in nzme._articles(xml)


def _archive_accepts(url: str) -> bool:
    return re.match(nzme.ARCHIVE["article_re"], url) is not None


def test_both_regexes_build_from_the_one_tail():
    assert nzme._ARTICLE.pattern.endswith(nzme._ARC_TAIL)
    assert nzme.ARCHIVE["article_re"].endswith(nzme._ARC_TAIL)


def test_paths_agree_on_the_battery():
    battery = {
        # premium is collected since 2026-11-13 (measured served in full):
        # BOTH paths accept
        "https://www.nzherald.co.nz/premium/business/ABCDEFGHIJKLMNOPQRSTUVWXYZ/": True,
        # a real Arc-id article: BOTH accept
        "https://www.nzherald.co.nz/nz/politics/ABCDEFGHIJKLMNOPQRSTUVWX/": True,
        # no Arc id: BOTH reject
        "https://www.nzherald.co.nz/nz/": False,
        "https://www.nzherald.co.nz/premium/business/short/": False,
    }
    for url, expected in battery.items():
        assert _fresh_accepts(url) == expected, f"fresh path: {url}"
        assert _archive_accepts(url) == expected, f"archive path: {url}"


def test_arc_tail_is_the_single_source():
    # the exact shape both paths must keep agreeing on
    assert re.search(nzme._ARC_TAIL, "/nz/anything/ABCDEFGHIJKLMNOPQRSTUVWX/")
    assert not re.search(nzme._ARC_TAIL, "/nz/anything/short/")
