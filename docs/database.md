# De database — `koopjes.db`

[← README](../README.md) · [alle naslag](README.md)

De SQLite-database waar alles in terechtkomt: WAL-modus, wat erin staat, en hoe de oude CSV/JSON-bestanden zich ertoe verhouden.

## SQLite mirror — `--db`

The database runs in sqlite's write-ahead mode (since 02-10-2026): a round
or the live server reading thousands of listings no longer makes a click on
the live server fail with "database is locked", and a write waits up to 30 s
for another one. While it is open there are two more files next to it,
`koopjes.db-wal` and `koopjes.db-shm`: they are part of the database (don't
delete them separately; copy the database only when nothing has it open).
Should a click still find it busy, the page says so and nothing is saved.

Every run also mirrors its listings into a local SQLite database
(`koopjes.db` by default, created automatically), on top of — not instead
of — the CSV/JSON files the crawler writes: every field the script parses (price, city,
condition, frame size, bid status, ...) gets upserted per listing, a
`crawl_run` row logs the query and page count, and `seen_listings.json` /
`reference_prices.csv` / `reference_price_history.csv` get re-imported into
the same database so it stays in sync with them. Only a full crawl
(`--pages 0`) marks previously-seen listings for that query as disappeared
if they no longer turn up — a shallow `--pages 3` run only looked at part of
the market, so it never draws that conclusion. Neither does a `--pages 0`
crawl that didn't see every result: Marktplaats stops paging after about
5000 listings (167 pages; "racefiets" has 26000+ results), a page can fail
to load, and the default sort order repeats listings across pages. A page
that fails gets one more try after 60 seconds (seen 28-09-2026: a single 403
from Marktplaats between two good requests); only a second failure ends the
crawl as incomplete. With `--delay 0` there is no wait. The sweep
only runs when the number of distinct listings seen matches the total
Marktplaats reports, and says why it skipped otherwise — use a narrower query
(e.g. "giant defy"), `--category`, and `--sort newest` for the full crawl
whose disappearances you want to count.

One exception: a crawl that loaded every page but missed just a few (at
most 3, or 2% of the total). That is what happens when a listing is sold
*while* the crawl pages through the results — everything after it shifts up
a place and one listing lands on a page already fetched. Such a crawl notes
the listings it missed (`missed_at`) without calling them gone; a listing
missed by the next full crawl as well is marked disappeared as of its first
miss, and one that turns up again in any crawl is cleared. The console says
`verdwijn-sweep voorlopig` when this happens. The database remembers every query that
found a listing (table `listing_query`), so a Defy last seen by the daytime
"racefiets" run still counts for the nightly "giant defy" sweep. It also
remembers when a crawl first saw a listing marked reserved
(`listing.reserved_at`, migration 9; cleared when a crawl sees it unreserved
again). A reserved listing that is still online doesn't count as a comparable
price for the bike computers, just as within a run; once it disappears it
counts like any other gone listing. `valuation.py` reads from this
database (see [eigen-fiets.md](eigen-fiets.md)); disable writing to it entirely with `--no-db`.
