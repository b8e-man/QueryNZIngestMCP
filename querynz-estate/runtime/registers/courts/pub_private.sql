-- registers/courts: the lane's private views for the links lane (ruling 142, Arthur, 4 November 2026: "match them";
-- "we want everything"). Made in `pub_private` by support.db.private_views before each links build; neither reader
-- login is granted the schema. The contact details and street addresses a court document prints, as the lane keeps
-- them (`courts_private.identifiers`, identifiers.py): the links lane's shared-contact@1 and judgment-address-*@1 read
-- them, and only it.
CREATE OR REPLACE VIEW pub_private.court_identifiers AS
SELECT key, person, document, kind, value, page
  FROM courts_private.identifiers
 WHERE kind IN ('address', 'po_box', 'email', 'phone');
