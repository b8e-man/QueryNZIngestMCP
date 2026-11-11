"""The nzme premium-drop + Arc-id predicate exists on TWO paths — the fresh
sitemap filter (_articles/_ARTICLE) and the archive walker's ARCHIVE["article_re"]
— and they had to be edited together (2026-08-24 card). Folded 2026-08-30: both
build from the single _ARC_TAIL constant; this battery pins their agreement so a
future edit to one path reddens if the other drifts."""
import re

from newsscrapers import nzme


def _fresh_accepts(url: str) -> bool:
    xml = f"<loc>{url}</loc>"
    return nzme._articles(xml) == [url]


def _archive_accepts(url: str) -> bool:
    return re.match(nzme.ARCHIVE["article_re"], url) is not None


def test_both_regexes_build_from_the_one_tail():
    assert nzme._ARTICLE.pattern.endswith(nzme._ARC_TAIL)
    assert nzme.ARCHIVE["article_re"].endswith(nzme._ARC_TAIL)


def test_paths_agree_on_the_battery():
    battery = {
        # premium is paywalled + robots-disallowed: BOTH paths must reject
        "https://www.nzherald.co.nz/premium/business/ABCDEFGHIJKLMNOPQRSTUVWXYZ/": False,
        # a real Arc-id article: BOTH accept
        "https://www.nzherald.co.nz/nz/politics/ABCDEFGHIJKLMNOPQRSTUVWX/": True,
        # no trailing slash: BOTH accept
        "https://www.nzherald.co.nz/nz/ABCDEFGHIJKLMNOPQRSTUVWX": True,
        # id too short: BOTH reject
        "https://www.nzherald.co.nz/nz/SHORTID123/": False,
        # section page (no Arc id): BOTH reject
        "https://www.nzherald.co.nz/nz/politics/": False,
    }
    for url, want in battery.items():
        assert _fresh_accepts(url) is want, f"fresh path wrong on {url}"
        assert _archive_accepts(url) is want, f"archive path wrong on {url}"
