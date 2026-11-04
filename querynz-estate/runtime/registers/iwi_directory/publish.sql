-- registers/iwi_directory: what later modules read (plan 6.2, template 3, use case 14: the post-settlement governance
-- map). Te Kāhui Māngai as it lists them today: iwi, hapū, marae, organisations and post-settlement governance
-- entities, how they relate, and the settlement a governance entity's entry names. Details are supplied to Te Puni
-- Kōkiri by the organisations themselves; the site is not advice on whom to consult and not a record of historical
-- hapū and marae. No person's name, phone, email or address is read or shown (hard limit 15); a marae's location is
-- the marae's own. Attribution on every row (CC BY 3.0 NZ, as catalogued; position `iwi-and-hapu-directory`).
CREATE OR REPLACE VIEW pub.iwi_directory_entities AS
SELECT e.key, e.kind, e.name, e.iwi_key, e.listed_as, e.region, e.legal_entity, e.governance_structure,
       e.hapu_represented, e.area_of_interest, e.local_authorities, e.primary_purpose, e.website, e.wharenui,
       e.location, e.flags, e.charity_number, e.nzbn, e.last_updated, e.pages, e.url,
       'Te Kāhui Māngai, Te Puni Kōkiri (www.tkm.govt.nz), CC BY 3.0 NZ as catalogued on data.govt.nz'::text AS source,
       e.document, e.page, e.place, e.read_from, e.reader, e.profile, e.profile_version, e.loaded_at
FROM iwi_directory.entities e;

CREATE OR REPLACE VIEW pub.iwi_directory_relations AS
SELECT r.key, r.from_key, r.relation, r.to_key, r.to_name, r.section, r.url,
       r.document, r.page, r.place, r.read_from, r.reader, r.profile, r.profile_version, r.loaded_at
FROM iwi_directory.relations r;

CREATE OR REPLACE VIEW pub.iwi_directory_settlements AS
SELECT s.key, s.settlement_key, s.entity_key, s.iwi_key, s.name, s.act, s.act_year, s.stage, s.signed_on, s.as_printed, s.url,
       s.document, s.page, s.place, s.read_from, s.reader, s.profile, s.profile_version, s.loaded_at
FROM iwi_directory.settlements s;
