"""thepress.co.nz — The Press (Christchurch, Stuff masthead). Added by
Arthur's word, 2026-11-13 ("Do it"): not on the estate's 87-source list; it
joins estate-news like every outlet. Platform facts live in stuffmasthead
(the shared Stuff-masthead core) — this module is the thin per-site binding.
On-site archive runs back to 2023-12-13 (measured 2026-11-13)."""
from .stuffmasthead import make

_m = make("thepress.co.nz", "the-press")
SOURCE = _m.SOURCE
discover = _m.discover
fetch_all = _m.fetch_all
extract = _m.extract
ARCHIVE = _m.ARCHIVE
POLITE_SLEEP = _m.POLITE_SLEEP
FETCH_CHUNK = _m.FETCH_CHUNK
_ID_RE = _m.ID_RE
