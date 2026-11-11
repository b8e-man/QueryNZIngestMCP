"""e-tangata.co.nz — Māori and Pasifika long-form journalism (WordPress); a
coverage blind spot in mainstream news. Clean robots. Generic RSS scraper."""
from __future__ import annotations
from . import genericrss
SOURCE = "e-tangata.co.nz"
discover = genericrss.make_discover("https://e-tangata.co.nz/feed/")
extract = genericrss.extract
