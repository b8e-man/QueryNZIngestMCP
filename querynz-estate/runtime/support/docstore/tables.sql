-- The document store's tables, schema `docs` (plan 1.8, 1.10; docs/contracts/document-store.md).
-- A document is its bytes, keyed by sha256; its names are attributes. Idempotent.

CREATE TABLE IF NOT EXISTS docs.documents (
    sha256          text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size            bigint NOT NULL CHECK (size >= 0),
    kind            text NOT NULL,                 -- pdf, image, spreadsheet, web-page, text, csv, other
    source          text NOT NULL,                 -- the lane, or the old folder it was copied from
    content_sha256  text,                          -- web pages: the sameness hash of the canonical text
    fetched_at      timestamptz,                   -- when it was captured (as the capture says)
    landed_at       timestamptz NOT NULL DEFAULT now(),
    path            text NOT NULL,                 -- where the bytes are, under the store root
    withdrawn       text                           -- NULL, or why it was withdrawn (never deleted)
);

CREATE TABLE IF NOT EXISTS docs.names (
    sha256     text NOT NULL REFERENCES docs.documents (sha256),
    name       text NOT NULL,                      -- a file name, a URL, a folder path
    kind       text NOT NULL,                      -- file, url, old-path
    seen_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sha256, kind, name)
);
CREATE INDEX IF NOT EXISTS docs_names_name ON docs.names (name);

-- what each document has had extracted: per profile and field, the iteration of the profile's extract list it was
-- extracted at (support/docstore/extraction.py; Arthur, 3 November 2026). A ledger: never wiped by a load
CREATE TABLE IF NOT EXISTS docs.extractions (
    sha256     text NOT NULL REFERENCES docs.documents (sha256),
    profile    text NOT NULL,
    field      text NOT NULL,
    iteration  int NOT NULL CHECK (iteration >= 1),
    reader     text NOT NULL,
    model      text,
    at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sha256, profile, field)
);
CREATE INDEX IF NOT EXISTS docs_extractions_profile ON docs.extractions (profile, field, iteration);

-- the landing log: every attempt, so a failed landing is retried and a
-- document is never registered before it lands
CREATE TABLE IF NOT EXISTS docs.landings (
    landing_id  bigserial PRIMARY KEY,
    sha256      text,
    source      text NOT NULL,
    name        text,
    ok          boolean NOT NULL,
    new         boolean NOT NULL DEFAULT false,
    why         text,
    at          timestamptz NOT NULL DEFAULT now()
);
