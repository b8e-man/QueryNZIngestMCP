# registers.local_elections

Step 6.3: the returns of electoral donations and expenses that candidates for councils, mayoralties, community and
local boards and licensing trusts file after each local election (Local Electoral Act 2001 s 112A), as each
council's electoral officer publishes them (s 112F, seven years), for 2019, 2022 and 2025 and the by-elections
between (ruling 71). No collected source exists for those years (electionz.com's own collection stops at 2013), so
the lane goes council by council: `survey.md` is where each council lists them, `listings.tsv` the pages the
capture asks. The listings are read (`read.py`, structured pages only); the returns are landed by hash and HELD:
their reading waits on node1 (ruling 79). Built by local-elections-1: `survey.py`, `capture.py`, `read.py`,
`load.py`, `publish.sql`, `check.py`, `sample.py`, `sample.list`, `tests/`, `profiles-proposed.jsonl` and the
position page.
