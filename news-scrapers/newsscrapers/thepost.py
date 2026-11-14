"""thepost.co.nz — The Post (Wellington, Stuff masthead; carries the Taranaki
Daily News, Manawatu Standard and Sunday Star-Times sections — their stories
ride this host's sitemaps and keep their source name in categories). Added
2026-11-13 under the Stuff-suite ruling; platform facts in stuffmasthead."""
from .stuffmasthead import make

_m = make("thepost.co.nz", "the-post")
SOURCE = _m.SOURCE
discover = _m.discover
fetch_all = _m.fetch_all
extract = _m.extract
ARCHIVE = _m.ARCHIVE
POLITE_SLEEP = _m.POLITE_SLEEP
FETCH_CHUNK = _m.FETCH_CHUNK
_ID_RE = _m.ID_RE
