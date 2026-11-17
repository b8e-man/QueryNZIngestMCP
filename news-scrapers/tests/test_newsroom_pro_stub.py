"""estate-newsroom-pro-stubs@2026-11-18: the Pro-sales-block thin-row check.

A page whose extracted text carries the Newsroom Pro sales block is a
teaser, not a body — extract() must return None (drops as thin, loud).
A full body without the block extracts normally.
"""
from newsscrapers import newsroom

PAGE = """<html><body>
<h1 class="entry-title entry-title--with-subtitle">Headline</h1>
<span class="author vcard"><a>Reporter</a></span>
<time class="entry-date published" datetime="2026-11-12T06:00:00+13:00">12 Nov</time>
<span class="cat-links">Posted inPolitics</span>
<div class="entry-content">{body}</div>
</body></html>"""

PRO_TEASER = (
    "<p>A few opening paragraphs of the article tease the story ahead and "
    "then stop at the paywall boundary.</p>"
    "<p>Exclusive subscriber-only emails and analysis from our newsroom. "
    "Start 14-day free trial now. Corporate subscriptions also available.</p>"
)

FULL_BODY = (
    "<p>A few opening paragraphs of the article tell the whole story, with "
    "quotes and detail continuing well past any paywall boundary.</p>"
    "<p>And more reporting here.</p>"
)


def test_pro_teaser_drops_as_thin():
    ex = newsroom.extract(PAGE.format(body=PRO_TEASER),
                          "https://newsroom.co.nz/2026/11/12/example/")
    assert ex is None


def test_full_body_extracts():
    ex = newsroom.extract(PAGE.format(body=FULL_BODY),
                          "https://newsroom.co.nz/2026/11/12/example/")
    assert ex is not None
    assert "well past any paywall boundary" in ex.text
    assert ex.title == "Headline"


def test_all_three_markers_recognised():
    for mark in newsroom._PRO_SALES_MARKS:
        ex = newsroom.extract(PAGE.format(body=f"<p>tease</p><p>{mark}</p>"),
                              "https://newsroom.co.nz/2026/11/12/example/")
        assert ex is None, mark
