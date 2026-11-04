# The iwi and hapū directory (Te Kāhui Māngai), on the board

- **Entities** (`pub.iwi_directory_entities`, key `key`): `kind` (iwi, hapū, marae, organisation, governance entity),
  `name` as the site prints it, `listed_as` (the rohe section, the kind of organisation, tribal or non-tribal marae),
  an iwi's `region`, an organisation's `legal_entity`, `governance_structure`, `hapu_represented`, `website` and its
  role `flags` as printed (post-settlement governance entity with its Act, mandated iwi organisation, iwi aquaculture
  organisation, RMA iwi authority, RMA group representing hapū, Tūhono, member of Ngā Iwi o Taranaki for the
  Taranaki Maunga collective redress), a marae's `wharenui` and `location` (blank where the page has no column). `charity_number` and `nzbn` only
  where the page prints them.
- **Relations** (`pub.iwi_directory_relations`): hapū of iwi, marae of hapū, marae of iwi, organisation of iwi, iwi
  in region, rohe in local authority.
- **Settlements** (`pub.iwi_directory_settlements`): the Act (and year) or deed a governance entity's entry names;
  a mandate is shown as a stage, never as a settlement. `key` is the row's own (the entity's with the settlement's);
  `settlement_key` is the settlement's, shared by every body whose entry names it (blank where the entry names none:
  stage `settled: none named`).
- **Citation** on every row: the page's sha256 (`document`), `place`, `reader`, `profile`, `profile_version`, `url`.

Say on the pane: "as supplied to Te Puni Kōkiri by the organisations; not advice on whom to consult". No person, no
phone, no email, no postal or physical address of an organisation. Source: Te Kāhui Māngai, Te Puni Kōkiri, CC BY
3.0 NZ as catalogued.
