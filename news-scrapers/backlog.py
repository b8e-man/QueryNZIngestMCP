"""Shim — the real backlog.py (ingestion/) was not in the archive."""


def scraper_priority(hours: int) -> int:
    raise NotImplementedError("backlog is not wired in this checkout")
