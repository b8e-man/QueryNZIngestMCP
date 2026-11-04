# Local election candidate returns, on the board

- **Returns** (`pub.local_election_returns`, key `key`): one row per return a council's electoral officer lists on
  the council's site: `council`, `election_year`, `by_election`, `covers` (one candidate, or a combined file for a
  ward, a board or an election), `candidate_as_listed` (the listing's words; never matched to a person here),
  `position` (the seat the listing names; blank where it names none), `return_kind` (as listed), `file_url`,
  `file_document` (the return's sha256 once held) and `file_state`.
- **Coverage** (`pub.local_election_returns_coverage`): returns listed, combined files, files held and failed, by
  council and election.
- **Citation** on every row: the listing page's sha256 (`document`), `place`, `reader`, `profile`,
  `profile_version`.

Say on the pane: "the returns are held, not yet read: no amount and no donor is shown until their reading
(ruling 79)". No address, of a candidate or a donor, is ever shown (hard limit 15). Source: each council's electoral
officer, Local Electoral Act 2001 s 112F.
