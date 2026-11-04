# FMA warnings and enforcement, on the board

- **Actions** (`pub.fma_actions`, kind action, key `key`): `kind` (warning, enforcement case), title `title` ("name
  withheld by the FMA" where `title_withheld`), `action_on` (the date published), the FMA's own `summary`, `acts` and
  `sections` as the page states them, and for a case `outcome` (its latest timeline entry) with `outcome_when` as
  published; `url` opens the FMA's own page (empty where a suppressed name would be in it). A warning is the FMA's
  caution, not a finding against the party: the pane says "FMA warning" and never "fraud". `names_nobody` marks a topic
  alert that names no entity the reading can see.
- **Parties** (`pub.fma_parties`, under their action): `name` as published ("name withheld" where `withheld`),
  `company_number` where printed, `named_in` (a field, the heading, or the heading before its dash). `organisation`
  false means "not shown to be an organisation", never "a person".
- **Citation** on every row: the page's sha256 (`document`), `page`, `place`, `reader`, `profile`, `profile_version`.

An item the FMA takes down stays, with `taken_down_on` (ruling 142). A warning's address and contact fields are in `fma_private`.
