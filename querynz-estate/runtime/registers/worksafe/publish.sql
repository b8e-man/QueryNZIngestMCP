-- registers/worksafe: what later modules read (plan 5.3, use cases 5, 6 and 7). WorkSafe New Zealand's court
-- summaries (one per prosecution decided) and accepted enforceable undertakings, one row per item any finished pass
-- listed (one WorkSafe takes down stays, with `taken_down_on`), with the facts as the page states them: the duty holder,
-- the section charged, the decision and its date, the fine and reparation as stated; nothing inferred. One row per duty
-- holder as WorkSafe names it. A name WorkSafe withholds, publishes as a code ('2019-A'), or a page states is
-- suppressed is flagged here; what the page prints in its place, the heading, the page address and every headed
-- section of the page (the facts in brief, the incident) are kept whole in worksafe_private (ruling 142).
CREATE OR REPLACE VIEW pub.worksafe_actions AS
SELECT a.key, a.kind,
       CASE WHEN a.title_withheld THEN 'name withheld by WorkSafe' ELSE a.title END AS title,
       a.title_withheld, a.industry, a.offence_when, a.offence_on, a.section_charged, a.acts, a.sections,
       a.charged_when, a.charged_on, a.court, a.plea, a.decision, a.decided_on, a.fine_text, a.fine_amount,
       a.reparation_text, a.status, a.published_on, a.accepted_on, a.action_on, a.url, a.taken_down_on,
       a.document, a.page, a.place, a.read_from, a.reader, a.profile, a.profile_version, a.loaded_at
FROM worksafe.actions a;

CREATE OR REPLACE VIEW pub.worksafe_parties AS
SELECT p.key, p.action_key, p.ordinal,
       CASE WHEN p.withheld THEN 'name withheld' ELSE p.name END AS name,
       p.withheld, p.withheld_by, p.organisation, p.company_number, p.named_in, p.split_from,
       p.document, p.page, p.place, p.read_from, p.reader, p.profile, p.profile_version, p.loaded_at,
       (SELECT a.action_on FROM worksafe.actions a WHERE a.key = p.action_key) AS action_on   -- the listing's own date, for a report (1 November 2026)
FROM worksafe.parties p;
