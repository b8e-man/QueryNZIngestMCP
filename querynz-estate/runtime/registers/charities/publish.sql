-- registers/charities: what later modules read (plan 4.1; the Opus build kept). Every charity on the register with
-- its register's own number as the key; its officers with their role, window, status and the register's
-- disqualification status; its annual returns' period, tier, currency, audit opinion and financial fields (ruling of
-- 14 August 2026). Each row carries its citation: the page's sha256, the page and the row's key in it, the reader and
-- the profile. No officer has an address, a birth date, an email or a phone on any view here (hard limit 15). A
-- suppressed name is blanked on every view; the row stays (hard limit 16). Run by a session only against its scratch
-- schema (the tests rewrite `pub.`).
--
-- The address for service: held in charities_private.addresses and shown for every charity (ruling 143, 4 November
-- 2026), with `address_not_body_corporate` true where the charity is not a body corporate (an incorporated society, a
-- company, a trust board incorporated under the Charitable Trusts Act): the flag a product applies hard limit 15 by.
CREATE OR REPLACE VIEW pub.charities AS
SELECT c.key, c.number, c.name, c.other_names, c.status, c.registered_on, c.deregistered_on, c.deregistration_reason,
       c.legal_structure, c.legal_structure_other, c.charitable_purpose, c.main_sector, c.main_activity,
       c.main_beneficiary,
       a.address_for_service,
       a.address_for_service IS NOT NULL AND c.legal_structure IS DISTINCT FROM 'Incorporated Society'
         AND c.legal_structure IS DISTINCT FROM 'Company'
         AND c.legal_structure IS DISTINCT FROM 'Charitable Trusts incorporated under the Charitable Trusts Act'
         AS address_not_body_corporate,
       c.group_key, c.group_number, c.group_name, c.nzbn, c.incorporation_number, c.year_end_month, c.year_end_day,
       c.annual_return_due_on, c.source_modified_at, c.absent_since,
       c.document, c.page, c.place, c.read_from, c.reader, c.profile, c.profile_version, c.loaded_at
FROM charities.charities c
LEFT JOIN charities_private.addresses a ON a.key = c.key;

CREATE OR REPLACE VIEW pub.charity_officers AS
SELECT key, charity_key, kind,
       CASE WHEN suppressed THEN 'name suppressed' ELSE full_name END AS full_name,
       CASE WHEN suppressed THEN NULL ELSE first_name END AS first_name,
       CASE WHEN suppressed THEN NULL ELSE middle_name END AS middle_name,
       CASE WHEN suppressed THEN NULL ELSE last_name END AS last_name,
       name_note, suppressed, role, started_on, ended_on, status, disqualified, source_modified_at, absent_since,
       document, page, place, read_from, reader, profile, profile_version, loaded_at
FROM charities.officers;

CREATE OR REPLACE VIEW pub.charity_returns AS
SELECT key, charity_key, group_key, period_end, months_covered, began_on, tier, currency, audited, modified_opinion,
       opinion, total_gross_income, total_expenditure, net_surplus, total_assets, total_liabilities, total_equity,
       figures, material_expenses, source_modified_at, absent_since,
       document, page, place, read_from, reader, profile, profile_version, loaded_at
FROM charities.returns;
