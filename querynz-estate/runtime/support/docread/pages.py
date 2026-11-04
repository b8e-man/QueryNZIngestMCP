"""Stub of the estate's document reader package (pdftotext wrapper + LLM
page reader) — not part of the capture runtime. Imports resolve; the
capture walks never call these. See support/reader.py for the pattern."""


def __getattr__(name):
    return type(name, (), {"__init__": lambda self, *a, **k: None})
