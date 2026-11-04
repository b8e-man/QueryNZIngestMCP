-- registers/candidate_returns: what may never be published (hard limit 15). A donor's street address, and the
-- name-and-address cell it was cut from, keyed by the published row's key. The session reader and the product login
-- are never granted this schema. Loaded by replacing `candidate_returns_private.`.
CREATE TABLE IF NOT EXISTS candidate_returns_private.addresses (
    key        text PRIMARY KEY,                      -- candidate_returns.donors.key
    document   text NOT NULL,
    address    text NOT NULL,                         -- the cell after the name, as read
    cell       text NOT NULL                          -- the whole cell, as read
);
