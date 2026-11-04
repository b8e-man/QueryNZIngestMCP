# Large-donation disclosures, on the board

One row of `pub.disclosures` is one declaration the Electoral Commission lists.

| Pane part | What |
| --- | --- |
| Title | The donor as the Commission prints it, then the party |
| Fields | Amount (and the amount before an amendment, where printed); the regime and its floor; the Commission's note verbatim; the itemised gifts (`pub.disclosure_items`) as printed, under the declaration |
| Dates | Both, named: the day the party received the gift (`given_on`) and the day the Commission received the declaration (`received_on`); `amended_on`, `withdrawn_on` and `returned_on` where stated |
| Citation | The Commission's table (`document`, `place`) and the scanned declaration (`declaration_document`, or "not held" with the Commission's link) |
| Flags | `amendment` other than none; `at_or_under_threshold`; `items_check` differs; `party` unresolved |

An amended declaration is one row carrying the amended figures; it is never summed with its original. No address is shown: the donor cell's address lines are private.
