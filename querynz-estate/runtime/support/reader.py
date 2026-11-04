"""Stub of the estate's page reader (LLM text extraction) — not part of the
capture runtime. Attribute accesses resolve to placeholder classes so the
lanes' read modules import; the capture walks never call them. The estate's
readers use its own reader against its own store."""


def __getattr__(name):
    return type(name, (), {"__init__": lambda self, *a, **k: None})
