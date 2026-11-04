# Building practitioners, on the board

- **Board decisions** (`pub.building_practitioner_decisions`, kind decision, key `key`): title `citation` and
  `decision_kind`; `name` and `lbp_number` ("name withheld by the Board" where `suppressed`), `decided_on`, `region`
  (the area the list publishes, often none), `licence_classes`, `penalties`, `grounds`, `upheld`; `decision_url` and
  `pdf_url` open the Board's own page and decision (empty where suppressed: both carry the name). A decision older than
  three years is not on the view (the register's own window, the queue's default). The pane never says a practitioner
  "has no decisions": the list is the Board's published decisions, and a missing one is "none found".
- **Licensed building practitioners** (`pub.building_practitioners`, kind person, key `key`; ruling 132): title `name`
  and `licence_number`; `licence_classes` (each class with its areas of practice, from the register's searches),
  `status`, `area` (the town the register publishes, flagged by `area_names_address` where its shape names an
  address, ruling 102), `region`, `first_granted_on`; `register_url` opens the practitioner's page on the register.
  The pane never says a person "is not licensed": a practitioner not found is "not found on the current register".
- **Citation** on every row: the page's sha256 (`document`), `page`, `place` (`complaint=CB26816`,
  `practitioner=BP123456`), `reader`, `profile` and `profile_version`.

No postcode, email or telephone; a decision's summary is not shown (it can name a property or a complainant).
