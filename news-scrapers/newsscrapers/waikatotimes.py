"""waikatotimes.co.nz — Waikato Times (Stuff masthead). Added 2026-11-13
under the Stuff-suite ruling; platform facts in stuffmasthead."""
from .stuffmasthead import make

_m = make("waikatotimes.co.nz", "waikato-times")
SOURCE = _m.SOURCE
discover = _m.discover
fetch_all = _m.fetch_all
extract = _m.extract
ARCHIVE = _m.ARCHIVE
POLITE_SLEEP = _m.POLITE_SLEEP
FETCH_CHUNK = _m.FETCH_CHUNK
_ID_RE = _m.ID_RE
