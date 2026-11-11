"""critic.co.nz — Critic Te Ārohi (OUSA, Otago): student magazine that
regularly breaks real university/Dunedin stories. Custom CMS with /rss;
open robots. Generic RSS handles both feed and page shapes."""
from __future__ import annotations
from . import genericrss
SOURCE = "critic.co.nz"
discover = genericrss.make_discover("https://www.critic.co.nz/rss")
extract = genericrss.extract
