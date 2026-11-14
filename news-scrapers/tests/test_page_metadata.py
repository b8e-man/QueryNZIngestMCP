"""page_metadata fallback (estate-improvements practice 4, 2026-11-15):
published_at/author come from the page's own printed metadata — meta tags
(both attribute orders), JSON-LD (object or @graph), <time datetime> — and
never from prose scraping."""
from datetime import datetime

from newsscrapers.base import page_metadata

META_FIRST = (
    '<html><head>'
    '<meta property="article:published_time" content="2026-11-10T09:30:00Z"/>'
    '<meta name="DC.creator" content="Jane Reporter">'
    '</head><body></body></html>'
)

CONTENT_FIRST = (
    '<html><head>'
    '<meta content="2026-10-01T00:00:00+13:00" itemprop="datePublished">'
    '<meta content="Ngā Media Team" name="byl">'
    '</head><body></body></html>'
)

JSONLD = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"http://schema.org","@type":"NewsArticle",'
    '"datePublished":"2026-09-03T07:00:00Z",'
    '"author":[{"name":"R. Writer"},{"name":"S. Sub"}]}'
    "</script></head><body></body></html>"
)

TIME_TAG = (
    "<html><head></head><body>"
    '<span>Published</span><time datetime="2026-08-15T12:00:00+12:00">15 Aug 2026</time>'
    "</body></html>"
)

DATELINE_CSS = (
    "<html><head><style>" + ".css-junk{color:red}" * 200 +
    "</style></head><body><div class='chakra-stack'><p class='css-1'>"
    "Feature: ten ways to tackle climate. 30 October 2026</p>"
    "<p>Body of the story follows here with plenty of words.</p>"
    "</div></body></html>"
)

DATELINE_AMBIGUOUS = (
    "<html><head></head><body><p>Report released 3 November 2026 covers the "
    "period ending 30 June 2026.</p></body></html>"
)

NOTHING = "<html><head><title>No meta</title></head><body><p>Just words.</p></body></html>"


def test_meta_tags_property_first():
    pub, auth = page_metadata(META_FIRST)
    assert pub == datetime.fromisoformat("2026-11-10T09:30:00+00:00")
    assert auth == "Jane Reporter"


def test_meta_tags_content_first():
    pub, auth = page_metadata(CONTENT_FIRST)
    assert pub is not None and pub.year == 2026 and pub.month == 10
    assert auth == "Ngā Media Team"


def test_jsonld_picks_date_and_author_list():
    pub, auth = page_metadata(JSONLD)
    assert pub == datetime.fromisoformat("2026-09-03T07:00:00+00:00")
    assert auth == "R. Writer / S. Sub"


def test_time_datetime_fallback():
    pub, auth = page_metadata(TIME_TAG)
    assert pub is not None and pub.month == 8
    assert auth is None


def test_no_metadata_yields_none():
    pub, auth = page_metadata(NOTHING)
    assert pub is None and auth is None


def test_dateline_past_css_junk():
    pub, auth = page_metadata(DATELINE_CSS)
    assert pub is not None and pub.day == 30 and pub.month == 10


def test_dateline_ambiguous_date_pair_refused():
    pub, auth = page_metadata(DATELINE_AMBIGUOUS)
    assert pub is None
