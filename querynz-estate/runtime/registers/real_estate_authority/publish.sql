-- registers/real_estate_authority: what later modules read (step 5.3, use case 12; Arthur, 2 November 2026: "alright
-- do it"). The Real Estate Authority's decisions database, one row per decision its abstract states, and one row per
-- licensee, agency or defendant a decision names. Every decision the database lists and the lane holds is shown,
-- including Complaints Assessment Committee decisions the database has since dropped after its three years.
-- A suppressed decision (a suppression order recorded on the abstract) keeps its row flagged, the names, licence numbers
-- and penalty text kept whole in real_estate_authority_private (ruling 142). A penalty that names a street address
-- carries the flag penalty_names_address beside it, and every product applies hard limit 15 by that flag (ruling 102).
-- The reasoning text and the complainant are in real_estate_authority_private.
CREATE OR REPLACE VIEW pub.rea_decisions AS
SELECT d.key, d.case_id, d.complaint_number, d.listed_body, d.decided_by, d.appeal, d.citation, d.decided_on, d.year,
       d.decision, d.decision_note,
       CASE WHEN d.suppressed THEN NULL ELSE d.penalty END AS penalty,
       d.penalty_kinds, d.penalty_names_address, d.complaint_type, d.transaction_type, d.chairperson, d.charge,
       d.act_sections, d.code_sections, d.history, d.parties_named, d.suppressed, d.abstract_url,
       d.document, d.page, d.place, d.read_from, d.reader, d.profile, d.profile_version, d.loaded_at
FROM real_estate_authority.decisions d;

COMMENT ON VIEW pub.rea_decisions IS
  'One Real Estate Authority decision as its abstract states it: the deciding body, citation, finding, penalty and its kinds, complaint and transaction types, chairperson, sections cited, the dated history with its PDFs. Suppressed: penalty NULL. penalty_names_address flags a street address in the penalty (ruling 102).';

CREATE OR REPLACE VIEW pub.rea_parties AS
SELECT p.key, p.decision_key, p.case_id, p.seq,
       CASE WHEN p.suppressed THEN 'name withheld by the Authority' ELSE p.name END AS name,
       CASE WHEN p.suppressed THEN NULL ELSE p.licence_number END AS licence_number,
       p.kind, p.role, p.suppressed, p.decided_on, p.decision, d.decided_by, d.citation, d.complaint_number,
       p.document, p.page, p.place, p.read_from, p.reader, p.profile, p.profile_version, p.loaded_at
FROM real_estate_authority.parties p
JOIN real_estate_authority.decisions d ON d.key = p.decision_key;

COMMENT ON VIEW pub.rea_parties IS
  'A licensee, agency or defendant a Real Estate Authority decision names, as printed, with the licence number where printed; linked to nobody. Suppressed: name withheld, number NULL, the row kept.';
