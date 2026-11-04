# Views this lane publishes, for the integrator to catalogue on the board (in the merge after the lane's)

- `pub.councillor_interest_registers` — key `council`; the 78 councils: `host`, `form`, `landing_url`,
  `landing_sha256`, `documents_held`, `members_read`, `why`, `loaded_at`. No person on it.
- `pub.councillor_interests` — key `key`; from a structured register page: `council`, `member`, `role`, `category`,
  `entries`, `as_at`, `source`; citation `document`, `page`, `place`, `url`, `read_from`, `reader`, `profile`,
  `profile_version`, `loaded_at`, `kind`, `model`, and the flags `real_property`, `of_partner`, `private_entries`.
  Names elected members (public office-holders) with every declared interest as the council publishes it; an
  address-shaped entry is counted in `private_entries` and held in the private twin.
  It names people: it stays off the public site unless Arthur says otherwise (hard limit 14). Proven in
  `querynz_v4_sample.scratch_councils_1` (Invercargill: 15 members, 56 category rows) and on the sample.
