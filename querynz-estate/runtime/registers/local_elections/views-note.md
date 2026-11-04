# The local elections lane's views, for the integrator to catalogue (in the merge after this lane's)

`publish.sql` makes two views. Proven in `querynz_v4_sample` on 22 October 2026
(the views made under `scratch_local_elections_1.pub_local_election_*` from the full build, the names rewritten: 2,183 and 96 rows).

| View | A row is | Key | Rows at the proof |
| --- | --- | --- | --- |
| `pub.local_election_returns` | one return a council's electoral officer lists (s 112F): council, election year, by-election, one candidate or a combined file, the candidate as listed, the seat the listing names, the return's kind as listed, the file's address, its sha256 once held and its state, the listing page cited by sha256 and address | `key` (council and file address) | 2,183 |
| `pub.local_election_returns_coverage` | a council's election: returns listed, combined files, files held, files failed | council, election_year, by_election | 96 |

No amount, no donor and no address on either (the returns are held unread, ruling 79; hard limit 15). A
candidate's name is as the listing prints it and is never matched to a person by this lane: the links decide that.

For `products/board/catalogue.py`, beside `candidate_returns` (register `local_elections`; label "Local election
candidate returns"):

```python
    # ── local election returns (built; pane.md: local_elections; added at local-elections-1) ──
    View("local_election_returns", "local_elections", "document", ("candidate_as_listed", "council", "election_year"),
         search=("candidate_as_listed", "council", "position"),
         fields=(("council", "council"), ("election", "election_year"), ("by-election", "by_election"),
                 ("covers", "covers"), ("seat", "position"), ("kind", "return_kind"), ("file held", "file_state"),
                 ("file", "file_document")),
         urls=("file_url", "listing_url"),
         names=("candidate_as_listed",),
         note="held, not read: no amount and no donor until the returns' reading (ruling 79)",
         default_order="election_year"),
    View("local_election_returns_coverage", "local_elections", "figure", ("council", "election_year"),
         search=("council",),
         fields=(("by-election", "by_election"), ("returns listed", "returns_listed"),
                 ("combined files", "combined_files"), ("files held", "files_held"), ("files failed", "files_failed")),
         default_order="council"),
```
