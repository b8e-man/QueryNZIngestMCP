-- registers/council_procurement: every table this lane owns, in `council_procurement`. The capture's record
-- (capture.py makes it; never wiped): what each monthly watch asked of the four pages whose words keep councils' own
-- award and tender lists out, and whether they still say them. No table holds a row of the source (position
-- `council-procurement-platforms`). The pages stay in the document store verbatim by sha256.

-- ── the capture ──────────────────────────────────────────────────────────────

-- one row per request the watch made
CREATE TABLE IF NOT EXISTS council_procurement.capture_watch (
    at        timestamptz NOT NULL DEFAULT now(),
    url       text NOT NULL,
    status    integer,
    sha256    text,
    answer    text NOT NULL,                        -- 'bars', 'changed', 'set aside: <why>'
    PRIMARY KEY (at, url)
);

-- ── the reading
-- Nothing is read: no reading table exists until a council's leave or a changed page and a fresh position allow it.
