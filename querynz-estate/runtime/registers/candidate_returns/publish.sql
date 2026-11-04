-- registers/candidate_returns (plan 4.1): what later modules read. One row per return read: the candidate as the
-- Commission lists them, the election, the declared totals as printed, and the Commission's own figures beside them
-- (the headline rule: its figure, linked to its file, with ours beside it). Nothing here is a person's address.
-- Sum only rows whose status is current or unlisted: a replaced return is kept because a figure that changed between
-- filings is a fact about the filing.
--
-- Then one row per row of the Commission's newest summary spreadsheet that no read return covers (candidate-returns-3):
-- `read_from` is 'commission', the return's own figures (donations … loans, the parts, the checks) are NULL, typed numeric(14,2) as the table is so the union keeps the view's types, because
-- nothing was read, and the Commission's figures stand in commission_donations, commission_expenses and
-- commission_loans, the headline columns. It cites the spreadsheet: `document` is its hash, `place` its tab and row,
-- `sheet` and `sheet_row` the same apart. Its key is the Commission row's own (<spreadsheet sha256>/<row>), never a
-- read return's (<return sha256>/declaration). The replacement rule, here and nowhere else: a spreadsheet row is
-- covered, and its Commission row withdrawn, once a return placed on it (files.sheet_key) whose status is current or
-- unlisted has been read (a row in `returns`). A replaced return read does not cover it: its figures are an earlier
-- filing's. A row the Commission writes "Return not received" is not published (no figure; the catch log names it).
CREATE OR REPLACE VIEW pub.candidate_return_totals AS
SELECT r.key, r.document, r.page, r.place, f.year, f.surname, f.given_names, f.electorate, f.party,
       f.status, f.replaced_by, f.placed_by,
       r.donations, r.part_a, r.part_c, r.part_d, r.donations_check,
       r.expenses, r.part_f, r.part_g, r.expenses_check, r.loans, r.loans_check, r.signed,
       c.donations AS commission_donations, c.expenses AS commission_expenses, c.loans AS commission_loans,
       c.file AS commission_file, c.key AS commission_key,
       r.read_from, r.reader, r.profile, r.profile_version, r.loaded_at, r.donors_check,
       r.issue,                                     -- ruling 66: the parts' difference from the printed total, under $100
       NULL::text AS sheet, NULL::integer AS sheet_row  -- the citation's tab and row, on a Commission row only
FROM candidate_returns.returns r
JOIN candidate_returns.files f ON f.document = r.document
LEFT JOIN candidate_returns.commission c ON c.key = f.sheet_key
UNION ALL
SELECT c.key, c.file, NULL::integer, concat_ws(', ', 'sheet ' || nullif(c.sheet, ''), 'row ' || split_part(c.key, '/', 2)),
       c.year, c.surname, c.given_names, c.electorate, c.party,
       'current', NULL, 'spreadsheet row',
       NULL::numeric(14,2), NULL::numeric(14,2), NULL::numeric(14,2), NULL::numeric(14,2), NULL,
       NULL::numeric(14,2), NULL::numeric(14,2), NULL::numeric(14,2), NULL, NULL::numeric(14,2), NULL, NULL,
       c.donations, c.expenses, c.loans,
       c.file, c.key,
       'commission', 'registers.candidate_returns.commission.spreadsheet_rows', 'ec-candidate-returns-summary',
       NULL::integer, NULL::timestamptz, NULL,
       c.problems,                                  -- a cell the parser could not take as money, named
       nullif(c.sheet, ''), split_part(c.key, '/', 2)::integer
FROM candidate_returns.commission c
WHERE c.source = 'spreadsheet' AND c.received
  AND NOT EXISTS (SELECT 1 FROM candidate_returns.files f JOIN candidate_returns.returns r ON r.document = f.document
                  WHERE f.sheet_key = c.key AND f.status IN ('current', 'unlisted'));

-- Part A's donors: the name and the money, never the address; only parts that reconciled (to the cent, or within
-- ruling 66's $100 with the difference named in `issue`).
CREATE OR REPLACE VIEW pub.candidate_return_donors AS
SELECT d.key, d.return_key, d.document, d.page, d.ordinal, f.year, f.surname, f.given_names, f.electorate, f.party,
       f.status, f.replaced_by, d.donor, d.amount, d.dates, d.contributions, d.read_from, d.reader, d.profile,
       d.profile_version, d.loaded_at, d.place,     -- place and what follows last: a view gains columns only at its end
       d.issue
FROM candidate_returns.donors d JOIN candidate_returns.files f ON f.document = d.document;
