"""ourauckland.aucklandcouncil.govt.nz — OurAuckland (Auckland Council
newsroom): official but names contractors, projects, appointments across the
country's biggest council. Umbraco CMS with an RSS at /rss; robots only blocks
/umbraco/ + /search/."""
from __future__ import annotations
from . import genericrss
SOURCE = "ourauckland.aucklandcouncil.govt.nz"
discover = genericrss.make_discover("https://ourauckland.aucklandcouncil.govt.nz/rss")
extract = genericrss.extract
