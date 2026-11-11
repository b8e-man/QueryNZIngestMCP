"""police.govt.nz — NZ Police media releases: charges, arrests, operations,
district news. Official source, Crown content, open robots (only CMS internals
disallowed). Entity-dense but names accused persons — DISPLAY of person links
rides the existing compliance gates (confidence floor, disclaimer, suppression);
capture+extraction is the same news path as beehive. Drupal RSS."""
from __future__ import annotations
from . import genericrss
SOURCE = "police.govt.nz"
discover = genericrss.make_discover("https://www.police.govt.nz/rss/news")
extract = genericrss.extract
