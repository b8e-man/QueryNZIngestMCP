# Charities, on the board

One pane per charity (`pub.charities`), its officers and its returns beneath it. The board views the integrator adds
to the catalogue (products/board), each field as the view names it:

- **Charities** (`pub.charities`, kind organisation, key `key`): title `name`, `number` (`CC12345`, a `-1` suffix kept)
  and `status`; fields `other_names`, `registered_on`, `deregistered_on`, `deregistration_reason`, `legal_structure`,
  `legal_structure_other`, `main_sector`, `main_activity`, `main_beneficiary`, `charitable_purpose`, `group_name`
  (`group_number`, `group_key`), `nzbn`, `incorporation_number`, `year_end_month`/`year_end_day`,
  `annual_return_due_on`, `address_for_service`. An NZBN or incorporation number opens the company or society.
- **Charity officers** (`pub.charity_officers`, kind person or body corporate by `kind`, joined on `charity_key`,
  names in `full_name`, `first_name`, `middle_name`, `last_name`, suppressed by `suppressed`): `role`, `started_on`,
  `ended_on`, `status`, `disqualified` (only the register's own status says so), `name_note` (a name field held privately:
  a date or an address typed into it). Past officers after current ones. No address of any kind, no birth date, no
  email or phone: the view has no such column. An officer opens the person's group.
- **Charity returns** (`pub.charity_returns`, joined on `charity_key`, or `group_key` for a group's return): one line
  per return, newest `period_end` first: `months_covered`, `tier`, `currency`, `total_gross_income`,
  `total_expenditure`, `net_surplus`, `total_assets`, `total_liabilities`, `total_equity`, `audited`,
  `modified_opinion` and `opinion`; `figures` and `material_expenses` behind "every figure".
- **Citation** on every row: the feed page's sha256 (`document`), `page`, `place` (`OrganisationId=…`, `OfficerId=…`,
  `AnnualReturnId=…`), `reader`, `profile` and `profile_version`.

The address for service is on every charity's row, with `address_not_body_corporate` true where the charity is not an
incorporated society, a company or a trust board incorporated under the Charitable Trusts Act (ruling 143). A row the
register's newest full copy no longer holds carries `absent_since`.
