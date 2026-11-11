"""Shim — the real dedup.py (ingestion/) was not in the archive. --dry never
calls these; real runs raise until the capture adapter owns dedup."""


def url_ref(url: str) -> str:
    return url


async def seen_refs(*a, **k):
    raise NotImplementedError("dedup is not wired in this checkout")


async def register_content(*a, **k):
    raise NotImplementedError("dedup is not wired in this checkout")
