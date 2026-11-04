"""The reading of the watched pages: pure, no network, no model.

No council's tender or award page is read (the position: the councils whose
own sites list awards or tenders bar commercial copying or ask for a
request first; TenderLink and Queenstown Lakes challenge; VendorPanel shows
its tenders to registered suppliers only). This module recognises the four
pages whose words decide that, and says whether each still says them:

  bars      the page is the one watched and still carries the words that bar us
  changed   the page is the one watched and no longer carries them: read the
            position again
"""
import html
import re

PROFILE = "council-procurement-terms-page"
PROFILE_VERSION = 1

#: url → (the page's own title, the words that bar the capture, who it is)
WATCHED = {
    "https://www.cluthadc.govt.nz/terms-and-conditions": (
        "Terms and Conditions - Clutha District Council",
        "The Data may not be distributed or copied for any commercial purpose", "Clutha District Council"),
    "https://www.tauranga.govt.nz/terms-of-use": (
        "Terms of use - Tauranga City Council",
        "for personal, informational and non-commercial purposes only", "Tauranga City Council"),
    "https://www.dunedin.govt.nz/about-this-site": (
        "About this site - Dunedin City Council",
        "Upon request, information available on this website may be used free of charge", "Dunedin City Council"),
    "https://www.vendorpanel.nz/marketplace": (
        "VendorPanel Marketplace",
        "Once registered you'll receive notifications of Public Tenders", "VendorPanel"),
}


class NotTheShape(ValueError):
    """Not the page watched at that address."""


def text(page: str) -> str:
    """The page's visible words on one line: no script or style, entities
    decoded, curly apostrophes made plain."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return " ".join(t.replace("’", "'").replace("​", "").split())


def title(page: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return " ".join(html.unescape(m.group(1)).split()) if m else ""


def recognise(url: str, body: bytes) -> str:
    if url not in WATCHED:
        raise NotTheShape(f"{url} is not a watched page")
    want_title, words, who = WATCHED[url]
    page = (body or b"").decode("utf-8", "replace")
    if title(page) != want_title:
        raise NotTheShape(f"not {who}'s page (its title is not {want_title!r})")
    return "bars" if words in text(page) else "changed"
