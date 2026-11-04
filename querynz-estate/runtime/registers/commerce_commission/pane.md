# Commerce Commission cases, on the board

- **Cases** (`pub.commerce_commission_cases`, kind case, key `key`): title `title` ("name withheld by the
  Commission" where `title_withheld`), `kind` and `sub_category`, `status` and `outcome` as the Commission publishes
  them, `act_section` as stated (and `acts`, `sections` split per Act), `opened_on`, `closed_on`, `case_number` where
  stated; `url` opens the Commission's own entry (empty where a suppressed name would be in it). An open case is an
  investigation or an application, not a finding: the pane says so beside every open case ("The existence of an
  investigation does not mean that there has been a breach of the law", the Commission's own words).
- **Parties** (`pub.commerce_commission_parties`, under their case): `name` as published ("name withheld" where
  `withheld`), `trading_as`, `company_number` where printed. `organisation` false means "not shown to be an
  organisation", never "a person". `split_from` says whether the Commission separated the parties or the field is one
  party as published.
- **Citation** on every row: the entry's sha256 (`document`), `page`, `place`, `reader`, `profile`, `profile_version`.

A case the Commission takes off its register stays, with `taken_down_on` (ruling 142). The register prints no address.
