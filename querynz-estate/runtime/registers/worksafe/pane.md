# WorkSafe prosecutions and undertakings, on the board

- **Actions** (`pub.worksafe_actions`, kind action, key `key`): `kind` (prosecution, enforceable undertaking), title
  `title` ("name withheld by WorkSafe" where `title_withheld`). A prosecution shows `section_charged` as stated (and
  `acts`), `court`, `plea`, `decision`, `decided_on`, `fine_text` and `reparation_text` as stated, `fine_amount` only
  where the field states one figure, `offence_when` and `charged_when` as stated. An undertaking shows `status`,
  `accepted_on`, `published_on` and the `sections` its alleged contravention states; an undertaking is accepted in
  place of a prosecution and is not a conviction, and the pane says so. `url` opens WorkSafe's own page (empty where a
  withheld name would be in it).
- **Parties** (`pub.worksafe_parties`, under their action): the duty holder as WorkSafe names it ("name withheld"
  where `withheld`); `named_in` (the Defendant name field or the heading); `organisation` false means "not shown to be
  an organisation", never "a person".
- **Citation** on every row: the page's sha256 (`document`), `page`, `place`, `reader`, `profile`, `profile_version`.

An item WorkSafe takes down stays, with `taken_down_on` (ruling 142). The facts in brief are in `worksafe_private`.
