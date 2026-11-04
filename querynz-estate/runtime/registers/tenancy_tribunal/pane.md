# Tenancy Tribunal orders, on the board

One pane, counts only (no names, no addresses, nothing from inside an order):

- **Held:** `select count(*) filter (where document is not null), count(*) from tenancy_tribunal.orders`:
  orders landed, of orders listed.
- **At risk:** `select count(*) from tenancy_tribunal.orders where document is null and unpublished_date < current_date + 14`:
  listed, not yet held, and leaving the source within two weeks. Above zero is the number that matters.
- **Against the source:** `python -m registers.tenancy_tribunal.check`: months equal, short, past the window.
- **Kept whole:** `python -m registers.tenancy_tribunal.check` is counts only; the listing rows kept whole (names and
  the tenancy address among them, ruling 143) are in `tenancy_tribunal_private.listing_rows`, which this pane does not read.
- **Set aside:** `select stage, count(*) from tenancy_tribunal.set_aside group by stage`.
- **Last run:** the newest `qv4-tenancy-tribunal-capture` run record: requests, landed, why it stopped.
