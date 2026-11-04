# registers/commerce_commission — the Commerce Commission's published cases

Step 5.3, the held-and-unread regulator actions (Commerce Commission; use cases 5, 6 and
7). The regulator's own published record of its actions, captured
verbatim by hash through the fetch gate under the four questions, read by
profile into one row per action and one per named party, with the Act and
section the regulator states, the date and the outcome as published.
Nothing is read from the old estate's parsed copy except to compare
counts.

Built by `regulators-1`, with the other two regulator lanes; `spec.md`,
`capture.py`, `read.py`, `load.py`, `publish.sql`, `check.py`,
`sample.list`, `tests/` and the position page are its deliverable.
