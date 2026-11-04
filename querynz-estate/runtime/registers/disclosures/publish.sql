-- registers/disclosures: what later modules read. One row per declaration the Commission lists, with its
-- citation, and the gifts it itemises. No address: the donor cell's address lines stay in disclosures_private.
CREATE OR REPLACE VIEW pub.disclosures AS
SELECT key, document, page, place, regime, threshold, section, party, party_label, party_basis, donor_name,
       amount, amount_original, received_on, given_on, commission_note, amendment, amended_on, withdrawn_on,
       returned_on, amount_note, items_sum, items_check, at_or_under_threshold, href, declaration_document,
       form_total, form_check, form_reading,
       read_from, reader, profile, profile_version, loaded_at,
       issue      -- ruling 66: the gifts' signed difference below $100; a view gains columns only at its end
FROM disclosures.declarations;

CREATE OR REPLACE VIEW pub.disclosure_items AS
SELECT key, declaration, ordinal, amount, first_date, contributor, text
FROM disclosures.items;
