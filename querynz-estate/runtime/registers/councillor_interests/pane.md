# Councillors' registers of interests, on the board

- **Registers** (`pub.councillor_interest_registers`, key `council`): the 78 councils, each with `form` (html register,
  pdf register, per-member files, linked but not found, not reached, not found), the `landing_url` and its sha256,
  `documents_held` (held, never read) and `members_read`; `why` a council was not reached (a block, held).
- **Interests** (`pub.councillor_interests`, key `key`): from a council that publishes a structured page: `member` and
  `role` as printed, `category` as published, `entries` as printed, `as_at`.
- **Citation** on every interests row: the page's sha256 (`document`), `place` (table and row), `reader`, `profile`.

Say on the pane: "the council's own published summary". Every category, with the flags `real_property`, `of_partner`
and `private_entries` (address-shaped entries, held privately).
