-- registers/grants: what later modules read (step 6.3). Every grant the Department's national file of class 4 grants
-- publishes (decisions from 2017 on; the file of 21 October 2026 holds 2021 to 2025) and every grant a Lottery
-- committee's record of grants lists, one row each; one row per grantor and recipient as published; one row per
-- publisher and grantor with its licence and attribution. Each grant carries its citation (the document's sha256,
-- page and place, the reader and the profile) and the licence and attribution of the document it was read from. No
-- address of any kind is on any view: none is printed by these layouts (hard limit 15). A recipient is kept as
-- printed and never looked up. Run by a session only against its scratch schema (`pub.` rewritten).

CREATE OR REPLACE VIEW pub.grant_publishers AS
SELECT p.key, p.name, p.kind, p.website, p.on_departments_list, p.role, p.grants, p.licence, p.attribution, p.loaded_at
FROM grants.publishers p;

CREATE OR REPLACE VIEW pub.grants AS
SELECT g.key, g.publisher_key, g.grantor_key, gp.name AS grantor, g.grantor_as_published, g.committee,
       g.recipient_key, g.recipient_as_published, g.recipient_final_as_published, g.recipient_kind,
       g.nzbn_as_published, g.nzbn, g.charity_number_as_published, g.charity_number, g.status,
       g.amount_requested_as_published, g.amount_granted_as_published, g.amount_nzd, g.multi_year,
       g.purpose_as_published, g.category_1, g.category_2, g.decided_on, g.decided_on_as_published, g.period, g.round,
       g.is_refund, g.refunded_on, g.refunded_on_as_published, g.amount_refunded_as_published, g.benefits,
       g.territorial_authority, g.other_territorial_authority, g.region, g.application_as_published,
       g.reason_as_published, g.interest_as_published,
       p.licence, p.attribution,
       g.document, g.page, g.place, g.read_from, g.reader, g.profile, g.profile_version, g.loaded_at
FROM grants.grants g
JOIN grants.publishers p ON p.key = g.publisher_key
JOIN grants.publishers gp ON gp.key = g.grantor_key;

CREATE OR REPLACE VIEW pub.grant_recipients AS
SELECT r.key, r.grantor_key, gp.name AS grantor, r.name_as_published, r.kind, r.nzbn, r.charity_number, r.grants,
       r.accepted, r.declined, r.amount_nzd, r.first_period, r.last_period,
       p.licence, p.attribution,
       r.document, r.page, r.place, r.read_from, r.reader, r.profile, r.profile_version, r.loaded_at
FROM grants.recipients r
JOIN grants.publishers p ON p.key = r.publisher_key
JOIN grants.publishers gp ON gp.key = r.grantor_key;
