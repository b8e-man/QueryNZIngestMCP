# registers/building_practitioners — licensed building practitioners

Step 5.3 (for use cases 6, 7 and 12). Under part 4 of the Building Act 2004:
one row per published disciplinary decision of the Building Practitioners
Board (`capture.py`, `read.py`), and one row per licensed practitioner from
the public register, copied on ruling 132 (`register.py`: licence number,
names, licence classes with areas of practice, status, the town and region
the register publishes, the date first granted). No postcode, email or
telephone is read; the town carries an address flag (ruling 102).

Built by `sanctions-1`, with `registers/sanctions/` and
`registers/limited_partnerships/`; the register's copy by the
building-practitioners-register session, 2 November 2026.
