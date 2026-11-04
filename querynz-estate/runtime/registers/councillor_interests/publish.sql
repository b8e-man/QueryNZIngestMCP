-- registers/councillor_interests: what later modules read (plan 6.3). Councillors' registers of pecuniary interests,
-- council by council, as each council publishes its summary (Local Government Act 2002, Part 4 subpart 3). Two views:
-- how each of the 78 councils publishes its register and what the estate holds of it; and each member's categories
-- as published, from a council's structured page (read.py) or its register PDF read by the text reader
-- (model_read.py; ruling 128 lifted ruling 79's hold for node2; Arthur, 2 November 2026). Every category is published
-- with its flags (ruling 142; ruling 143): `real_property`, `of_partner`, and `private_entries`, the count of entries
-- shaped like an address, a road, an email or a phone number, which are held in councillor_interests_private.entries.
-- Position `councillors-registers-of-interests`.
CREATE OR REPLACE VIEW pub.councillor_interest_registers AS
SELECT r.council, r.host, r.form, r.landing_url, r.landing_sha256, r.documents_held, r.members_read, r.why, r.loaded_at
FROM councillor_interests.registers r;

CREATE OR REPLACE VIEW pub.councillor_interests AS
SELECT i.key, i.council, i.member, i.role, i.category, i.entries, i.as_at,
       'the council''s own published summary of its register of members'' pecuniary interests'::text AS source,
       i.document, i.page, i.place, i.url, i.read_from, i.reader, i.profile, i.profile_version, i.loaded_at,
       i.kind, i.model, i.real_property, i.of_partner, i.private_entries
FROM councillor_interests.interests i;
