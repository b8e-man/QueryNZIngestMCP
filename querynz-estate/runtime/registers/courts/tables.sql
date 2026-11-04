-- registers/courts (step 5.4; rulings 126 to 128): the courts' documents from the MCP's courts corpus. Two kinds of table:
--   the reading's (documents, cases, case_links, judgments, judgment_parties, paragraphs, people, set_aside, and
--     courts_private.withheld_names and courts_private.identifiers): rebuilt from the documents at every load, wiped and refilled in one transaction (load.py);
--   the lane's own record, never wiped: suppression_orders (a ledger a person writes through suppress.py; nothing deletes
--     from it and there is no command that lifts an order).
-- Everything a document prints is kept (ruling 142, 4 November 2026). The schema courts is read by the session login, so
-- the identifying details a document prints (addresses, ages, dates of birth, emails, phones) are kept in
-- courts_private.identifiers, and a name a suppression covers is kept in courts_private.withheld_names, whole, keyed by
-- the row it belongs to, flagged suppressed with the source's words; the row in judgment_parties, people or cases carries
-- the role, the place and the flag. courts_private (never granted to the session or product logins) also holds the
-- rows whole with their names in place (private.sql: judgment_parties_whole, people_whole, cases_whole), for the links.

-- one row per record of the corpus (the version the pull saw last): what became of its file
CREATE TABLE IF NOT EXISTS courts.documents (
    key               text PRIMARY KEY,                -- <record id>  (the record's url)
    record            text NOT NULL CHECK (record ~ '^[0-9a-f]{64}$'),   -- the record document the pointer was read from
    seq               bigint,
    kind              text,                            -- the MCP's kind: case_page | judgment_pdf | media_release
    case_slug         text,
    url               text NOT NULL,
    content_type      text,
    fetched_at        timestamptz,                     -- when the provider captured it
    document          text CHECK (document IS NULL OR document ~ '^[0-9a-f]{64}$'),   -- the file, by hash; NULL when not landed
    state             text NOT NULL,                   -- the pull's: landed | held | caught | waiting
    profile           text,                            -- the profile recognised by shape, or NULL
    profile_version   integer,
    outcome           text NOT NULL,                   -- read | waiting: page reader | waiting: text reader | set aside | caught
    pages             integer,
    read_from         text,                            -- text | pixels | mixed
    text_chars        integer,                         -- characters of text read (text layer, or page readings; a case page's text as sent to the model)
    pieces            integer,                         -- pieces the text reader needs by the profile's reading rule (1 = whole; ruling 130); NULL when not read by text
    citation          text,                            -- the neutral citation the document carries, where it carries one
    case_numbers      text[] NOT NULL DEFAULT '{}',
    dated             date,                            -- the date the document prints (judgment, release, hearing)
    summary           text,                            -- the one-line summary the text reader made; NULL until read
    model             text,                            -- the model that made the summary and the people rows
    model_reader      text,                            -- the reader version that asked it
    mcp_citation      text,                            -- the MCP record's own `citation`, as it gives it (the provider's, 3 November 2026)
    mcp_doc_date      date,                            -- the MCP record's `doc_date`, the judgment's own date by the provider (its `date` is the arrival)
    mcp_court         text,                            -- the MCP record's own `court`, as it gives it (the provider re-files records under another court)
    mcp_court_reclassified_at timestamptz,             -- the MCP record's `court_reclassified_at`: when the provider re-filed it (4 November 2026)
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_case_slug ON courts.documents (case_slug);
CREATE INDEX IF NOT EXISTS documents_document ON courts.documents (document);

-- one row per case page read: the court, the case name and the dates the records lack
CREATE TABLE IF NOT EXISTS courts.cases (
    key               text PRIMARY KEY,                -- <document sha256>/case
    case_slug         text NOT NULL,
    url               text NOT NULL,
    case_name         text,                            -- the title before its dash; NULL when withheld
    citation          text,                            -- the citation in the title, where the court printed one
    case_numbers      text[] NOT NULL DEFAULT '{}',
    court             text,                            -- from the breadcrumb: Supreme Court, Court of Appeal, …
    summary           text,                            -- the page's own one-line summary (the court's words)
    result            text,                            -- the page's Result, the court's words
    judges            text,
    date_of_judgment  date,
    date_of_hearing   date,
    suppression       boolean NOT NULL DEFAULT false,
    withheld          text,
    links             integer NOT NULL DEFAULT 0,
    document          text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page              integer NOT NULL,
    place             text NOT NULL,
    read_from         text NOT NULL,
    reader            text NOT NULL,
    profile           text NOT NULL,
    profile_version   integer NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cases_slug ON courts.cases (case_slug);

-- one row per file a case page links: what the court calls it, and the corpus document it is where the corpus holds it
CREATE TABLE IF NOT EXISTS courts.case_links (
    key               text PRIMARY KEY,                -- <case key>/link/<n>
    "case"            text NOT NULL,
    position          integer NOT NULL,
    section           text,                            -- the heading the link sits under: Decision, Media releases, Hearing Transcripts, …
    label             text,
    href              text NOT NULL,                   -- absolute
    linked_document   text,                            -- the corpus file by hash, where a record points at this url
    document          text NOT NULL,
    page              integer NOT NULL,
    place             text NOT NULL
);

-- one row per judgment document read: the caption's facts, never its text
CREATE TABLE IF NOT EXISTS courts.judgments (
    key               text PRIMARY KEY,                -- <document sha256>/judgment
    citation          text,                            -- the neutral citation as printed: [2024] NZSC 161
    court             text,                            -- NZSC | NZCA | NZHC | NZEmpC | …, from the citation
    court_name        text,                            -- as the court line prints it
    registry          text,                            -- the High Court's registry
    case_numbers      text[] NOT NULL DEFAULT '{}',    -- SC 106/2022, CA274/2022, CIV-…, CRI-…: a consolidated appeal has several
    judgment_date     date,
    date_basis        text,                            -- label | running head | delivered | mcp doc_date (the document gave none; the MCP's)
    citation_basis    text,                            -- document | mcp citation (the document gave none; the MCP's)
    hearing           text,                            -- the Hearing: label as printed (dates)
    judges            text,                            -- the Court: label, else the heading's OF …
    heading           text,                            -- JUDGMENT, SENTENCING NOTES, …
    caption_shape     text,                            -- between | criminal | matter | none
    counsel_roles     text[] NOT NULL DEFAULT '{}',    -- the roles the counsel lines are "for", as printed (Appellant): never a name
    outcome           text[] NOT NULL DEFAULT '{}',    -- a closed vocabulary: appeal dismissed, application granted, …
    paragraphs        integer NOT NULL DEFAULT 0,      -- numbered paragraphs found in sequence
    parties           integer NOT NULL DEFAULT 0,
    suppression       boolean NOT NULL,                -- a banner, an order in the text, or an order in the ledger
    suppression_kinds text[] NOT NULL DEFAULT '{}',    -- banner, order in the text, CPA s 203, Family Court Act, until, paragraphs, ledger
    withheld          text,                            -- why its parties' names are withheld; NULL when none is
    status            text NOT NULL,                   -- parsed | partial | unparsed
    missing           text[] NOT NULL DEFAULT '{}',
    unrecognised      integer NOT NULL DEFAULT 0,      -- caption lines no grammar took: a count, never the lines
    notes             text[] NOT NULL DEFAULT '{}',
    case_slug         text,
    source            text NOT NULL,
    source_url        text,
    source_note       text NOT NULL,
    document          text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page              integer NOT NULL,
    place             text NOT NULL,
    read_from         text NOT NULL,
    reader            text NOT NULL,
    profile           text NOT NULL,
    profile_version   integer NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS judgments_citation ON courts.judgments (citation);

-- one row per party and role a caption names: a consolidated appeal gives one row per party
CREATE TABLE IF NOT EXISTS courts.judgment_parties (
    key               text PRIMARY KEY,                -- <document sha256>/party/<position>
    judgment          text NOT NULL,                   -- judgments.key
    citation          text,
    position          integer NOT NULL,
    block             integer NOT NULL,                -- BETWEEN = 1, each AND one more
    role              text NOT NULL,                   -- as printed: Appellant, First Respondents, Defendant, Prosecutor
    name              text,                            -- as printed; under a suppression in courts_private.withheld_names
    withheld          boolean NOT NULL,                -- a suppression covers the name (the flag); the name is kept privately
    anonymised        boolean NOT NULL,                -- the court printed an initial (W, MR N): kept so, never expanded
    crown             boolean NOT NULL,                -- the Crown or a public prosecutor: no suppression covers it
    confidence        text NOT NULL,                   -- high | low (a wrapped list split or rejoined)
    capacity          text,                            -- "as trustees of …", as printed; NULL when withheld
    document          text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page              integer NOT NULL,
    place             text NOT NULL,
    read_from         text NOT NULL,
    reader            text NOT NULL,
    profile           text NOT NULL,
    profile_version   integer NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS judgment_parties_judgment ON courts.judgment_parties (judgment);

-- one row per numbered paragraph, with its page: a citation can say "[2024] NZSC 161 at [45], page 12". No text
CREATE TABLE IF NOT EXISTS courts.paragraphs (
    judgment          text NOT NULL,
    number            integer NOT NULL,
    page              integer NOT NULL,
    document          text NOT NULL,
    PRIMARY KEY (judgment, number)
);

-- one row per person or body the text reader found a document naming, with the role the text gives it (ruling 128):
-- the rows the links lane reads. From a stored model reading only; the load never calls a model
CREATE TABLE IF NOT EXISTS courts.people (
    key               text PRIMARY KEY,                -- <document sha256>/person/<n>
    name              text,                            -- as the document names it; NULL when withheld
    kind              text NOT NULL,                   -- person | body
    role              text NOT NULL,                   -- party | counsel | witness | judge | company | agency | other
    role_text         text,                            -- the role as the text gives it: "counsel for the appellant", "witness for the Crown"
    for_party         text,                            -- counsel: the party acted for, as named in the text
    citation          text,                            -- the document's citation, or its case's
    case_slug         text,
    document_kind     text NOT NULL,                   -- judgment | media release | hearing transcript | counsel submission | case synopsis | case page
    dated             date,                            -- the document's own date
    withheld          boolean NOT NULL DEFAULT false,
    document          text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    page              integer NOT NULL,
    place             text NOT NULL,
    read_from         text NOT NULL,
    reader            text NOT NULL,                   -- the lane's model reader and its version
    model             text NOT NULL,                   -- the served model that read it
    profile           text NOT NULL,
    profile_version   integer NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS people_document ON courts.people (document);
CREATE INDEX IF NOT EXISTS people_citation ON courts.people (citation);

-- the catch log: one line for every item the reading could not take, with the stage and the reason
CREATE TABLE IF NOT EXISTS courts.set_aside (
    item     text NOT NULL,                            -- a record id, or a document's hash
    stage    text NOT NULL,                            -- pull | recognise | read | parse | listing
    reason   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- a name a suppression covers, kept whole with everything printed beside it, keyed by the row it belongs to, flagged
-- suppressed with the source's words (ruling 142: the suppression is a flag beside the row, applied at a product's export)
CREATE TABLE IF NOT EXISTS courts_private.withheld_names (
    key               text PRIMARY KEY,                -- judgment_parties.key, people.key or cases.key
    name              text NOT NULL,
    capacity          text,                            -- a party's capacity as printed
    held_in           text NOT NULL CHECK (held_in IN ('judgment_parties', 'people', 'cases')),
    document          text CHECK (document ~ '^[0-9a-f]{64}$'),
    citation          text,
    for_party         text,                            -- a model-read name's party acted for, as the text gives it
    suppressed        boolean NOT NULL DEFAULT true,
    suppression_words text NOT NULL                    -- the source's words: the kinds found (banner, order in the text, CPA s 203, ...) or the ledger order's reason
);

-- an identifying detail a document prints (Arthur, 3 November 2026: gather any identifying information), once per
-- document, kind and value, at the first page printing it: never published, never exported, never joined by a view.
-- Gathered whether or not the document is under a suppression (the lever withholds names from the published tables; it
-- has nothing to withhold here). `person` is the people row's key where a reader tied the detail to a person, else NULL
CREATE TABLE IF NOT EXISTS courts_private.identifiers (
    key               text PRIMARY KEY,                -- <document sha256>/identifier/<n>
    person            text,                            -- people.key, or NULL (a detail found by its shape)
    document          text NOT NULL CHECK (document ~ '^[0-9a-f]{64}$'),
    kind              text NOT NULL CHECK (kind IN ('address', 'po_box', 'place_of_residence', 'age', 'date_of_birth',
                          'occupation', 'employer', 'law_firm', 'email', 'phone', 'company_number', 'nzbn', 'ird_number',
                          'driver_licence', 'vehicle_registration', 'file_number', 'relationship', 'other')),
    value             text NOT NULL,                   -- as printed
    page              integer NOT NULL,
    place             text NOT NULL,
    read_from         text NOT NULL,
    reader            text NOT NULL,
    model             text,                            -- NULL for a detail found by its shape
    profile           text NOT NULL,
    profile_version   integer NOT NULL,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS courts_identifiers_document ON courts_private.identifiers (document);

-- the ledger of suppression orders the lever records (suppress.py): never wiped, never deleted from
CREATE TABLE IF NOT EXISTS courts.suppression_orders (
    order_id    bigserial PRIMARY KEY,
    citation    text,                                  -- every document of the citation
    document    text CHECK (document IS NULL OR document ~ '^[0-9a-f]{64}$'),
    reason      text NOT NULL,                         -- the order and where it is recorded; never a name
    by_whom     text NOT NULL,
    ordered_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (citation IS NOT NULL OR document IS NOT NULL)
);

-- the estate's own capture (ruling 140): every file the lane fetched itself from a court's own publication, by the address
-- it was asked at; never wiped, never deleted from (a captured document is never deleted). A file the MCP also holds, by
-- hash, is read once, as the MCP's (load.py). No case name is kept here: the document's own caption carries it.
CREATE TABLE IF NOT EXISTS courts.own_files (
    url         text PRIMARY KEY,                      -- the address asked, as the listing gave it, made absolute
    source      text NOT NULL,                         -- courts-jdo (Judicial Decisions Online)
    court       text NOT NULL,                         -- the court as the listing was asked for it
    year        integer,                               -- the listing's judgment-date year
    listing     text CHECK (listing IS NULL OR listing ~ '^[0-9a-f]{64}$'),   -- the listing page that named it, by hash
    sha256      text CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),     -- the file, by hash; NULL when not landed
    bytes       bigint,
    status      text NOT NULL CHECK (status IN ('landed', 'absent')),         -- absent: the host answered 404
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS own_files_sha256 ON courts.own_files (sha256);

-- where the own capture's listing walk is up to: one row per source, court and year
CREATE TABLE IF NOT EXISTS courts.own_cursor (
    source      text NOT NULL,
    court       text NOT NULL,
    year        integer NOT NULL,
    total       integer,                               -- the listing's own count when last asked
    pages_done  integer NOT NULL DEFAULT 0,            -- pages of the listing walked to the end
    done        boolean NOT NULL DEFAULT false,        -- every page walked; a past year is not asked again
    at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, court, year)
);
