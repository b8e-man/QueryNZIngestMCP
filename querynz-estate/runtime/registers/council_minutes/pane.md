# Council meetings (InfoCouncil councils), on the board

- **Meetings** (`pub.council_meetings`, key `key`): `council`, `body` as the council lists it (a committee, a
  community board, the council), `meeting_date` and `meeting_time`, `kind` (meeting, extraordinary, supplementary,
  workshop, hearing, briefing: from the listed name), `documents` listed, and the minutes: `minutes_held` (landed,
  held by the old estate, not yet captured, failed, html only, no minutes listed), `minutes_sha256` where held,
  `minutes_url`.
- **Citation** on every row: the listing page's sha256 (`document`), `place` (its row), `reader`, `profile`,
  `profile_version`, `listing_url`.

Say on the pane: "the council's own listing; the minutes are held, not read". No venue, no attendee, no resolution.
The minutes PDF opens from the document store by its hash.
