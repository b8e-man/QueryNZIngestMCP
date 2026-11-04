-- registers/courts: the published views, the only thing a later module reads (contract: the lane).
-- A withheld name is NULL in courts.judgment_parties, courts.people and courts.cases already. No view carries an address
-- or any identifying detail a document prints: those are kept privately (identifiers.py, hard limit 15); no suppressed
-- name is published (hard limit 16). One view reads the private table, narrowly, by ruling (court_company_numbers, last).

CREATE OR REPLACE VIEW pub.court_judgments AS
SELECT key, citation, court, court_name, registry, case_numbers, judgment_date, judges, heading, outcome,
       paragraphs, parties, suppression, suppression_kinds, withheld IS NOT NULL AS names_withheld, status, missing,
       case_slug, source, source_url, document, page, place, read_from, reader, profile, profile_version, loaded_at
  FROM courts.judgments;

CREATE OR REPLACE VIEW pub.court_judgment_parties AS
SELECT p.key, p.judgment, p.citation, j.court, j.judgment_date, p.position, p.role,
       CASE WHEN p.withheld THEN NULL ELSE p.name END AS name,
       p.withheld, p.anonymised, p.crown, p.confidence,
       CASE WHEN p.withheld THEN NULL ELSE p.capacity END AS capacity,
       p.document, p.page, p.place, p.read_from, p.reader, p.profile, p.profile_version, p.loaded_at
  FROM courts.judgment_parties p
  JOIN courts.judgments j ON j.key = p.judgment;

-- every person and body a court document names, with the role the text gives it: the rows the links lane reads
-- (name as filed, role, document, place; `dated` is the document's own date; a withheld name is NULL and `suppressed`)
CREATE OR REPLACE VIEW pub.court_people AS
SELECT p.key, CASE WHEN p.withheld THEN NULL ELSE p.name END AS name, p.kind, p.role, p.role_text,
       CASE WHEN p.withheld THEN NULL ELSE p.for_party END AS for_party,
       p.citation, p.case_slug, p.document_kind, p.dated, p.withheld AS suppressed,
       p.document, p.page, p.place, p.read_from, p.reader, p.model, p.profile, p.profile_version, p.loaded_at
  FROM courts.people p;

-- one row per case page: the court, the case name and the dates the records lack
CREATE OR REPLACE VIEW pub.court_cases AS
SELECT key, case_slug, url, CASE WHEN withheld IS NOT NULL THEN NULL ELSE case_name END AS case_name, citation, case_numbers,
       court, summary, result, judges, date_of_judgment, date_of_hearing, suppression, links,
       document, page, place, read_from, reader, profile, profile_version, loaded_at
  FROM courts.cases;

CREATE OR REPLACE VIEW pub.court_case_links AS
SELECT key, "case", position, section, label, href, linked_document, document, page, place
  FROM courts.case_links;

-- one row per record of the corpus: what it is, how it was read, and the text reader's one-line summary
CREATE OR REPLACE VIEW pub.court_documents AS
SELECT key, record, seq, kind, case_slug, url, content_type, fetched_at, document, state, profile, profile_version,
       outcome, pages, read_from, text_chars, citation, case_numbers, dated, summary, model, model_reader, loaded_at
  FROM courts.documents;

-- Arthur, 3 November 2026 (ruling 1): a company's NZBN or company number a court document prints is not personal
-- information, so the links lane may confirm a party to the company it names. Published for the links lane alone and
-- narrow: the document, the kind, the value and the page, those two kinds only, nothing else of the private table.
-- check.py holds this statement to its exact text (check.NUMBERS_VIEW_SQL): a widened view fails the lane's check.
CREATE OR REPLACE VIEW pub.court_company_numbers AS
SELECT document, kind, value, page FROM courts_private.identifiers WHERE kind IN ('nzbn', 'company_number');
