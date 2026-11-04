-- registers/local_elections: the candidates' returns of electoral donations and expenses at local elections
-- (Local Electoral Act 2001 s 112A; s 112F: published by each council's electoral officer for seven years),
-- 2019, 2022 and 2025 and the by-elections between (ruling 71: 2017 onward). Every table here, and nowhere else.
-- No private twin: no address is read. A return is landed by hash and HELD: its pages are not read (ruling 79).
CREATE SCHEMA IF NOT EXISTS local_elections;

-- ── the capture's record: never wiped
CREATE TABLE IF NOT EXISTS local_elections.capture_passes (
    pass_id     bigserial PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    mode        text NOT NULL,                  -- 'listings' (the pages only) or 'files'
    requests    integer NOT NULL DEFAULT 0,
    landed      integer NOT NULL DEFAULT 0,
    failed      integer NOT NULL DEFAULT 0,
    note        text
);
-- every listing page asked, each pass: the page as it answered
CREATE TABLE IF NOT EXISTS local_elections.capture_pages (
    pass_id     bigint NOT NULL REFERENCES local_elections.capture_passes (pass_id),
    council     text NOT NULL,
    url         text NOT NULL,
    seed_year   integer,
    depth       integer NOT NULL DEFAULT 0,
    status      integer,
    sha256      text,                           -- docs.documents; NULL when nothing landed
    state       text NOT NULL,                  -- 'landed', 'failed', 'blocked', 'refused', 'not found'
    why         text,
    at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pass_id, url)
);
-- every file a listing links that the reading calls a return: asked once, ever, then held by its hash
CREATE TABLE IF NOT EXISTS local_elections.capture_files (
    url         text PRIMARY KEY,
    council     text NOT NULL,
    listing_url text NOT NULL,
    election_year integer,
    pass_id     bigint REFERENCES local_elections.capture_passes (pass_id),
    status      integer,
    sha256      text,
    kind        text,
    size        bigint,
    state       text NOT NULL,                  -- 'wanted', 'landed', 'failed', 'blocked', 'refused', 'not found', 'not linked'
    why         text,
    at          timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- the ledger: one row per listing page read
CREATE TABLE IF NOT EXISTS local_elections.read_pages (
    council     text NOT NULL,
    url         text NOT NULL,
    document    text NOT NULL,
    profile     text NOT NULL,
    state       text NOT NULL,                  -- 'read', 'followed only', 'set aside'
    rows_read   integer NOT NULL,
    not_returns integer NOT NULL,
    out_of_window integer NOT NULL,
    PRIMARY KEY (url, document)
);
-- the register: one row per return a council's listing links
CREATE TABLE IF NOT EXISTS local_elections.returns (
    key                 text PRIMARY KEY,       -- council | file address
    council             text NOT NULL,
    election_year       integer,
    by_election         boolean NOT NULL,
    covers              text NOT NULL,           -- 'one candidate' or 'several candidates' (a combined file)
    candidate_as_listed text NOT NULL,           -- the listing's words, as printed; never matched to a person here
    position            text NOT NULL,           -- the seat the listing names ('' when it names none)
    return_kind         text NOT NULL,           -- 'donations and expenses', 'donations', 'expenses', 'nil'
    link_words          text NOT NULL,
    file_url            text NOT NULL,
    file_document       text,                    -- the return's sha256, once landed; HELD, not read (ruling 79)
    file_state          text NOT NULL,           -- the capture's state for the file
    listing_url         text NOT NULL,
    context             text NOT NULL,
    document            text NOT NULL,           -- the listing page cited: its sha256
    place               text NOT NULL,           -- the listing page's address
    reader              text NOT NULL,
    profile             text NOT NULL,
    profile_version     integer NOT NULL,
    loaded_at           timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS local_elections.read_set_aside (
    document    text,
    place       text NOT NULL,
    stage       text NOT NULL,
    reason      text NOT NULL
);
