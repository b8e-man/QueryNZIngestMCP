-- registers/council_minutes: what later modules read (plan 6.3). The meetings of the councils on the InfoCouncil
-- platform, as each council's own listing shows them: the body, the date, the kind, and what the estate holds of the
-- minutes (the PDF's sha256 where held). The minutes are held and never read: this view says a meeting happened and
-- where its minutes are, never who attended or what was resolved. The venue is kept whole in council_minutes_private.venues
-- (ruling 142), never on a view. Position `council-meeting-platform-infocouncil`.
CREATE OR REPLACE VIEW pub.council_meetings AS
SELECT m.key, m.council, m.host, m.body, m.meeting_date, m.meeting_time, m.kind, m.code, m.documents,
       m.minutes_file, m.minutes_url, m.minutes_sha256, m.minutes_held,
       'the council''s own meeting listing on its InfoCouncil site'::text AS source,
       m.document, m.page, m.place, m.listing_url, m.read_from, m.reader, m.profile, m.profile_version, m.loaded_at
FROM council_minutes.meetings m;

-- The minutes' reading (2 November 2026): who attended, what was declared and what was resolved, as each council's own
-- minutes PDF prints it, each row citing the PDF's sha256 and page. A public-excluded part and a public forum item are
-- flagged, never cut (ruling 142): `part` beside each row; their lines are kept whole in the private twin. A resolution's text is whole, with the
-- flag `text_names_address` where its shape names a street address (ruling 102). Never a venue.
CREATE OR REPLACE VIEW pub.council_meeting_attendance AS
SELECT a.key, a.meeting_key, a.council, a.body, a.meeting_date, a.seq, a.name, a.role, a.title, a.attendance,
       'the council''s own minutes of the meeting'::text AS source,
       a.document, a.page, a.place, a.read_from, a.reader, a.profile, a.profile_version, a.model, a.loaded_at
FROM council_minutes.attendance a;

CREATE OR REPLACE VIEW pub.council_resolutions AS
SELECT r.key, r.meeting_key, r.council, r.body, r.meeting_date, r.seq, r.item, r.item_title, r.number, r.mover,
       r.seconder, r.text, r.outcome, r.votes_for, r.votes_against, r.abstained, r.text_names_address, r.part,
       'the council''s own minutes of the meeting'::text AS source,
       r.document, r.page, r.place, r.read_from, r.reader, r.profile, r.profile_version, r.model, r.loaded_at
FROM council_minutes.resolutions r;

CREATE OR REPLACE VIEW pub.council_meeting_declarations AS
SELECT d.key, d.meeting_key, d.council, d.body, d.meeting_date, d.seq, d.member, d.role, d.item, d.text,
       d.text_names_address, d.part, 'the council''s own minutes of the meeting'::text AS source,
       d.document, d.page, d.place, d.read_from, d.reader, d.profile, d.profile_version, d.model, d.loaded_at
FROM council_minutes.declarations d;
