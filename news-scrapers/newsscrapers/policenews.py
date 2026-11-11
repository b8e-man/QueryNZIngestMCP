"""NZ Police media releases (police.govt.nz) — clean RSS 2.0 head plus a
?page= Drupal archive to 2002 for cluster-time backfill (recon 2026-07-26).
robots crawl-delay 10 → POLITE_SLEEP 11."""
from . import genericrss, htmlsource

SOURCE = "police.govt.nz"
POLITE_SLEEP = 11.0

discover = genericrss.make_discover("https://www.police.govt.nz/rss/news")
extract = htmlsource.make_extract(category="release",
                                  selector=".field--name-body, article, main")
