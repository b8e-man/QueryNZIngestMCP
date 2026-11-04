# Courts, on the board

One pane, counts only (never a party's name, never a judgment's text, never a summary):

- **The corpus, accounted for:** `select outcome, count(*) from courts.documents group by 1`: read, waiting: page reader,
  waiting: text reader, set aside, caught. `python -m registers.courts.check` holds it to the pull's arrivals.
- **By profile:** `select profile, count(*) from courts.documents group by 1 order by 2 desc`: judgments by court,
  determinations and tribunal decisions, case pages, media releases, transcripts, submissions, synopses, scanned documents.
- **The reader's pieces (ruling 130):** `select profile, count(*), sum(pieces), count(*) filter (where pieces > 1) from courts.documents
  where outcome in ('read', 'waiting: text reader') group by 1`: documents, the calls the text reader makes, documents over
  the budget; `select count(*) from courts.set_aside where stage = 'read' and reason like 'the text reader cannot%'`: unsplittable.
- **Held and read:** `select status, count(*) from courts.judgments group by 1`: parsed, partial, unparsed; the per-field
  missing counts and the roles the counsel lines name that no party holds, from the check.
- **The text reader's work:** `select count(*), count(*) filter (where withheld), count(distinct document) from courts.people`
  and `select role, count(*) from courts.people group by 1`; `select count(summary) from courts.documents`:
  names read, names withheld, documents read, documents summarised. Above zero waiting: text reader for a week after
  the queue ran is the number that matters.
- **Cases:** `select count(*), count(citation), count(date_of_judgment), count(date_of_hearing) from courts.cases` and
  `select count(*), count(linked_document) from courts.case_links`: case pages, with a citation, dated, links, links to a held file.
- **Suppression:** `select count(*) filter (where suppression), count(*) filter (where withheld is not null) from courts.judgments`,
  `select count(*) from courts.people where withheld`, `select count(*) from courts.cases where suppression`
  and `select count(*) from courts.suppression_orders`: judgments flagged, names withheld (caption and model-read),
  cases withheld, orders in the ledger.
- **Set aside:** `select stage, count(*) from courts.set_aside group by stage`: pull, recognise, read, parse, listing
  (the old estate's judgments the corpus lacks: reported to the provider).

The published views the links lane reads: `pub.court_people` (name as filed, kind, role, role_text, for_party, citation,
case_slug, document_kind, dated, suppressed, document, place), beside `pub.court_judgments`, `pub.court_judgment_parties`,
`pub.court_cases`, `pub.court_case_links` and `pub.court_documents`.
