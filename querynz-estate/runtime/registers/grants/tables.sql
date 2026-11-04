-- registers/grants: every table the lane owns (contract: the lane). Two parts. The capture's record comes first and is
-- never wiped: the runs, every document landed with the list it came from, and the catch log. The reading's tables
-- follow the marker line below; load.py drops and makes them again at every load, inside one transaction. No table
-- here, and none in `grants_private`, holds an address: none of the layouts read prints one (hard limit 15), so the
-- private twin is made empty, for the contract's shape.

CREATE SCHEMA IF NOT EXISTS grants;
CREATE SCHEMA IF NOT EXISTS grants_private;

-- one run of the capture
CREATE TABLE IF NOT EXISTS grants.capture_runs (
    run_id      bigserial PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    requests    integer NOT NULL DEFAULT 0,
    landed      integer NOT NULL DEFAULT 0,
    set_aside   integer NOT NULL DEFAULT 0,
    stopped     text
);

-- every document a run landed, by its hash, with the list that asked for it: `dia-file` (the national file of class 4
-- grants), `dia-file-page` (the catalogue's page that lists it), `lottery-page` (a page of Community Matters met on
-- the crawl), `about` (a page about a source: a licence, terms, a privacy notice), `society-page` (a class 4
-- society's own grants page) and `society-file` (a grants list it links, as a file); `publisher` is the society's
-- key there. `recognised` is the profile whose
-- shape it has, or null (a page the crawl walked through and the reading never reads)
CREATE TABLE IF NOT EXISTS grants.capture_docs (
    run_id      bigint NOT NULL REFERENCES grants.capture_runs (run_id),
    list        text NOT NULL,
    publisher   text NOT NULL,
    url         text NOT NULL,
    sha256      text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    recognised  text,
    new         boolean NOT NULL,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grants_capture_docs_list ON grants.capture_docs (list, url, at);
-- the lists, held by a named check so a new list is one line here (grants-2 added the societies' two)
ALTER TABLE grants.capture_docs DROP CONSTRAINT IF EXISTS capture_docs_list_check;
ALTER TABLE grants.capture_docs DROP CONSTRAINT IF EXISTS grants_capture_docs_list_check;
ALTER TABLE grants.capture_docs DROP CONSTRAINT IF EXISTS capture_docs_list_known;
ALTER TABLE grants.capture_docs ADD CONSTRAINT capture_docs_list_known
    CHECK (list IN ('dia-file', 'dia-file-page', 'lottery-page', 'about', 'society-page', 'society-file'));

-- the crawl's frontier for a site walked whole (the whole-site doctrine): every address met, and when it was asked
CREATE TABLE IF NOT EXISTS grants.capture_frontier (
    host      text NOT NULL,
    url       text NOT NULL,
    depth     integer NOT NULL,
    found_at  timestamptz NOT NULL DEFAULT now(),
    asked_at  timestamptz,
    status    integer,
    PRIMARY KEY (host, url)
);

-- the capture's catch log: a failed read, a block, a challenge, a page the gate refused
CREATE TABLE IF NOT EXISTS grants.capture_set_aside (
    run_id  bigint REFERENCES grants.capture_runs (run_id),
    item    text NOT NULL,
    stage   text NOT NULL,
    reason  text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);

-- ── the reading: rebuilt from the listed documents at every load (load.py)

-- one per grant as published. `publisher_key` published the document; `grantor_key` made the grant (a society, or
-- the Lottery Grants Board through `committee`). The recipient exactly as printed; the NZBN and the charity number
-- only where the publisher printed a valid one beside it. `amount_nzd` is the granted amount of an accepted grant;
-- every figure is also kept as published. `period` is the year of decision (the national file) or the financial
-- year (a Lottery record), or a society list's decision date or its period as printed ('2025-07-01/2025-09-30');
-- `round` is the Lottery's round as printed. A society's own list adds its application number, its reason for a
-- decision and its declared conflicts of interest, each as printed
CREATE TABLE grants.grants (
    key                            text PRIMARY KEY,
    publisher_key                  text NOT NULL,
    grantor_key                    text NOT NULL,
    grantor_as_published           text NOT NULL,
    committee                      text,
    recipient_key                  text NOT NULL,
    recipient_as_published         text NOT NULL,
    recipient_final_as_published   text,
    recipient_kind                 text NOT NULL,
    nzbn_as_published              text,
    nzbn                           text,
    charity_number_as_published    text,
    charity_number                 text,
    status                         text NOT NULL,
    amount_requested_as_published  text,
    amount_granted_as_published    text,
    amount_nzd                     numeric,
    multi_year                     text,
    purpose_as_published           text,
    category_1                     text,
    category_2                     text,
    decided_on                     date,
    decided_on_as_published        text,
    period                         text NOT NULL,
    round                          text,
    is_refund                      text,
    refunded_on                    date,
    refunded_on_as_published       text,
    amount_refunded_as_published   text,
    benefits                       text,
    territorial_authority          text,
    other_territorial_authority    text,
    region                         text,
    application_as_published       text,
    reason_as_published            text,
    interest_as_published          text,
    document                       text NOT NULL,
    page                           integer NOT NULL,
    place                          text NOT NULL,
    read_from                      text NOT NULL,
    reader                         text NOT NULL,
    profile                        text NOT NULL,
    profile_version                integer NOT NULL,
    loaded_at                      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX grants_grants_grantor ON grants.grants (grantor_key, period);
CREATE INDEX grants_grants_recipient ON grants.grants (recipient_key);

-- one per grantor and recipient as published: never joined across grantors, never looked up. `kind` says only what
-- the printed name and numbers show ('organisation (a number printed)', 'organisation (by its name)', 'not shown to be
-- an organisation'); the citation is the first grant read for it
CREATE TABLE grants.recipients (
    key                text PRIMARY KEY,
    grantor_key        text NOT NULL,
    publisher_key      text NOT NULL,
    name_as_published  text NOT NULL,
    kind               text NOT NULL,
    nzbn               text,
    charity_number     text,
    grants             integer NOT NULL,
    accepted           integer NOT NULL,
    declined           integer NOT NULL,
    amount_nzd         numeric NOT NULL,
    first_period       text NOT NULL,
    last_period        text NOT NULL,
    document           text NOT NULL,
    page               integer NOT NULL,
    place              text NOT NULL,
    read_from          text NOT NULL,
    reader             text NOT NULL,
    profile            text NOT NULL,
    profile_version    integer NOT NULL,
    loaded_at          timestamptz NOT NULL DEFAULT now()
);

-- one per publisher or grantor: the Department, the Lottery Grants Board, every society (read.publishers())
CREATE TABLE grants.publishers (
    key                  text PRIMARY KEY,
    name                 text NOT NULL,
    kind                 text NOT NULL,
    website              text,
    on_departments_list  boolean,
    licence              text NOT NULL,
    attribution          text NOT NULL,
    role                 text NOT NULL,
    grants               integer NOT NULL,
    loaded_at            timestamptz NOT NULL DEFAULT now()
);

-- the ledger: every listed document read, its records, and how many became grants or catch-log lines
CREATE TABLE grants.read_documents (
    document   text NOT NULL,
    list       text NOT NULL,
    url        text,
    profile    text,
    records    integer NOT NULL,
    grants     integer NOT NULL,
    set_aside  integer NOT NULL,
    stated     jsonb NOT NULL DEFAULT '{}'
);

-- the reading's catch log
CREATE TABLE grants.read_set_aside (
    document  text NOT NULL,
    place     text NOT NULL,
    stage     text NOT NULL,
    reason    text NOT NULL
);

-- counted notes about rows that were kept (a field read as Windows-1252, a spreadsheet day number)
CREATE TABLE grants.read_notes (
    document  text NOT NULL,
    note      text NOT NULL,
    count     integer NOT NULL
);
