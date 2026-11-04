# Real Estate Authority decisions, on the board

One pane, counts only (no names, nothing from inside a decision):

- **Held:** `select count(*) filter (where captured_at is not null), count(*) from real_estate_authority.cases`:
  cases held (abstract and every PDF landed), of cases listed; and `select count(*) from real_estate_authority.documents`.
- **Against the source:** `python -m registers.real_estate_authority.check`: years equal, short, withdrawn.
- **Set aside:** `select stage, count(*) from real_estate_authority.set_aside group by stage`.
- **Read:** `select count(*), count(*) filter (where suppressed) from real_estate_authority.decisions` and
  `select role, kind, count(*) from real_estate_authority.parties group by 1, 2`; the reading's set-asides from
  `real_estate_authority.read_set_aside`.
- **Last run:** the newest `qv4-real-estate-authority-capture` run record: requests, landed, why it stopped.
