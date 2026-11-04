-- registers/fma: every table this lane owns, in `fma` and its private twin, in two parts. The capture's record
-- (capture.py makes it; never wiped): no capture table holds a row of the source; the listing pages and the warning
-- and case pages stay in the document store verbatim by sha256. The reading's tables (load.py drops and makes them
-- again at every load). `fma_private` holds what the lane's own tables leave out, kept whole (ruling 142, 4 November
-- 2026): every labelled field a warning prints besides its party (address, website, email, telephone, bank), and what
-- a suppression the page states covers (the name; the heading, summary, outcome, slug and address). An item the FMA
-- takes down stays, flagged with the date of the first finished pass that no longer listed it.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per pass over a listing: its stated total (the listing's own :total) and how far it has got
CREATE TABLE IF NOT EXISTS fma.capture_passes (
    pass_id      bigserial PRIMARY KEY,
    list         text NOT NULL,
    stated       integer,                           -- the listing's own count, read from the pass's first page
    next_page    integer NOT NULL DEFAULT 1,        -- the pass resumes from this page
    pages        integer NOT NULL DEFAULT 0,
    items        integer NOT NULL DEFAULT 0,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

-- the listing pages landed, with their hashes
CREATE TABLE IF NOT EXISTS fma.capture_pages (
    pass_id   bigint NOT NULL REFERENCES fma.capture_passes (pass_id),
    page_no   integer NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    items     integer NOT NULL,
    PRIMARY KEY (pass_id, page_no)
);

-- what each pass listed: the item's slug, address and fingerprint (its date and title as listed)
CREATE TABLE IF NOT EXISTS fma.capture_listed (
    pass_id   bigint NOT NULL REFERENCES fma.capture_passes (pass_id),
    list      text NOT NULL,
    slug      text NOT NULL,
    url       text NOT NULL,
    card      text NOT NULL,
    ordinal   integer NOT NULL,
    PRIMARY KEY (pass_id, slug)
);

-- the items landed: one row per fetch, so an item fetched again (its card changed) keeps its older hash too
CREATE TABLE IF NOT EXISTS fma.capture_items (
    list      text NOT NULL,
    slug      text NOT NULL,
    url       text NOT NULL,
    card      text NOT NULL,
    sha256    text NOT NULL,
    at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (list, slug, sha256)
);

-- the documents about the source (the copyright licence, the privacy statement)
CREATE TABLE IF NOT EXISTS fma.capture_docs (
    name      text NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    new       boolean NOT NULL,
    at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fma.capture_set_aside (
    pass_id  bigint,
    item     text NOT NULL,
    stage    text NOT NULL,
    reason   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- load.py drops these and makes them again at every load. Each row cites the page's sha256, page 1, its place, the
-- reader and the profile.

-- the ledger: one row per item the newest finished pass of each list listed; items in = read + set aside + not captured
CREATE TABLE IF NOT EXISTS fma.read_items (
    list       text NOT NULL,
    slug       text NOT NULL,
    pass_id    bigint,
    document   text,                                -- NULL: listed and not yet captured
    state      text NOT NULL CHECK (state IN ('read', 'set aside', 'not captured')),
    parties    integer NOT NULL DEFAULT 0,
    taken_down_on date,                             -- the first finished pass that no longer listed it; NULL: listed now
    PRIMARY KEY (list, slug)
);

CREATE TABLE IF NOT EXISTS fma.actions (
    key              text PRIMARY KEY,              -- fma/warning/<slug> or fma/enforcement/<slug>
    kind             text NOT NULL,                 -- 'warning' or 'enforcement case'
    slug             text,                          -- NULL where a suppression withholds a name (the slug carries it)
    title            text,                          -- the heading as published; NULL where withheld
    title_withheld   boolean NOT NULL,
    summary          text,                          -- the FMA's own one-line description of the page
    published_on     date,
    acts             text[] NOT NULL,               -- each Act the body names by title
    sections         text[] NOT NULL,               -- each 'section N of the <Act>' the body states, verbatim
    outcome          text,                          -- a case's latest dated timeline entry, as published
    outcome_when     text,                          -- the entry's date as published: '17 June 2026' or 'March 2026'
    outcome_on       date,                          -- the day, only where the entry gives one
    names_nobody     boolean NOT NULL,              -- a topic alert: no entity named in a field or the heading
    url              text,                          -- NULL where a suppression withholds a name (the address carries it)
    taken_down_on    date,                          -- the FMA took the item down by this date
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fma.parties (
    key              text PRIMARY KEY,              -- <action key>/party/<n>
    action_key       text NOT NULL,
    ordinal          integer NOT NULL,
    name             text,                          -- as published; NULL where withheld (hard limit 16)
    withheld         boolean NOT NULL,
    withheld_by      text,
    organisation     boolean NOT NULL,              -- carries an organisation word; false is "not shown to be", never "a person"
    company_number   text,                          -- only where the page prints one beside the name
    named_in         text NOT NULL,                 -- 'field: Entity Name', 'heading', 'heading, before its dash'
    split_from       text NOT NULL,                 -- 'semicolon', 'and between two legal names', 'as published'
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- a party a suppression the page states covers: its name as printed (ruling 142); the lane's own row carries the flag
CREATE TABLE IF NOT EXISTS fma_private.suppressed_names (
    key              text PRIMARY KEY,              -- the party's key in fma.parties
    action_key       text NOT NULL,
    ordinal          integer NOT NULL,
    name             text NOT NULL,
    company_number   text,
    named_in         text NOT NULL,
    suppressed_by    text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- an action whose page states a suppression: what its lane row leaves out
CREATE TABLE IF NOT EXISTS fma_private.suppressed_actions (
    key              text PRIMARY KEY,              -- the action's key in fma.actions
    slug             text NOT NULL,
    title            text,
    summary          text,
    outcome          text,
    url              text NOT NULL,
    suppressed_by    text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- every labelled field a warning prints besides its party, as printed: Address, Website, Email(s), Phone, Bank Name,
-- Account Number and the rest
CREATE TABLE IF NOT EXISTS fma_private.warning_fields (
    key              text NOT NULL,                 -- the action's key
    ordinal          integer NOT NULL,
    label            text NOT NULL,
    value            text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key, ordinal)
);

CREATE TABLE IF NOT EXISTS fma.read_set_aside (
    document  text,
    place     text NOT NULL,
    stage     text NOT NULL,
    reason    text NOT NULL
);
