-- registers/councillor_interests: every table this lane owns, in `councillor_interests`, in two parts. The capture's
-- record (capture.py makes it; never wiped): no capture table holds a row of the source; every page and document stays
-- in the document store verbatim by sha256. The reading's tables (load.py drops and makes them again at every load)
-- come from structured HTML registers (read.py) and, from 2 November 2026, register PDFs and pages read by the text
-- reader (model_read.py; ruling 128 lifted ruling 79 for node2). Every category is kept (ruling 142; ruling 143:
-- real-property declarations whole, a spouse's or partner's interests read), flagged; an entry shaped like a street
-- address, a road, an email or a phone number is kept in the private twin `councillor_interests_private.entries`,
-- which the session and product logins are never granted.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per ask: a council's landing page, a register page, a register document
CREATE TABLE IF NOT EXISTS councillor_interests.capture_items (
    item_id   bigserial PRIMARY KEY,
    council   text NOT NULL,
    url       text NOT NULL,
    kind      text NOT NULL CHECK (kind IN ('page', 'document')),
    found_on  text,                                  -- the page that linked it; NULL for the survey's own address
    asked_at  timestamptz NOT NULL DEFAULT now(),
    status    integer,
    sha256    text,                                  -- NULL when the read failed
    why       text
);

-- a host not asked again until a session reads why (hard limit 6)
CREATE TABLE IF NOT EXISTS councillor_interests.capture_held_hosts (
    host   text PRIMARY KEY,
    since  timestamptz NOT NULL DEFAULT now(),
    why    text NOT NULL
);

CREATE TABLE IF NOT EXISTS councillor_interests.capture_set_aside (
    item    text NOT NULL,
    stage   text NOT NULL,
    reason  text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- load.py drops these and makes them again at every load, from the newest capture of each page.

-- one row per council: how it publishes its register, and what the estate holds of it
CREATE TABLE IF NOT EXISTS councillor_interests.registers (
    council          text PRIMARY KEY,
    host             text NOT NULL,
    form             text NOT NULL,                  -- html register | pdf register | per-member files | linked, not found | not yet captured | address failed | not found | not reached | held: its terms bar automated access
    landing_url      text,
    landing_sha256   text,
    documents_held   integer NOT NULL DEFAULT 0,     -- register documents landed (read by the text reader where they carry text)
    members_read     integer NOT NULL DEFAULT 0,     -- members read from a structured page
    why              text,                           -- not reached: the held host's reason
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- every register document held: the council, its address, its hash (held, never read)
CREATE TABLE IF NOT EXISTS councillor_interests.documents (
    sha256      text PRIMARY KEY,
    council     text NOT NULL,
    url         text NOT NULL,
    found_on    text,
    asked_at    timestamptz NOT NULL,
    reading     text,                                -- read | waiting: text reader | waiting: page reader | not a register: … | set aside: … (model_read)
    members     integer NOT NULL DEFAULT 0,          -- members read from it
    unread_pages integer[] NOT NULL DEFAULT '{}',    -- pages with no text layer, or over the reading budget
    loaded_at   timestamptz NOT NULL DEFAULT now()
);

-- one row per member and published category, from a structured page (read.py) or a register PDF read by the text
-- reader (model_read.py, 2 November 2026): the category as published and every entry as printed, an address-shaped
-- entry in the private twin by this row's key and its ordinal
CREATE TABLE IF NOT EXISTS councillor_interests.interests (
    key              text PRIMARY KEY,               -- <council>/<member>/<category ordinal>
    council          text NOT NULL,
    member           text NOT NULL,                  -- as the page prints the member's name
    role             text,                           -- Mayor, Councillor, …, as printed
    category         text NOT NULL,                  -- the heading as published
    entries          text[] NOT NULL DEFAULT '{}',   -- the entries as printed, the address-shaped ones apart; empty for nil
    real_property    boolean NOT NULL DEFAULT false, -- typed real property, or the heading names land, a home, an address or a contact
    of_partner       boolean NOT NULL DEFAULT false, -- the heading or an entry names a spouse, partner or family member
    private_entries  integer NOT NULL DEFAULT 0,     -- entries shaped like an address, a road, an email or a phone: in the private twin
    kind             text,                           -- the s 54E kind the text reader typed the category by (a PDF's); NULL from a page
    as_at            text,                           -- the register's date as printed
    document         text NOT NULL,
    page             integer NOT NULL DEFAULT 1,
    place            text NOT NULL,
    url              text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    model            text,                           -- the served model that read a PDF; NULL for the page grammar
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- the flagged categories, by heading, flag and count (never a value)
CREATE TABLE IF NOT EXISTS councillor_interests.read_flagged (
    council   text NOT NULL,
    category  text NOT NULL,
    why       text NOT NULL,
    members   integer NOT NULL
);

CREATE TABLE IF NOT EXISTS councillor_interests.read_set_aside (
    document  text NOT NULL,
    place     text,
    stage     text NOT NULL,
    reason    text NOT NULL
);

-- the private twin: an entry shaped like a street address, a road, a rural delivery, a title, an email or a phone
-- number, by the interests row's key and the entry's ordinal as printed (ruling 142; never granted to a reader)
CREATE TABLE IF NOT EXISTS councillor_interests_private.entries (
    key       text NOT NULL,
    ordinal   integer NOT NULL,
    entry     text NOT NULL,
    PRIMARY KEY (key, ordinal)
);
