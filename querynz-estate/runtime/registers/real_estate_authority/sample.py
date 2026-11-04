"""The sample filler (plan 1b.6). The reading (2 November 2026) is proven on
fakes in tests/test_real_estate_authority_read.py, so the sample holds no rows of it. It does not create its tables
in the sample schema either: every module fills one shared scratch schema,
and `set_aside` there is already party_returns' (a different shape). The
tables' shape is proven by the tests instead."""


def fill(conn, schema: str, items: list) -> int:
    return 0
