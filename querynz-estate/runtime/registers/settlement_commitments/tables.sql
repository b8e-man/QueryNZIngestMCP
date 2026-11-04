-- registers/settlement_commitments: every table this lane owns, in `settlement_commitments`. The capture's record
-- (capture.py makes it; never wiped): what each weekly watch asked and whether the login wall answered. No table holds
-- a row of the source: the lane holds no settlement or commitment (its position: the records sit behind a login, and
-- Te Tari Whakatau's terms bar data collection). The pages stay in the document store verbatim by sha256.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per request the watch made: the records address (is the wall still there?) or a page about the source
CREATE TABLE IF NOT EXISTS settlement_commitments.capture_watch (
    at        timestamptz NOT NULL DEFAULT now(),
    url       text NOT NULL,
    purpose   text NOT NULL CHECK (purpose IN ('records', 'about the source')),
    status    integer,
    sha256    text,
    answer    text NOT NULL,                        -- 'wall', 'open', 'set aside: <why>'
    PRIMARY KEY (at, url)
);

-- ── the reading
-- Nothing is read: no reading table exists until the records are open to us and a position says so.
