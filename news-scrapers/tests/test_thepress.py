"""thepress.co.nz module contract: extract() parses the story JSON (shape
measured 2026-11-13 from the live /api/v1.0/the-press/story/{id} payload),
the URL id-regex matches real article URLs, and a non-JSON body (SPA shell)
is refused instead of landing garbage."""
import json

from newsscrapers import thepress

_STORY = {
    "id": 361114431,
    "type": "ARTICLE",
    "teaser": {"title": "Teaser title", "intro": "teaser intro"},
    "content": {
        "title": "Scarborough Rd occupants respond to neighbours' complaints",
        "intro": "intro",
        "url": "/nz-news/361114431/scarborough-rd-occupants-respond-neighbours-complaints",
        "contentBody": {"body": "<p>First paragraph.</p><p>Second paragraph.</p>"
                                "<h2>A heading</h2><p>Third paragraph.</p>"},
        "section": "NZ news",
        "topic": [{"name": "Timaru", "url": "/topics/timaru"},
                  {"name": "Housing", "url": "/topics/housing"}],
    },
    "author": [{"id": "x", "name": "Rachael Comer"}],
    "publishedDate": "2026-11-13T15:00:00Z",
}


def test_extract_parses_story_json():
    ex = thepress.extract(json.dumps(_STORY), "https://example.invalid/x")
    assert ex is not None
    assert ex.title == "Scarborough Rd occupants respond to neighbours' complaints"
    assert "First paragraph." in ex.text and "A heading" in ex.text
    assert ex.author == "Rachael Comer"
    assert ex.published_at is not None
    assert ex.published_at.year == 2026 and ex.published_at.month == 11
    assert ex.categories == ["NZ news", "Timaru", "Housing"]


def test_extract_refuses_spa_shell():
    assert thepress.extract("<!doctype html><html><body>app</body></html>", "u") is None
    assert thepress.extract("null", "u") is None


def test_extract_refuses_empty_body():
    story = json.loads(json.dumps(_STORY))
    story["content"]["contentBody"]["body"] = ""
    assert thepress.extract(json.dumps(story), "u") is None


def test_url_id_regex_matches_real_shape():
    u = "https://www.thepress.co.nz/nz-news/361114431/scarborough-rd-occupants-respond-neighbours-complaints"
    m = thepress._ID_RE.search(u)
    assert m and m.group(1) == "361114431"
    assert not thepress._ID_RE.search("https://www.thepress.co.nz/nz-news/archive")
