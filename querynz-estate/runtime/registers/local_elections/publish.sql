-- registers/local_elections: what later modules read (plan 6.3). The returns of electoral donations and expenses
-- that local election candidates filed (Local Electoral Act 2001 s 112A), as each council's electoral officer lists
-- them on the council's site (s 112F), 2017 onward (ruling 71). One row per return a listing links: the council,
-- the election year, the candidate AS LISTED (never matched to a person here), the seat the listing names, the
-- return's kind as listed, the return's own hash once held, and the listing page cited by its hash. The returns are
-- held and NOT read (ruling 79): no amount and no donor is on any view. No address is read or shown (hard limit 15).
CREATE OR REPLACE VIEW pub.local_election_returns AS
SELECT r.key, r.council, r.election_year, r.by_election, r.covers, r.candidate_as_listed, r.position,
       r.return_kind, r.file_url, r.file_document, r.file_state, r.listing_url,
       'the electoral officer of ' || r.council || ', under the Local Electoral Act 2001 s 112F'::text AS source,
       r.document, r.place, r.reader, r.profile, r.profile_version, r.loaded_at
FROM local_elections.returns r;

-- how many returns each council lists, by election: the coverage the board shows
CREATE OR REPLACE VIEW pub.local_election_returns_coverage AS
SELECT r.council, r.election_year, r.by_election,
       count(*) AS returns_listed,
       count(*) FILTER (WHERE r.covers = 'several candidates') AS combined_files,
       count(*) FILTER (WHERE r.file_state = 'landed') AS files_held,
       count(*) FILTER (WHERE r.file_state NOT IN ('landed', 'wanted', 'not asked')) AS files_failed
FROM local_elections.returns r
GROUP BY r.council, r.election_year, r.by_election;
