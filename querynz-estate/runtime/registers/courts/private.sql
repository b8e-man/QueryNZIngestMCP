-- registers/courts: the reading's rows whole, in the private schema (ruling 142, 4 November 2026: every lane keeps
-- everything its source gives; a suppression is a flag beside the row, applied at a product's export). A name a
-- suppression covers sits in courts_private.withheld_names, keyed by its row; these views put it back in its row, with
-- the flag and the source's words, for the links lane. courts_private is never granted to the session or product
-- logins; no pub view reads these. Made by load.publish after publish.sql, at every publish (the tables they read are
-- made again by every load).

CREATE OR REPLACE VIEW courts_private.judgment_parties_whole AS
SELECT p.key, p.judgment, p.citation, p.position, p.block, p.role,
       coalesce(w.name, p.name) AS name, coalesce(w.capacity, p.capacity) AS capacity,
       p.withheld AS suppressed, w.suppression_words, p.anonymised, p.crown, p.confidence,
       p.document, p.page, p.place, p.read_from, p.reader, p.profile, p.profile_version, p.loaded_at
  FROM courts.judgment_parties p
  LEFT JOIN courts_private.withheld_names w ON w.key = p.key AND w.held_in = 'judgment_parties';

CREATE OR REPLACE VIEW courts_private.people_whole AS
SELECT p.key, coalesce(w.name, p.name) AS name, p.kind, p.role, p.role_text, coalesce(p.for_party, w.for_party) AS for_party,
       p.citation, p.case_slug, p.document_kind, p.dated, p.withheld AS suppressed, w.suppression_words,
       p.document, p.page, p.place, p.read_from, p.reader, p.model, p.profile, p.profile_version, p.loaded_at
  FROM courts.people p
  LEFT JOIN courts_private.withheld_names w ON w.key = p.key AND w.held_in = 'people';

CREATE OR REPLACE VIEW courts_private.cases_whole AS
SELECT c.key, c.case_slug, c.url, coalesce(w.name, c.case_name) AS case_name, c.citation, c.case_numbers, c.court,
       c.summary, c.result, c.judges, c.date_of_judgment, c.date_of_hearing, c.suppression AS suppressed,
       w.suppression_words, c.links, c.document, c.page, c.place, c.read_from, c.reader, c.profile, c.profile_version,
       c.loaded_at
  FROM courts.cases c
  LEFT JOIN courts_private.withheld_names w ON w.key = c.key AND w.held_in = 'cases';
