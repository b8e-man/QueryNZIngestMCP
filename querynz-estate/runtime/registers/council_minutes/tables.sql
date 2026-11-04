-- registers/council_minutes: every table this lane owns, in `council_minutes`, in two parts. The capture's record
-- (capture.py makes it; never wiped): no capture table holds a row of the source; every listing page and every
-- minutes document stays in the document store verbatim by sha256. The reading's tables (load.py drops and makes
-- them again at every load) come from the listing pages only: the minutes are held and never read (plan 6.3; ruling
-- 79). The private twin `council_minutes_private` keeps a meeting's venue and every line of a public-excluded part or a
-- public forum item whole (ruling 142, 4 November 2026).

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per ask of an instance's listing (its default page: the year's meetings)
CREATE TABLE IF NOT EXISTS council_minutes.capture_listings (
    listing_id  bigserial PRIMARY KEY,
    host        text NOT NULL,
    url         text NOT NULL,
    asked_at    timestamptz NOT NULL DEFAULT now(),
    status      integer,
    sha256      text,                                -- the page landed; NULL when the read failed
    rows        integer,                             -- the grid's own row count, counted at capture
    why         text                                 -- a failed read's reason
);

-- one row per minutes document the listings name, and what became of it; a document is asked at most once
CREATE TABLE IF NOT EXISTS council_minutes.capture_documents (
    url         text PRIMARY KEY,
    host        text NOT NULL,
    file        text NOT NULL,
    state       text NOT NULL CHECK (state IN ('landed', 'held by the old estate', 'failed', 'set aside')),
    sha256      text,                                -- landed: the bytes' hash; held by the old estate: its listed hash
    listed_in   text,                                -- the listing page's sha256 that named it first
    asked_at    timestamptz,
    why         text
);

-- an instance not asked again until a session reads why: a challenged, blocked or refused read (hard limit 6), or a
-- listing that answered 404 (the instance moved)
CREATE TABLE IF NOT EXISTS council_minutes.capture_held_hosts (
    host   text PRIMARY KEY,
    since  timestamptz NOT NULL DEFAULT now(),
    why    text NOT NULL
);

CREATE TABLE IF NOT EXISTS council_minutes.capture_set_aside (
    item    text NOT NULL,
    stage   text NOT NULL,
    reason  text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- load.py drops these and makes them again at every load, from every listing page held: a row met on several
-- listings is the newest listing's. Each row cites the listing page's sha256, page 1, its row, the reader and the
-- profile.

-- the ledger: one row per listing page read; rows in = meetings out (check.py)
CREATE TABLE IF NOT EXISTS council_minutes.read_listings (
    document    text PRIMARY KEY,
    host        text NOT NULL,
    asked_at    timestamptz,                         -- NULL for a sample listing (no capture record)
    state       text NOT NULL CHECK (state IN ('read', 'set aside')),
    year        integer,
    grid_rows   integer NOT NULL DEFAULT 0,          -- the grid's rows, counted apart from the reader
    meetings    integer NOT NULL DEFAULT 0,
    documents   integer NOT NULL DEFAULT 0
);

-- one row per meeting row of a listing (a supplementary agenda is its own row, as the council lists it)
CREATE TABLE IF NOT EXISTS council_minutes.meetings (
    key              text PRIMARY KEY,                -- <host>/<first document's stem>
    council          text NOT NULL,
    host             text NOT NULL,
    body             text NOT NULL,                   -- the committee, board or council as listed; never the venue
    meeting_date     date NOT NULL,
    meeting_time     text,
    kind             text NOT NULL,                   -- from the listed name: meeting, extraordinary, supplementary, workshop, hearing
    code             text,                            -- the council's own code for the body, from the file name
    documents        integer NOT NULL,
    minutes_file     text,
    minutes_url      text,
    minutes_sha256   text,                            -- the minutes PDF's hash where held (landed, or the old estate's)
    minutes_held     text NOT NULL,                   -- landed | held by the old estate | not yet captured | failed | no minutes listed | html only
    document         text NOT NULL,                   -- the listing page's sha256
    page             integer NOT NULL DEFAULT 1,
    place            text NOT NULL,                   -- 'row n' of the grid
    listing_url      text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- every document a meeting row links (agenda, attachments, minutes; HTML and PDF), listed, not read
CREATE TABLE IF NOT EXISTS council_minutes.documents (
    key              text PRIMARY KEY,                -- <host>/<file>
    meeting_key      text NOT NULL,
    kind             text NOT NULL CHECK (kind IN ('agenda', 'agenda attachments', 'minutes', 'minutes attachments')),
    format           text NOT NULL CHECK (format IN ('pdf', 'html')),
    file             text NOT NULL,
    url              text NOT NULL,
    size_as_printed  text,
    sha256           text,                            -- held: the bytes' hash
    held             text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL DEFAULT 1,
    place            text NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS council_minutes.read_set_aside (
    document  text NOT NULL,
    place     text,
    stage     text NOT NULL,
    reason    text NOT NULL
);

-- ── the minutes' reading (2 November 2026; minutes.py and model_read.py): every landed minutes PDF read under its
-- profile, the standard template deterministically, any other shape by the text reader's stored readings (replayed,
-- never called, here). A public-excluded part and a public forum item are flagged, never cut (ruling 142): their lines are kept whole in
-- council_minutes_private.part_lines, and the standard template reads their resolutions and declarations, `part` beside.

-- the minutes ledger: one row per landed minutes PDF, what became of it; landed minutes = rows here (check.py)
CREATE TABLE IF NOT EXISTS council_minutes.minutes_read (
    document         text PRIMARY KEY,                -- the minutes PDF's sha256
    meeting_key      text,                            -- the meeting whose listing links it
    council          text,
    state            text NOT NULL,                   -- read | waiting: text reader | waiting: page reader | set aside: ... | not minutes ...
    profile          text,
    profile_version  integer,
    read_from        text,                            -- text | mixed | pixels
    pages            integer,
    attendance       integer NOT NULL DEFAULT 0,
    resolutions      integer NOT NULL DEFAULT 0,
    declarations     integer NOT NULL DEFAULT 0,
    excluded_parts   integer NOT NULL DEFAULT 0,      -- public-excluded parts: lines kept in the private twin
    excluded_lines   integer NOT NULL DEFAULT 0,
    forum_items      integer NOT NULL DEFAULT 0,      -- public forum items: lines kept in the private twin
    forum_lines      integer NOT NULL DEFAULT 0,
    unread_pages     text,                            -- pages with no text layer, for the page reader
    model            text
);

-- one row per person the minutes list as present, in attendance, apologising or absent
CREATE TABLE IF NOT EXISTS council_minutes.attendance (
    key              text PRIMARY KEY,                -- <minutes sha256>/a<n>
    meeting_key      text,
    council          text,
    body             text,
    meeting_date     date,
    seq              integer NOT NULL,
    name             text NOT NULL,
    role             text,
    title            text,
    attendance       text NOT NULL CHECK (attendance IN ('present', 'in attendance', 'apology', 'absent')),
    document         text NOT NULL,
    page             integer,
    place            text,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    model            text,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- one row per resolution, motion or recommendation the meeting decided, in the order printed
CREATE TABLE IF NOT EXISTS council_minutes.resolutions (
    key                 text PRIMARY KEY,             -- <minutes sha256>/r<n>
    meeting_key         text,
    council             text,
    body                text,
    meeting_date        date,
    seq                 integer NOT NULL,
    item                text,
    item_title          text,
    number              text,                         -- the council's own resolution number
    mover               text,
    seconder            text,
    text                text NOT NULL,                -- as moved, whole
    outcome             text,
    votes_for           text,
    votes_against       text,
    abstained           text,
    text_names_address  boolean NOT NULL DEFAULT false,   -- ruling 102: the text's shape names a street address
    part                text NOT NULL DEFAULT 'open',    -- open | public excluded | public forum (ruling 142)
    document            text NOT NULL,
    page                integer,
    place               text,
    read_from           text NOT NULL,
    reader              text NOT NULL,
    profile             text NOT NULL,
    profile_version     integer NOT NULL,
    model               text,
    loaded_at           timestamptz NOT NULL DEFAULT now()
);

-- one row per declaration of interest a member made at the meeting
CREATE TABLE IF NOT EXISTS council_minutes.declarations (
    key                 text PRIMARY KEY,             -- <minutes sha256>/d<n>
    meeting_key         text,
    council             text,
    body                text,
    meeting_date        date,
    seq                 integer NOT NULL,
    member              text NOT NULL,
    role                text,
    item                text,
    text                text,
    text_names_address  boolean NOT NULL DEFAULT false,
    part                text NOT NULL DEFAULT 'open',    -- open | public excluded | public forum (ruling 142)
    document            text NOT NULL,
    page                integer,
    place               text,
    read_from           text NOT NULL,
    reader              text NOT NULL,
    profile             text NOT NULL,
    profile_version     integer NOT NULL,
    model               text,
    loaded_at           timestamptz NOT NULL DEFAULT now()
);

-- ── the private twin (ruling 142, 4 November 2026): never granted to the session or product logins

-- a meeting's venue as its listing prints it (the committee cell after its first line break): it can be an address
CREATE TABLE IF NOT EXISTS council_minutes_private.venues (
    meeting_key          text PRIMARY KEY,
    venue                text NOT NULL,
    venue_names_address  boolean NOT NULL,          -- its shape names a street address (minutes.names_address)
    document             text NOT NULL,             -- the listing page's sha256
    place                text NOT NULL
);

-- every line of a public-excluded part or a public forum item, whole, in the order printed (minutes.parts)
CREATE TABLE IF NOT EXISTS council_minutes_private.part_lines (
    document   text NOT NULL,                       -- the minutes PDF's sha256
    seq        integer NOT NULL,                    -- the line's order among the document's lines outside the open meeting
    page       integer NOT NULL,
    part       text NOT NULL,                       -- public excluded | public forum
    part_n     integer NOT NULL,                    -- the part's number in the document
    text       text NOT NULL,
    PRIMARY KEY (document, seq)
);
