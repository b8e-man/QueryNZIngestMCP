-- registers/candidate_returns (plan 4.1): the tables this lane owns, in its own schema.
-- Loaded into a staging or scratch schema by replacing `candidate_returns.` with that schema's name.
-- A donor's street address is never a column here: it lives in candidate_returns_private (private.sql),
-- keyed by the row's key (hard limit 15).

-- every held return: who it belongs to and whether it is current, as the Commission states it (join.py)
CREATE TABLE IF NOT EXISTS candidate_returns.files (
    document      text PRIMARY KEY CHECK (document ~ '^[0-9a-f]{64}$'),
    names         text NOT NULL,                    -- the names the Commission published it under, ' | ' between
    placed_by     text,                             -- listing link | listing name | spreadsheet name | file name; NULL: unplaced
    year          integer,                          -- the election
    surname       text,                             -- as the Commission's listing or spreadsheet prints it
    given_names   text,
    electorate    text,
    party         text,                             -- the party as the Commission lists it ('' for an independent)
    status        text,                             -- current | replaced | replaced, not held | unlisted
    replaced_by   text CHECK (replaced_by ~ '^[0-9a-f]{64}$'),
    stated        text,                             -- the listing's link that replaces it, as the Commission wrote it
    listing       text,                             -- the listing page the candidate's row was read from, by hash
    sheet_key     text                              -- candidate_returns.commission.key of its spreadsheet row
);

-- one row per return read: its declared totals as printed (declaration.py)
CREATE TABLE IF NOT EXISTS candidate_returns.returns (
    key                    text PRIMARY KEY,        -- <document sha256>/declaration
    document               text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page                   integer NOT NULL,
    place                  text NOT NULL DEFAULT 'declaration',
    donations              numeric(14,2),           -- the section's declared figure (Total (A + C + D), or as declaration.py says)
    part_a                 numeric(14,2),
    part_c                 numeric(14,2),
    part_d                 numeric(14,2),
    donations_check        text,                    -- parts-sum | total | parts | step-cell | declared-nil
    expenses               numeric(14,2),           -- Total (F + G)
    part_f                 numeric(14,2),
    part_g                 numeric(14,2),
    expenses_check         text,
    loans                  numeric(14,2),           -- Part H (2023 form); NULL on a form with no loans section
    loans_check            text,
    signed                 text,                    -- the declaration's date as printed
    year_as_printed        integer,                 -- the form's title, where it prints one
    candidate_as_printed   text,
    party_as_printed       text,
    electorate_as_printed  text,
    read_from              text NOT NULL CHECK (read_from IN ('text', 'pixels')),
    reader                 text NOT NULL,
    profile                text NOT NULL,
    profile_version        integer NOT NULL,
    loaded_at              timestamptz NOT NULL,
    donors_check           text,                    -- Part A: parts-sum | declared-nil | NULL: set aside or not read
    issue                  text                     -- ruling 66: a section's parts within $100 of its printed total, not equal
);

-- the Commission's own statements: each spreadsheet row and each listing row, by the file it was read from
CREATE TABLE IF NOT EXISTS candidate_returns.commission (
    key           text PRIMARY KEY,                 -- <file sha256>/<row>: the spreadsheet's line, or the listing row's place on its page
    source        text NOT NULL CHECK (source IN ('spreadsheet', 'listing')),
    file          text NOT NULL CHECK (file ~ '^[0-9a-f]{64}$'),
    file_name     text NOT NULL,
    year          integer NOT NULL,
    surname       text NOT NULL,
    given_names   text,
    electorate    text,
    party         text,
    donations     numeric(14,2),
    expenses      numeric(14,2),
    loans         numeric(14,2),
    received      boolean NOT NULL DEFAULT true,    -- false where the Commission writes "Return not received"
    link          text,                             -- the listing row's link, as written
    problems      text,
    sheet         text                              -- the workbook's tab the spreadsheet row was read from ('' for a csv)
);

-- the catch log: one line for every item the lane could not take to a row, with the stage and the reason
-- (recognise | read | declaration | join for a return; part-a for a published return's Part A, the row standing;
-- commission for a Commission file or row)
CREATE TABLE IF NOT EXISTS candidate_returns.set_aside (
    document   text NOT NULL,
    stage      text NOT NULL,
    reason     text NOT NULL,
    at         timestamptz NOT NULL DEFAULT now()
);

-- Part A: one row per line of the donors' table (the form's example row dropped), from the text layer; published only
-- when the rows add to the page's TOTAL FOR PART A and the declaration's Part A (donors.py)
CREATE TABLE IF NOT EXISTS candidate_returns.donors (
    key              text PRIMARY KEY,               -- <document sha256>/A/<ordinal>
    return_key       text NOT NULL,
    document         text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page             integer NOT NULL,
    place            text NOT NULL,                  -- A/<ordinal>: the row's place in the part, as read
    ordinal          integer NOT NULL,
    donor            text NOT NULL,                  -- the name, cut from the address
    amount           numeric(14,2) NOT NULL,
    dates            text,
    contributions    text,                           -- the Yes/No column as printed
    read_from        text NOT NULL CHECK (read_from IN ('text', 'pixels')),
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL,
    issue            text                            -- ruling 66: the part's rows within $100 of a printed total, not equal
);

-- tranche 3: Part A read; a table made before it gains the columns (rows are named by column)
ALTER TABLE candidate_returns.returns ADD COLUMN IF NOT EXISTS donors_check text;
ALTER TABLE candidate_returns.donors ADD COLUMN IF NOT EXISTS place text;
-- ruling 66: the difference a reconciliation admitted, named on the row
ALTER TABLE candidate_returns.returns ADD COLUMN IF NOT EXISTS issue text;
ALTER TABLE candidate_returns.donors ADD COLUMN IF NOT EXISTS issue text;
-- candidate-returns-3: the spreadsheet row's tab, for the citation of a Commission row published with no return read
ALTER TABLE candidate_returns.commission ADD COLUMN IF NOT EXISTS sheet text;
