-- registers/worksafe: every table this lane owns, in `worksafe` and its private twin, in two parts. The capture's
-- record (capture.py makes it; never wiped): no capture table holds a row of the source; the listing pages, court
-- summaries and undertakings stay in the document store verbatim by sha256. The reading's tables (load.py drops and
-- makes them again at every load). `worksafe_private` holds what the lane's own tables leave out, kept whole (ruling
-- 142, 4 November 2026): every headed section a page prints (the facts in brief, the incident, the lessons, which
-- describe the victims and the place), and what the page prints in a withheld name's place with the heading, slug and
-- address. An item WorkSafe takes down stays, flagged with the date of the first finished pass that no longer listed it.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per pass over a listing: its stated total (the listing's own :total) and how far it has got
CREATE TABLE IF NOT EXISTS worksafe.capture_passes (
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
CREATE TABLE IF NOT EXISTS worksafe.capture_pages (
    pass_id   bigint NOT NULL REFERENCES worksafe.capture_passes (pass_id),
    page_no   integer NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    items     integer NOT NULL,
    PRIMARY KEY (pass_id, page_no)
);

-- what each pass listed: the item's slug, address and fingerprint (its date, title and status as listed)
CREATE TABLE IF NOT EXISTS worksafe.capture_listed (
    pass_id   bigint NOT NULL REFERENCES worksafe.capture_passes (pass_id),
    list      text NOT NULL,
    slug      text NOT NULL,
    url       text NOT NULL,
    card      text NOT NULL,
    ordinal   integer NOT NULL,
    PRIMARY KEY (pass_id, slug)
);

-- the items landed: one row per fetch, so an item fetched again (its card changed) keeps its older hash too
CREATE TABLE IF NOT EXISTS worksafe.capture_items (
    list      text NOT NULL,
    slug      text NOT NULL,
    url       text NOT NULL,
    card      text NOT NULL,
    sha256    text NOT NULL,
    at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (list, slug, sha256)
);

-- the documents about the source (the copyright statement, the privacy statement)
CREATE TABLE IF NOT EXISTS worksafe.capture_docs (
    name      text NOT NULL,
    url       text NOT NULL,
    sha256    text NOT NULL,
    new       boolean NOT NULL,
    at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS worksafe.capture_set_aside (
    pass_id  bigint,
    item     text NOT NULL,
    stage    text NOT NULL,
    reason   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- load.py drops these and makes them again at every load. Each row cites the page's sha256, page 1, its place, the
-- reader and the profile. The facts as the page states them; nothing inferred.

-- the ledger: one row per item the newest finished pass of each list listed; items in = read + set aside + not captured
CREATE TABLE IF NOT EXISTS worksafe.read_items (
    list       text NOT NULL,
    slug       text NOT NULL,
    pass_id    bigint,
    document   text,                                -- NULL: listed and not yet captured
    state      text NOT NULL CHECK (state IN ('read', 'set aside', 'not captured')),
    parties    integer NOT NULL DEFAULT 0,
    taken_down_on date,                             -- the first finished pass that no longer listed it; NULL: listed now
    PRIMARY KEY (list, slug)
);

CREATE TABLE IF NOT EXISTS worksafe.actions (
    key              text PRIMARY KEY,              -- worksafe/prosecution/<slug> or worksafe/undertaking/<slug>
    kind             text NOT NULL,                 -- 'prosecution' or 'enforceable undertaking'
    slug             text,                          -- NULL where a name is withheld (the slug carries it)
    title            text,                          -- the heading as published; NULL where a name is withheld
    title_withheld   boolean NOT NULL,
    industry         text,
    offence_when     text,                          -- the date of offence as stated ('Between … and …')
    offence_on       date,                          -- the day, only where the field states one day
    section_charged  text,                          -- the offence section as stated, a line per defendant joined by '; '
    acts             text[] NOT NULL,               -- each Act the section charged (or the alleged contravention) names
    sections         text[] NOT NULL,               -- an undertaking: each section its alleged contravention states
    charged_when     text,
    charged_on       date,
    court            text,
    plea             text,
    decision         text,
    decided_on       date,                          -- the final decision date
    fine_text        text,                          -- the fine imposed as stated
    fine_amount      numeric,                       -- only where the field states one figure
    reparation_text  text,                          -- the reparation and costs as stated
    status           text,                          -- an undertaking: 'In progress' or 'Complete'
    published_on     date,
    accepted_on      date,                          -- an undertaking's date accepted
    action_on        date,                          -- decided, else accepted, else published
    url              text,                          -- NULL where a name is withheld (the address carries it)
    taken_down_on    date,                          -- WorkSafe took the item down by this date
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS worksafe.parties (
    key              text PRIMARY KEY,              -- <action key>/party/<n>
    action_key       text NOT NULL,
    ordinal          integer NOT NULL,
    name             text,                          -- the duty holder as published; NULL where withheld (hard limit 16)
    withheld         boolean NOT NULL,
    withheld_by      text,
    organisation     boolean NOT NULL,              -- carries an organisation word; false is "not shown to be", never "a person"
    company_number   text,                          -- only where the page prints one beside the name
    named_in         text NOT NULL,                 -- 'field: Defendant name' or 'heading'
    split_from       text NOT NULL,                 -- 'and between two legal names' or 'as published'
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- a withheld party: what the page prints in its place (the name a stated suppression covers, the code, or the word),
-- kept whole (ruling 142); the lane's own row carries the flag
CREATE TABLE IF NOT EXISTS worksafe_private.suppressed_names (
    key              text PRIMARY KEY,              -- the party's key in worksafe.parties
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

-- an action with a withheld name: the heading, slug and address its lane row leaves out
CREATE TABLE IF NOT EXISTS worksafe_private.suppressed_actions (
    key              text PRIMARY KEY,              -- the action's key in worksafe.actions
    slug             text NOT NULL,
    title            text,
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

-- every section a page prints under its own heading, as printed (facts in brief, the incident, lessons, highlights)
CREATE TABLE IF NOT EXISTS worksafe_private.page_sections (
    key              text NOT NULL,                 -- the action's key
    ordinal          integer NOT NULL,
    heading          text NOT NULL,
    text             text NOT NULL,
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

CREATE TABLE IF NOT EXISTS worksafe.read_set_aside (
    document  text,
    place     text NOT NULL,
    stage     text NOT NULL,
    reason    text NOT NULL
);
