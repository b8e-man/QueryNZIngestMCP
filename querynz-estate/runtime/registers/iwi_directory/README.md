# registers.iwi_directory

The iwi and hapū directory, Te Kāhui Māngai (Te Puni Kōkiri), for template 3 (plan step 6.2, use case 14: the
post-settlement governance map). The site walked whole by `capture.py`, landed verbatim by hash, and read by shape
(`read.py`, five profiles) into iwi, hapū, marae, organisations and governance entities, how they relate, and the
settlement a governance entity's entry names. An organisation's people and contact details are captured with the
page and kept whole in `iwi_directory_private.entry_fields`, never on a row or a view (ruling 142). No model (ruling 79). Built by settlements-1: `spec.md`, `capture.py`, `read.py`, `load.py`,
`publish.sql`, `check.py`, `sample.list`, `tests/`, `profiles-proposed.jsonl` and the position page.
