-- registers/iwi_directory: every table this lane owns, in `iwi_directory`, in two parts. The capture's record
-- (capture.py makes it; never wiped): no capture table holds a row of the source; every page stays in the document
-- store verbatim by sha256. The reading's tables (load.py drops and makes them again at every load). The private
-- twin, `iwi_directory_private.entry_fields` (load.create_private): an organisation's people, phones, emails and
-- postal and physical addresses, every label not read onto a row, whole (ruling 142, 4 November 2026); never on a
-- row or a view (hard limit 15).

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per walk of the whole site from its home page, resumed until its frontier is empty
CREATE TABLE IF NOT EXISTS iwi_directory.capture_passes (
    pass_id      bigserial PRIMARY KEY,
    pages        integer NOT NULL DEFAULT 0,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

-- every address the walk found on the site, in the order found, and what became of it
CREATE TABLE IF NOT EXISTS iwi_directory.capture_frontier (
    pass_id    bigint NOT NULL REFERENCES iwi_directory.capture_passes (pass_id),
    url        text NOT NULL,
    ordinal    integer NOT NULL,
    found_on   text,                                -- NULL for a seed
    state      text NOT NULL DEFAULT 'todo' CHECK (state IN ('todo', 'landed', 'set aside', 'not asked')),
    kind       text,                                -- the page's shape (read.recognise) once landed
    sha256     text,
    why        text,                                -- 'not asked': a file, a form or a map; 'set aside': the reason
    at         timestamptz,
    PRIMARY KEY (pass_id, url)
);

CREATE TABLE IF NOT EXISTS iwi_directory.capture_set_aside (
    pass_id  bigint,
    item     text NOT NULL,
    stage    text NOT NULL,
    reason   text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- ── the reading
-- load.py drops these and makes them again at every load. Each row cites the page's sha256, page 1, its place, the
-- reader and the profile.

-- the ledger: one row per page the newest finished walk landed; pages in = read + not read (a site page) + set aside
CREATE TABLE IF NOT EXISTS iwi_directory.read_pages (
    url        text PRIMARY KEY,
    document   text NOT NULL,
    kind       text NOT NULL,
    state      text NOT NULL CHECK (state IN ('read', 'not read', 'set aside')),
    entities   integer NOT NULL DEFAULT 0,          -- rows the page gave before entities met on other pages merged
    relations  integer NOT NULL DEFAULT 0,
    iwi_links  text[] NOT NULL DEFAULT '{}'         -- the iwi pages a region or authority page links (check.py)
);

-- iwi, hapū, marae, organisations and governance entities as the site lists them
CREATE TABLE IF NOT EXISTS iwi_directory.entities (
    key                   text PRIMARY KEY,         -- tkm/iwi/<slug>, tkm/hapu/<iwi slug>/<name>, tkm/marae/<name>/<location>, tkm/org/<name>
                                                    -- (tkm/org/<name>/<page slug> where its pages print names that differ, macrons kept)
    kind                  text NOT NULL CHECK (kind IN ('iwi', 'hapū', 'marae', 'organisation', 'governance entity')),
    name                  text NOT NULL,
    iwi_key               text,                     -- a hapū's iwi
    listed_as             text,                     -- the section the site lists it under (rohe, kind of organisation, kind of marae)
    region                text,                     -- an iwi's region map
    legal_entity          text,                     -- as printed
    governance_structure  text,                     -- as printed
    hapu_represented      text,                     -- as printed
    area_of_interest      text,                     -- as printed
    local_authorities     text,                     -- as printed under an organisation
    primary_purpose       text,                     -- as printed (other Māori organisations)
    website               text,
    wharenui              text,                     -- a marae's
    location              text,                     -- a marae's own location, as printed
    flags                 text[] NOT NULL,          -- each role the page marks, '<role>: <as printed> [<bracket>]'
    charity_number        text,                     -- only where the page prints one
    nzbn                  text,                     -- only where the page prints one
    last_updated          text,                     -- an organisation's entry, as printed (dd/mm/yyyy)
    pages                 integer NOT NULL DEFAULT 1, -- pages that list it
    url                   text NOT NULL,
    document              text NOT NULL,
    page                  integer NOT NULL,
    place                 text NOT NULL,
    read_from             text NOT NULL,
    reader                text NOT NULL,
    profile               text NOT NULL,
    profile_version       integer NOT NULL,
    loaded_at             timestamptz NOT NULL DEFAULT now()
);

-- hapū of iwi, marae of hapū (or of iwi where the page has no hapū column), organisation of iwi, iwi in region,
-- an iwi's rohe in a local authority
CREATE TABLE IF NOT EXISTS iwi_directory.relations (
    key              text PRIMARY KEY,              -- <from key>|<relation>|<to key or name>
    from_key         text NOT NULL,
    relation         text NOT NULL,
    to_key           text,                          -- NULL where the other side is a name only (a region, an authority)
    to_name          text,
    section          text,
    url              text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- the settlement a governance entity's flag names (its Act, or a deed signed), and a mandate's stage
CREATE TABLE IF NOT EXISTS iwi_directory.settlements (
    key              text PRIMARY KEY,              -- the row's own: <entity key>|<settlement key>, or <entity key>|no settlement named
    settlement_key   text,                          -- the settlement's, shared by each body whose entry names it: tkm/settlement/<act>,
                                                    -- tkm/settlement/<entity>/<date>, tkm/mandate/<entity>; NULL where the entry names none
    entity_key       text NOT NULL,
    iwi_key          text,
    name             text,
    act              text,
    act_year         integer,
    stage            text NOT NULL,                 -- 'settled: Act', 'settled: deed signed', 'collective settlement', 'mandate recognised', 'settled: as printed',
                                                    -- 'settled: none named' (the post-settlement flag's own words, no settlement beside them)
    signed_on        text,                          -- as printed
    as_printed       text NOT NULL,
    url              text NOT NULL,
    document         text NOT NULL,
    page             integer NOT NULL,
    place            text NOT NULL,
    read_from        text NOT NULL,
    reader           text NOT NULL,
    profile          text NOT NULL,
    profile_version  integer NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- labels left unread, by name, with the pages that carry them (never a value): the profile's drift record
CREATE TABLE IF NOT EXISTS iwi_directory.read_unread_labels (
    label  text PRIMARY KEY,
    pages  integer NOT NULL
);

CREATE TABLE IF NOT EXISTS iwi_directory.read_set_aside (
    document  text,
    place     text NOT NULL,
    stage     text NOT NULL,
    reason    text NOT NULL
);
