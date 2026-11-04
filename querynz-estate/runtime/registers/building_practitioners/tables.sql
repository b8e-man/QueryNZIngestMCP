-- registers/building_practitioners: every table this lane owns, in `building_practitioners` and its private twin, in
-- two parts. The capture's record (capture.py makes it; never wiped): no capture table holds a row of the source; the
-- list pages stay in the document store verbatim by sha256. The reading's tables (load.py drops and makes them again
-- at every load). No address of any kind is read: the decisions list publishes a region at most (hard limit 15). The
-- register of practitioners is copied on ruling 132: its page's postcode, email and telephones are in the private twin.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per pass over the Board's decisions list: its stated total (the list's own "of N results") and progress
CREATE TABLE IF NOT EXISTS building_practitioners.capture_passes (
    pass_id      bigserial PRIMARY KEY,
    stated       integer,                           -- "Displaying 20 of N results" on the pass's first page
    next_start   integer NOT NULL DEFAULT 0,        -- the next page's `start`; the pass resumes from it
    pages        integer NOT NULL DEFAULT 0,
    items        integer NOT NULL DEFAULT 0,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

-- the listing: one row per list page landed, with its hash
CREATE TABLE IF NOT EXISTS building_practitioners.capture_pages (
    pass_id   bigint NOT NULL REFERENCES building_practitioners.capture_passes (pass_id),
    page_no   integer NOT NULL,
    start     integer NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    items     integer NOT NULL,
    new       boolean NOT NULL,
    PRIMARY KEY (pass_id, page_no)
);

-- the documents about the source (the copyright grant, the privacy statement, the register's statement of s 307)
CREATE TABLE IF NOT EXISTS building_practitioners.capture_docs (
    name      text NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    new       boolean NOT NULL,
    at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS building_practitioners.capture_set_aside (
    pass_id  bigint,
    item     text NOT NULL,
    stage    text NOT NULL,
    reason   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- the register of practitioners (register.py; ruling 132): one row per pass of its 26 searches (the seven licence
-- classes, the nineteen areas of practice), one row per search page landed, and one row per practitioner's page
-- landed (the register's own id, never a name). No row of the source: the pages stay in the document store.
CREATE TABLE IF NOT EXISTS building_practitioners.capture_register_passes (
    pass_id      bigserial PRIMARY KEY,
    next_query   integer NOT NULL DEFAULT 0,
    lists        integer NOT NULL DEFAULT 0,
    rows         integer NOT NULL DEFAULT 0,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE TABLE IF NOT EXISTS building_practitioners.capture_register_lists (
    pass_id   bigint NOT NULL REFERENCES building_practitioners.capture_register_passes (pass_id),
    query_no  integer NOT NULL,
    field     text NOT NULL,                        -- lclass or aop
    value     text NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    rows      integer NOT NULL,
    new       boolean NOT NULL,
    PRIMARY KEY (pass_id, query_no)
);

CREATE TABLE IF NOT EXISTS building_practitioners.capture_register_details (
    guid        text NOT NULL,                      -- the register's own id for the practitioner
    url         text NOT NULL,
    sha256      text NOT NULL,
    new         boolean NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guid, sha256)
);

-- ── the reading
-- load.py drops these and makes them again at every load. Each row cites the page's sha256, page 1, its place
-- (`complaint=CB26816`), the reader and the profile.

-- the ledger: one row per list page read; items in = decisions typed + read again on a later page + set aside
CREATE TABLE IF NOT EXISTS building_practitioners.read_pages (
    document     text PRIMARY KEY,
    pass_id      bigint,
    stated       integer,
    items        integer NOT NULL,
    typed        integer NOT NULL,
    superseded   integer NOT NULL,
    set_aside    integer NOT NULL
);

-- one row per published complaint decision of the Building Practitioners Board
CREATE TABLE IF NOT EXISTS building_practitioners.decisions (
    key               text PRIMARY KEY,             -- building_practitioners/decision/<complaint number>/<kind>
    complaint_number  text NOT NULL,                -- the Board's own (CB26816)
    citation          text,                         -- [2025] BPB 26816
    decision_kind     text NOT NULL,                -- as the title states it: final decision, penalty decision, …
    name              text,                         -- the practitioner as the title publishes it; NULL when suppressed
    lbp_number        text,                         -- NULL when suppressed
    suppressed        boolean NOT NULL,             -- the Board withholds the name, or the item records a suppression
    region            text,                         -- the area the list publishes and nothing finer; NULL when "Omitted"
    licence_classes   text[] NOT NULL,
    decided_on        date,
    penalties         text[] NOT NULL,              -- s 318 orders as listed
    grounds           text[] NOT NULL,              -- s 317 grounds as listed, each with "- not upheld" where so
    upheld            boolean,                      -- any ground upheld; NULL when the list gives no ground
    decision_url      text,                         -- carries the name: withheld on the view when suppressed
    pdf_url           text,
    taken_down_on     date,                         -- the Board's list no longer lists it, by this date; NULL: listed
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL, reader text NOT NULL,
    profile text NOT NULL, profile_version integer NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now()
);

-- the register of licensed building practitioners (ruling 132): one row per practitioner whose page is held, keyed by
-- the practitioner number; classes and areas from the newest pass's searches. The town is kept whole with a flag where
-- its shape names an address (ruling 102); the page's postcode, email and telephones are in the private twin.
CREATE TABLE IF NOT EXISTS building_practitioners.practitioners (
    key                 text PRIMARY KEY,           -- building_practitioners/lbp/<practitioner number>
    licence_number      text NOT NULL,
    name                text,
    first_name          text,
    middle_names        text,
    last_name           text,
    suppressed          boolean NOT NULL,
    licence_classes     jsonb,                      -- [{class, areas}] from the newest pass's searches
    status              text,                       -- licensed (on the newest pass's searches), or not on the current listing
    area                text,                       -- the town the register publishes
    area_names_address  boolean NOT NULL,           -- the town's shape names an address (ruling 102): a product withholds it
    region              text,
    first_granted_on    date,                       -- "Date Licensing Class First Granted", as a New Zealand day
    register_url        text,
    register_id         text NOT NULL,
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL, reader text NOT NULL,
    profile text NOT NULL, profile_version integer NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now()
);

-- the register's ledger: one row per load, the newest pass's practitioners listed against those read
CREATE TABLE IF NOT EXISTS building_practitioners.read_register (
    pass_id        bigint,
    searches       integer NOT NULL,
    listed         integer NOT NULL,                -- distinct practitioners on the pass's searches
    pages          integer NOT NULL,                -- practitioners' pages read (the newest of each)
    typed          integer NOT NULL,
    set_aside      integer NOT NULL,
    awaiting       integer NOT NULL                 -- listed, page not yet fetched
);

CREATE TABLE IF NOT EXISTS building_practitioners.read_set_aside (
    document  text NOT NULL,
    place     text NOT NULL,
    stage     text NOT NULL,
    reason    text NOT NULL
);

-- the private twin (ruling 142, 4 November 2026): what the lane's own tables leave out, kept whole
-- a suppressed decision as the list prints it: the name, LBP number, region and the addresses that carry the name
CREATE TABLE IF NOT EXISTS building_practitioners_private.suppressed (
    key               text PRIMARY KEY,             -- the decision's key
    name              text,
    lbp_number        text,
    region            text,
    decision_url      text,
    pdf_url           text,
    document text NOT NULL, place text NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now()
);

-- each decision's summary as listed (it can name a property or a complainant)
CREATE TABLE IF NOT EXISTS building_practitioners_private.summaries (
    key               text PRIMARY KEY,             -- the decision's key
    summary           text NOT NULL,
    document text NOT NULL, place text NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now()
);

-- a practitioner page's postcode, email, telephones, fax and website, as printed
CREATE TABLE IF NOT EXISTS building_practitioners_private.contacts (
    key               text NOT NULL,                -- the practitioner's key
    field             text NOT NULL,                -- the page's own field name (olp_primaryemailpr, …)
    value             text NOT NULL,
    document text NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key, field)
);
