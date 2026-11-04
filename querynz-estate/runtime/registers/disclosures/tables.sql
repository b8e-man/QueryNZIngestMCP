-- registers/disclosures: the tables this lane owns, in `disclosures` and `disclosures_private`.
-- Loaded into a staging or scratch schema by replacing `disclosures.` (and `disclosures_private.`) with that
-- schema's name (load.sql). Every row is read from the Commission's own table of large declarations
-- (listing.py); the scanned declarations are documents cited beside it.

CREATE TABLE IF NOT EXISTS disclosures.declarations (
    key                    text PRIMARY KEY,                    -- ec-listing/<received_on>/<12 hex of regime, party, donor>[/<n>]
    document               text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),  -- the listing page it was read from
    page                   integer NOT NULL DEFAULT 1,
    place                  text NOT NULL,                       -- table <t> row <r>, as the page stood
    regime                 text NOT NULL,                       -- over-20000-from-2023 | over-30000-2011-2022 | over-20000-2008-2010
    threshold              integer NOT NULL,                    -- the regime's floor in dollars
    section                text NOT NULL,                       -- the heading the table sits under, as printed
    party                  text,                                -- the registered party (keys.parties); NULL when unresolved
    party_label            text NOT NULL,                       -- the party as the Commission prints it
    party_basis            text NOT NULL,
    donor_name             text NOT NULL,                       -- the donor as the Commission prints it
    amount                 numeric(14,2) NOT NULL,              -- the declared total, as printed (amended where the Commission says so)
    amount_original        numeric(14,2),                       -- the total before an amendment, where the Commission prints both
    received_on            date NOT NULL,                       -- the day the Commission received the declaration
    given_on               date,                                -- the day the party received the gift (one gift); NULL otherwise
    commission_note        text NOT NULL DEFAULT '',            -- the Commission's bracketed statement, verbatim
    amendment              text NOT NULL CHECK (amendment IN ('none', 'amended', 'amendment withdrawn', 'unread')),
    amended_on             date,
    withdrawn_on           date,
    returned_on            date,                                -- the day the party returned the gift, where stated
    amount_note            text NOT NULL DEFAULT '',            -- what the Commission prints after the amount, verbatim
    items_sum              numeric(14,2),                       -- the first figure of every itemised line, summed
    items_check            text NOT NULL,                       -- equal | reconciled (below $100, ruling 66) | differs | no figures (the lines carry multiples and ranges)
    at_or_under_threshold  boolean NOT NULL,                    -- the Commission's own figure does not exceed the regime's floor
    href                   text,                                -- the Commission's link to the scanned declaration
    declaration_document   text CHECK (declaration_document ~ '^[0-9a-f]{64}$'),  -- the scan, when held
    form_total             numeric(14,2),                       -- the scan's own printed total, from a held page reading (pixels)
    form_check             text NOT NULL,                       -- equal | differs | no total read | no reading held | no scan held
    form_reading           text,                                -- the reading's stamp: <model>/<settings hash> <profile>@<version> page <n>
    read_from              text NOT NULL CHECK (read_from IN ('text', 'pixels')),
    reader                 text NOT NULL,
    profile                text NOT NULL,
    profile_version        integer NOT NULL,
    loaded_at              timestamptz NOT NULL,
    issue                  text                                 -- ruling 66: the itemised gifts' signed difference from the amount, below $100; NULL when equal
);
ALTER TABLE disclosures.declarations ADD COLUMN IF NOT EXISTS issue text;

-- the gifts a declaration itemises, one per printed line, as printed
CREATE TABLE IF NOT EXISTS disclosures.items (
    key              text PRIMARY KEY,                          -- <declaration key>/<ordinal>
    declaration      text NOT NULL,
    ordinal          integer NOT NULL,
    amount           numeric(14,2),                             -- the first figure on the line
    first_date       date,                                      -- the first full date on the line
    contributor      text,                                      -- a name line printed above it (a joint declaration)
    text             text NOT NULL                              -- the line as printed
);

-- every file the lane took from the old folder, and what the Commission's table says of it
CREATE TABLE IF NOT EXISTS disclosures.files (
    document         text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    name             text NOT NULL,                             -- the Commission's own file name
    kind             text NOT NULL,                             -- listing | declaration
    linked_by        text,                                      -- the declaration key whose link names it; NULL when none
    status           text NOT NULL,                             -- read | linked | not linked by the table | collision
    PRIMARY KEY (document, name)
);

-- the catch log: one line for every item the lane could not take to a row
CREATE TABLE IF NOT EXISTS disclosures.set_aside (
    item       text NOT NULL,                                   -- a document hash, a file name or a table place
    stage      text NOT NULL,                                   -- capture | listing | join
    reason     text NOT NULL,
    at         timestamptz NOT NULL DEFAULT now()
);

-- the donor cell's address lines: never published (hard limit 15)
CREATE TABLE IF NOT EXISTS disclosures_private.donor_addresses (
    key        text PRIMARY KEY,                                -- the declaration's key
    address    text NOT NULL
);
