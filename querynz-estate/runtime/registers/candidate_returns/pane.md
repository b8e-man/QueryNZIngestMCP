# Candidate returns, on the board

One pane per return read: the candidate, electorate, party and election as the Commission lists them; the declared
donations (Parts A, C, D and the total), expenses (F, G and the total) and, on the 2023 form, loans (Part H), each with
the check it passed (`parts-sum`, `total`, `step-cell`, `declared-nil`); the Commission's own spreadsheet figures
beside ours, a difference marked; whether the figures were read from a text layer or from pixels (weaker, and said
so); the return itself as the citation (its hash and the declaration page). A replaced return shows the amendment the
Commission's listing links in its place, and is never summed. Set-aside returns show their stage and reason: most
are scans waiting for a page reading. No donor's address appears on any pane.

A candidate whose return is not read shows the Commission's own row from its summary spreadsheet instead (`read_from`
'commission'): the candidate, electorate, party and election as the spreadsheet lists them, its donations, expenses and
(2023) loans as the Commission's figures, marked "the Commission's figure; no return read", with no parts, no checks and
no "ours" beside them, and the spreadsheet as the citation (its hash, the sheet's name and the row). It is told apart
from a read return by `read_from` alone (`text`, `pixels`, or `commission`); the template does the same. When the
return is read, its row takes the Commission's row's place.
