# Views this lane publishes, for the integrator to catalogue on the board (in the merge after the lane's)

- `pub.council_meetings` — key `key`; one row per meeting row of an InfoCouncil council's own listing: `council`,
  `body`, `meeting_date`, `meeting_time`, `kind`, `code`, `documents`, `minutes_file`, `minutes_url`,
  `minutes_sha256`, `minutes_held`; citation `document` (the listing's sha256), `page`, `place`, `listing_url`,
  `read_from`, `reader`, `profile`, `profile_version`, `loaded_at`. No person on it. Proven in
  `querynz_v4_sample.scratch_councils_1` (21 listings, 1,347 meetings) and on the sample (5 listings).
