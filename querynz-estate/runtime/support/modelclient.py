"""Stub of the estate's model client (LLM calls) — not part of the capture
runtime. See support/reader.py for the pattern."""


def __getattr__(name):
    return type(name, (), {"__init__": lambda self, *a, **k: None})
