-- registers/charities: every table this lane owns, in `charities` and `charities_private`, in two parts.
-- The capture's record (capture.py makes it; never wiped): no capture table holds a row of the register, the pages
-- stay in the document store verbatim by sha256. The reading's tables (load.py drops and makes them again at every
-- load, from the pages; the Opus build kept at step 4.1): every row a typed row of one feed row or a catch-log line.
-- No officer's address, birth date, email or phone is read (the feed's Officers carry no address or birth date);
-- a charity's address for service is the one address, held in `charities_private.addresses`.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per pass over one entity set of the feed: a full copy, or the rows changed since a date
CREATE TABLE IF NOT EXISTS charities.capture_passes (
    pass_id       bigserial PRIMARY KEY,
    entity_set    text NOT NULL,                     -- the feed's name: Organisations, Officers, AnnualReturn, ...
    mode          text NOT NULL CHECK (mode IN ('full', 'changes', 'whole')),   -- whole: a small set in one request
    since         timestamptz,                       -- changes: ModifiedOn on or after this; NULL for full
    stated        integer,                           -- the feed's own count for the pass's filter ($inlinecount), at its first page
    next_key      bigint,                            -- the last key landed; the pass resumes after it
    pages         integer NOT NULL DEFAULT 0,        -- pages landed
    rows_landed   integer NOT NULL DEFAULT 0,        -- rows in the pages landed
    set_aside     integer NOT NULL DEFAULT 0,        -- pages that failed (catch log lines for this pass)
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz                        -- NULL while the pass is half-done
);
CREATE INDEX IF NOT EXISTS capture_passes_open ON charities.capture_passes (entity_set) WHERE finished_at IS NULL;

-- the listing: one row per page landed, in order, with its hash; a pass's pages are its documents
CREATE TABLE IF NOT EXISTS charities.capture_pages (
    pass_id     bigint NOT NULL REFERENCES charities.capture_passes (pass_id),
    page_no     integer NOT NULL,                    -- 1, 2, ... within the pass
    entity_set  text NOT NULL,
    url         text NOT NULL,                       -- exactly as asked
    sha256      text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    rows        integer NOT NULL,
    first_key   bigint,
    last_key    bigint,
    new         boolean NOT NULL,                    -- false: the same bytes were already held
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pass_id, page_no)
);
CREATE INDEX IF NOT EXISTS capture_pages_sha ON charities.capture_pages (sha256);

-- the catch log: one line for every page the capture could not take, with the stage and the reason
CREATE TABLE IF NOT EXISTS charities.capture_set_aside (
    pass_id   bigint REFERENCES charities.capture_passes (pass_id),
    item      text NOT NULL,                         -- the URL asked
    stage     text NOT NULL,                         -- fetch | parse | order | land
    reason    text NOT NULL,
    at        timestamptz NOT NULL DEFAULT now()
);

-- ── the reading ──────────────────────────────────────────────────────────────

-- one row per page read: the reading's ledger (rows in = typed + set aside, page by page)
CREATE TABLE IF NOT EXISTS charities.read_pages (
    document     text PRIMARY KEY CHECK (document ~ '^[0-9a-f]{64}$'),
    entity_set   text NOT NULL,
    rows         integer NOT NULL,                  -- rows on the page
    typed        integer NOT NULL,                  -- rows read into a table
    set_aside    integer NOT NULL,                  -- rows in the catch log, superseded ones included
    skipped      integer NOT NULL DEFAULT 0         -- rows a sample fill passed over (always 0 on a full load)
);

-- the code lists' entries, as read: what every resolved name on the tables below came from
CREATE TABLE IF NOT EXISTS charities.codes (
    code_list  text NOT NULL,                       -- RegistrationStatus, MainSector, ReportingTier, ...
    entity     text NOT NULL DEFAULT '',            -- the list's EntityName (Groups, Organisations, ...), '' where none
    code       integer,
    name       text NOT NULL,
    document   text NOT NULL
);

-- the group registrations (a group files returns for its members)
CREATE TABLE IF NOT EXISTS charities.groups (
    key              text PRIMARY KEY,              -- charities/<the group's own register number>
    number           text NOT NULL,
    group_id         integer NOT NULL UNIQUE,       -- the feed's GroupId
    name             text,
    status           text,
    registered_on    date,
    deregistered_on  date,
    source_modified_at timestamptz,                 -- the register's own ModifiedOn; never a date of anything
    absent_since       date,                        -- the register's newest full copy (finished this day) no longer holds the row
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL,
    reader text NOT NULL, profile text NOT NULL, profile_version integer NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS charities.charities (
    key                    text PRIMARY KEY,        -- charities/CC12345: the register's own number, as filed
    number                 text NOT NULL UNIQUE,
    organisation_id        integer NOT NULL UNIQUE, -- the feed's OrganisationId
    name                   text,
    other_names            text,
    status                 text,                    -- Registered, Deregistered, Removed, ... (code list RegistrationStatus)
    registered_on          date,
    deregistered_on        date,
    deregistration_reason  text,
    legal_structure        text,                    -- code list LegalStructure
    legal_structure_other  text,
    charitable_purpose     text,
    main_sector_id         integer, main_sector      text,   -- resolved through MainSector
    main_activity_id       integer, main_activity    text,   -- MainActivity
    main_beneficiary_id    integer, main_beneficiary text,   -- MainBeneficiary
    group_key              text,
    group_number           text,
    group_name             text,
    group_type             integer,                 -- the feed's GroupType code, as filed
    nzbn                   text,
    incorporation_number   text,                    -- the feed's CompaniesOfficeNumber, as filed
    year_end_month         integer,
    year_end_day           integer,
    annual_return_due_on   date,
    source_modified_at     timestamptz,
    absent_since              date,                 -- the newest full copy (finished this day) no longer holds the row
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL,
    reader text NOT NULL, profile text NOT NULL, profile_version integer NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS charities.officers (
    key                       text PRIMARY KEY,     -- charities/officers/<OfficerId>
    officer_id                integer NOT NULL UNIQUE,
    charity_key               text NOT NULL,
    organisation_id           integer NOT NULL,
    kind                      text NOT NULL CHECK (kind IN ('person', 'body corporate')),
    full_name                 text NOT NULL,        -- rebuilt from the parts left when a name field is withheld
    first_name                text,
    middle_name               text,
    last_name                 text,
    name_note                 text,                 -- which name field was withheld and why (a date, an address); never its value
    suppressed                boolean NOT NULL DEFAULT false,   -- a suppressed name: blanked on every view, the row kept
    role                      text,                 -- PositioninOrganisation, as filed
    started_on                date,                 -- PositionAppointmentDate
    ended_on                  date,                 -- LastDateAsAnOfficer: the register's own day, never a load day
    ended_on_stated           boolean NOT NULL,
    status                    text,                 -- code list OfficerStatus: Qualified, Past, Disqualified, ...
    disqualified              boolean NOT NULL,     -- the register's status says Disqualified or Removed as Disqualified
    declared_not_disqualified boolean,              -- the feed's IsNotDisqualified, as filed
    source_modified_at        timestamptz,
    absent_since              date,                 -- the newest full copy (finished this day) no longer holds the row
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL,
    reader text NOT NULL, profile text NOT NULL, profile_version integer NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS charities_officers_charity ON charities.officers (charity_key);

CREATE TABLE IF NOT EXISTS charities.returns (
    key                text PRIMARY KEY,            -- charities/returns/<AnnualReturnId>
    return_id          integer NOT NULL UNIQUE,
    charity_key        text,                        -- the organisation that filed it, or
    group_key          text,                        -- the group (a return may name both)
    organisation_id    integer,
    group_id           integer,
    period_end         date,                        -- YearEnded
    months_covered     integer,                     -- PerformanceReportCovers, where filed
    began_on           date,                        -- DateEntityBegan, where filed
    tier_id            integer,
    tier               text,                        -- code list ReportingTier
    currency           text,                        -- code list ReportingCurrency; empty where the return names none
    audited            boolean,                     -- IsFinancialReportAudited
    modified_opinion   boolean,                     -- IsModifiedAuditOpinionReceived
    opinion            text,                        -- code list AuditModifiedOpinionReceived
    status_code        integer,                     -- the feed's Status, as filed
    total_gross_income numeric, total_expenditure numeric, net_surplus numeric,
    total_assets       numeric, total_liabilities numeric, total_equity numeric,
    figures            jsonb NOT NULL,              -- every financial field the return files: feed name → number
    material_expenses  jsonb,                       -- [{label, amount}]
    source_modified_at timestamptz,
    absent_since              date,                 -- the newest full copy (finished this day) no longer holds the row
    document text NOT NULL, page integer NOT NULL, place text NOT NULL, read_from text NOT NULL,
    reader text NOT NULL, profile text NOT NULL, profile_version integer NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (charity_key IS NOT NULL OR group_key IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS charities_returns_charity ON charities.returns (charity_key);

-- the reading's catch log: one line for every feed row not read into a table, with the stage and the reason
CREATE TABLE IF NOT EXISTS charities.read_set_aside (
    entity_set  text NOT NULL,
    document    text NOT NULL,
    place       text NOT NULL,                     -- the row's key in the page
    stage       text NOT NULL,                     -- read | key | link | supersede
    reason      text NOT NULL
);

-- what was kept but could not be resolved, counted (an unknown code, a dropped address part)
CREATE TABLE IF NOT EXISTS charities.read_notes (
    note   text PRIMARY KEY,
    count  integer NOT NULL
);

-- a charity's address for service, as the register publishes it (its street address). publish.sql shows it for every
-- charity, with `address_not_body_corporate` where the charity is not a body corporate (ruling 143, 4 November 2026)
CREATE TABLE IF NOT EXISTS charities_private.addresses (
    key                  text PRIMARY KEY,           -- the charity's key (charities.charities.key)
    address_for_service  text NOT NULL,
    document text NOT NULL, page integer NOT NULL, place text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- a part of a charity's street address that holds an email address, kept whole apart from the address (ruling 142)
CREATE TABLE IF NOT EXISTS charities_private.address_parts (
    key       text NOT NULL,                       -- the charity's key
    field     text NOT NULL,                       -- the feed's field (StreetAddressLine2, ...)
    value     text NOT NULL,
    why       text NOT NULL,
    document text NOT NULL, page integer NOT NULL, place text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- an officer's name field that holds a date or reads as an address, kept whole (ruling 142); the officer's row
-- carries `name_note` saying which field and why
CREATE TABLE IF NOT EXISTS charities_private.officer_name_fields (
    key       text NOT NULL,                       -- the officer's key (charities.officers.key)
    field     text NOT NULL,                       -- FirstName, MiddleName, LastName, FullName, BodyCorporateName
    value     text NOT NULL,
    why       text NOT NULL,
    document text NOT NULL, page integer NOT NULL, place text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
