# registers/grants — grants from gaming-machine societies and the Lottery Grants Board

Step 6.3, a source step 6 adds (for use cases 9 and 14). The Department of Internal Affairs publishes every class 4
society's grants, approved and declined, in one national file ("Grants from Gaming Machine Profits", CC BY 4.0), and
the Lottery committees' records of grants as pages on Community Matters. Both are captured verbatim by hash through
the fetch gate under the four questions, read by profile into one row per grant and one per recipient as published,
and checked against the documents' own counts and the Department's own list of societies. A recipient is kept as
printed and never looked up; no address is read.

The societies' own lists (Gambling Act 2003 s 110(4)) are read where they are files (class A of
`cards/the-societies-own-grants-lists-by-class.md`): each society's grants pages walked two links deep, every grants
file landed once, recognised by shape under one profile per layout (`society.py`) and read from the text layer by
word boxes (`pdftable.py`). Eleven layouts from six societies are read (Air Rescue 2017 to 2026, Pelorus, Aotearoa
Gaming Trust, Trust Aoraki 2025, Milestone 2017 to 2020, New Horizon, We Care 2022); the rest are carded by hash in
`unprofiled.list`. They add 2017 to 2020 and, where printed, the purpose. Other grant sources of step 6.3 are
surveyed in `survey.md`.

Built by `grants-1` (the national file, the Lottery record, the lane) and `grants-2` (the societies' files, the
table reader, the regional and tertiary survey).
