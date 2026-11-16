# Zoeken op Marktplaats — `racefiets_jev.py`

[← README](../README.md) · [alle naslag](README.md)

De crawler zelf: één zoekopdracht (of een watchlist) ophalen, filteren en als rapport wegschrijven. Alle vlaggen, categorieën, sortering, biedadvertenties, groepsetherkenning en watchlists. Wie de rondes laat draaien (zie [rondes.md](rondes.md)) typt deze commando's zelden zelf.

`racefiets_jev.py` searches [Marktplaats](https://www.marktplaats.nl) for
listings matching a query — road bikes ("racefiets") by default, but `--query`
works for anything (`--query luidsprekers`, `--query "canon eos"`, ...) — and
flags ones priced well below the median of what it found as a quick way to
spot bargains. Every listing also gets a single 0-100 **dealscore** combining
all the price signals it knows about, and the report is sorted by it, so the
best deal is the top row (see "Dealscore" in [rapport.md](rapport.md)). The frame-height/groupset
features below are bike-specific and simply find nothing to match on other
queries, which is harmless.

Pick a query term that's actually specific to what you want: Marktplaats'
own category data is used to filter out unrelated results (see "Off-topic
results" below), but that only works if your query has one clear dominant
category to begin with. E.g. `luidsprekers` (speakers) works well; `boxen`
doesn't — on Marktplaats that word matches baby playpens far more often
than speakers.

## Usage

```bash
pip install -r requirements.txt
python racefiets_jev.py --pages 10
python racefiets_jev.py --query luidsprekers --pages 10
```

Comma-separate multiple terms to run them in one go, e.g.
`--query "racefiets,luidsprekers"` — each gets its own HTML/CSV report (named
after the query), while the history/log/reference files stay shared. Only do
this when the same filters (`--max-price`, etc.) make sense for both —
`--min-frame-height`/`--max-frame-height` in particular would wipe out every
result for a non-bike query, since those listings never have a frame size.
Run the script separately per query instead when the filters need to differ,
or save the search as a watchlist (see below) — a watchlist carries its own
filters.

Listings marked with `*` are priced at or below `--bargain-ratio` (default
`0.6`, i.e. 60%) of the median price across all listings fetched. That median
(and the average next to it) is taken over listings with a real asking price:
a priceless one and a "gratis" one at €0 are both left out, since neither says
anything about what the thing costs. Every
priced listing also shows `% v. mediaan` — what percentage of the median
price it's asking, e.g. `24%` means it's asking a quarter of the median — so
you can judge relative cheapness on a scale instead of only the binary `*`
cutoff. In the HTML report this is a sortable column; it also feeds the
dealscore the report is sorted by.

Every run also writes `racefiets_report.html` — open it in a browser for a
sortable, filterable overview (Nieuw / Koopjes / Topdeals / Bieden / ...) with
clickable links to each listing, and the average/median price of what was
found. The page is built from `report_template.html`, which has to sit next to
the script (run with `--no-html` if you don't want a report). It compares against
`seen_listings.json` (created automatically) so listings you've already seen
in a previous run are marked accordingly instead of showing up as "new" every
time — handy if you run this script on a schedule (e.g. every 15 minutes via
cron / Task Scheduler). When there are new listings, the report also opens
automatically in your browser (see `--open-browser` below).

Every newly found bargain also gets appended to `bargains_log.csv` — unlike
`--output`, which is a snapshot that gets overwritten each run, this keeps
growing, so you end up with a history of every bargain ever spotted.

## Options

| Flag | Description | Default |
| --- | --- | --- |
| `--query` | Search query | `racefiets` |
| `--pages` | Number of result pages to fetch (30 listings/page). `0` = fetch everything Marktplaats allows browsing to (see note below) | `1` |
| `--min-price` / `--max-price` | Filter by price in EUR | none |
| `--min-frame-height` / `--max-frame-height` | Filter by frame size in cm; bikes without a stated size are kept (see below) | none |
| `--strict-frame-height` | With the frame size filter, also drop bikes that don't state a size | off |
| `--sort` | `optimized` (Marktplaats' own "Standaard" order) or `newest` (newest first — use this for scheduled runs, see below) | `optimized` |
| `--category` | Only search these Marktplaats categories (comma-separated key or number, e.g. `fietsonderdelen`), filtered by Marktplaats itself, or `alle` for every category (see below) | none |
| `--bargain-ratio` | Fraction of the median price at/below which a listing is flagged | `0.6` |
| `--delay` | Seconds between page requests | `1.5` |
| `--output` | Write results to a CSV file | none |
| `--html` | Path to write the HTML overview to | `racefiets_report.html` |
| `--no-html` | Skip writing the HTML overview | off |
| `--history-file` | Path to the file that remembers which listings were already seen | `seen_listings.json` |
| `--reference-file` | Optional CSV of known models to compare asking prices against (see [referentiedata.md](referentiedata.md)) | `reference_prices.csv` |
| `--open-browser` | `auto` (open only when there are new listings), `always`, or `never` | `auto` |
| `--log-file` | CSV that newly found bargains get appended to (a running history) | `bargains_log.csv` |
| `--no-log` | Skip appending to the bargains log | off |
| `--price-history-file` | CSV that logs observed prices of reference-matched listings (builds your own market price database) | `reference_price_history.csv` |
| `--no-price-history` | Skip recording/using observed secondhand prices | off |
| `--no-notify-better` | Skip the sound/notification when a listing beats the reference baseline | off |
| `--bid-lookup` | Which bidding listings to fetch bid details for: `fast` (FAST_BID only), `all` (also MIN_BID), `none` | `fast` |
| `--no-bid-lookup` | Alias for `--bid-lookup none` | off |
| `--detail-lookup` | `budget`: fetch the listing page (full description, "Kenmerken") for complete road bikes within your size and budget — at most 10 per run, each listing once, only with `--db`. `none` skips it | `budget` |
| `--bids-only` | Only report bidding listings | off |
| `--min-score` | Only report listings with at least this dealscore (0-100) | none |
| `--db` | Path to the SQLite database that mirrors the CSV/JSON files (see [database.md](database.md)) | `koopjes.db` |
| `--no-db` | Skip writing to the SQLite database | off |
| `--summary-file` | Append one JSON line per report (counts, report path, most interesting new listings) — what `koopjes.py`'s overview page reads | none |
| `--mijn-fiets` | Intake of your own bike, for the report's `Mijn fiets` and `Upgrade` tabs (see [rapport.md](rapport.md)) | `mijn_fiets.md` |
| `--watchlist` | Run saved searches by name (comma-separated, or `all` for every active one), each with its own filters and report (see below) | none |
| `--watchlist-add NAME` | Save `--query` plus the filter flags on this command line as watchlist `NAME` (replaces an existing one); doesn't crawl | none |
| `--watchlist-remove NAME` | Delete a watchlist; doesn't crawl | none |
| `--watchlist-list` | List the saved watchlists; doesn't crawl | off |

Example — bikes up to €150 with a frame size between 54 and 60 cm:

```bash
python racefiets_jev.py --pages 0 --max-price 150 --min-frame-height 54 --max-frame-height 60
```

## First run: fetch everything

Use `--pages 0` once to seed `seen_listings.json` with every listing
Marktplaats currently has, so your first scheduled run doesn't mark all of
them as "new" at once. A full crawl takes a few minutes (Marktplaats caps
pagination at a few hundred pages regardless of how many results a query
technically matches, so "everything" means everything it lets you browse
to — typically its few thousand most relevant/recent listings, not literally
every listing that ever matched). After that, run it with a small `--pages`
on your recurring schedule — new listings are what you're after, and they'll
show up on the first page(s) already.

## Frame size filtering

Marktplaats doesn't expose an exact frame size — sellers pick from fixed
buckets ("53 tot 57 cm", "57 tot 61 cm", etc.). `--min-frame-height`/
`--max-frame-height` include any bucket that overlaps your requested range,
so a bike in a bucket that only partially overlaps (e.g. bucket "53 tot 57
cm" for a `--min-frame-height 54` filter) may still show up.

A bike with no frame size listed at all is **kept** — that's most of them: on
a 40-page crawl of "racefiets" (September 2026), 76% of the bikes had no size
filled in, often because the seller wrote "maat 56" in the text instead.
Dropping those hid three out of four bikes. Add `--strict-frame-height` to
drop them anyway (the behavior before this change).

## Sort order — `--sort newest`

Marktplaats' default order ("Standaard", `--sort optimized`) is not by date.
On a 40-page crawl of "racefiets", today's listings were spread over all 40
pages — 83 of 314 on the first three — and the 1200 result slots held only
951 distinct listings: the default order serves some listings on several
pages and skips others. `--sort newest` fetches newest first through
Marktplaats' search API (the one the site's own "Sorteer op" menu uses), so
a scheduled run of a few pages sees everything that's new since the last
one. The default stays `optimized` so an existing setup keeps behaving as
it did.

## Categories — `--category`

Marktplaats flags the category a query is really about (see "Off-topic
results" below), and the script keeps only that one. Some queries have two:
"powermeter" is dominant in both *fietsonderdelen* (loose powermeters) and
*fietsen-racefietsen* (bikes with one fitted), and only the bikes were kept.
The script now says so when it happens. `--category fietsonderdelen` picks
the category (or categories) yourself, and Marktplaats filters server-side,
so no pages are spent on the rest. Use the category's key from the URL on
marktplaats.nl or its number; an unknown one lists the categories that do
have results for the query. With several categories, one that has no results
for the query today is skipped with a warning ("let op: categorie ... heeft
nu geen resultaten"), so a quiet day in one category doesn't cost the whole
search; only when none of them has results is it an error. Several categories must share a main category
(e.g. `fietsonderdelen,fietsen-racefietsen`, both under *fietsen-en-brommers*).
Common ones for bikes: `fietsen-racefietsen`, `fietsonderdelen`,
`fietsaccessoires-fietscomputers`.

`--category alle` is the other way round: every category, with no filter
and no dominant-category guess — everything Marktplaats finds for the query,
the same as searching on the site without a category. For a query that is
its own filter. "giant defy" is dominant in racefietsen, but on 29-09-2026
23 of its 165 results were Defys a seller had put under
*heren-sportfietsen-en-toerfietsen*, *dames-omafietsen* and the like, and the
guess dropped every one of them. The price: loose parts and the odd fuzzy
match come along too (in that search's own report). `alle` can't be combined
with other categories.

## Everything in a category — `--split`

Marktplaats pages through ~5000 results per search and no further, also
with 100 per page; the category racefietsen has ~13-14k. With `--split`
(`"split": true` in `schedule.json`) a complete crawl (`--pages 0`) with a
`--category` that has more than that runs in parts instead: per condition
(Nieuw, Zo goed als nieuw, Gebruikt — a condition with more than ~4800 also
oldest first) and per price band (€0-150, 150-300, ... for the listings
without a condition), each filtered by Marktplaats itself (checked
30-09-2026). Listings without an amount ("bieden") can't be asked for by
price, and sorting by price leaves them out, which is why the condition goes
first. It is only complete if the parts together saw every listing
Marktplaats counts; otherwise nothing is swept as gone. It runs slower than a
normal crawl on purpose: on 30-09-2026 Marktplaats answered 403 after ~120
quick requests of 100 listings, and was fine again a few minutes later. So:
at least 4 s between requests, a minute's pause every 40, and after a 403 it
waits 5 minutes and tries once more before stopping with what it has.

## Off-topic results on deep pages

Past a certain page depth (roughly page 50+ for "racefiets"), Marktplaats'
own search loosens from real matches to fuzzy word matches — e.g. old
PS2/Game Boy racing games showing up because their titles contain "racer".
The script detects Marktplaats' own "dominant category" for the query (the
category it considers the query to really be about) and drops listings
outside it, which removes this. It prints how many it dropped. This doesn't
catch the rare listing a seller mis-categorized themselves (e.g. cycling
shoes listed under "Racefietsen") — use `--exclude` for those if it becomes
annoying (not yet implemented — ask if you want it). When Marktplaats flags
more than one category as dominant, the script keeps the biggest and names
the others in its output; `--category` (above) chooses instead, and
`--category alle` switches this filter off.

"Wanted" ads — someone looking to buy, posted in the same category — are
skipped too, and counted in the output. Nothing in the listing data marks
them, so this goes by the title: "gezocht" at the start, at the end, or in
brackets ("Gezocht: racefiets", "Garmin Edge 530 gezocht", "(Gezocht)"), but
not "veel gezocht model".

## Watchlists — `--watchlist`

A watchlist is a named search with its own filters, stored in `koopjes.db`
(table `watchlist`) — for hunting a loose part such as a powermeter or a newer
bike computer next to the bike search, without the two getting in each
other's way. Save one once:

```bash
python racefiets_jev.py --watchlist-add powermeter --query powermeter \
    --min-price 100 --max-price 500 --reference-file reference_bike_accessories.csv
python racefiets_jev.py --watchlist-list
```

`--watchlist-add` stores `--query` plus whichever of these differ from their
default: `--min-price`, `--max-price`, `--min-frame-height`,
`--max-frame-height`, `--strict-frame-height`, `--bargain-ratio`,
`--reference-file`, `--category`, `--bids-only` and `--min-score`. A reference file that doesn't
exist gets a warning, when saving and when running — a relative path is
looked up from the directory the script is started in.
Saving under an existing name replaces it; `all` and names with a comma are
reserved. Then run it, alone or next to a regular query:

```bash
python racefiets_jev.py --watchlist powermeter
python racefiets_jev.py --query racefiets --max-frame-height 58 --watchlist powermeter
python racefiets_jev.py --watchlist all      # every active watchlist
```

The two sides don't share filters. A watchlist starts from the defaults and
applies only its own — in the second example `--max-frame-height 58` applies
to `racefiets` only (it would otherwise drop every powermeter, which has no
frame size), and the watchlist's price range doesn't touch the bike query
either. Everything that is about *how* the run is done rather than *what*
it looks for — `--pages`, `--sort`, `--bid-lookup`, `--delay`, `--db`, the
history/log/price-history files, `--open-browser` — comes from the command
line, so a scheduled shallow run stays shallow and makes no more requests
than you asked for. Each watchlist gets its own report, named after it
(`racefiets_report_powermeter.html`, and `<output>_powermeter.csv` with
`--output`); a watchlist whose query is comma-separated gets one per term.
Without `--query`, only the watchlists run; an unknown name stops the run
before anything is fetched.

A watchlist's `--reference-file` is also what gets imported into `model` and
matched into `listing_model` for its listings, so running the accessories
with `reference_bike_accessories.csv` is how those end up linked in the
database.

## Bidding listings (FAST_BID / MIN_BID)

Some listings ("Bieden") don't have a fixed price. Marktplaats' search
results always report €0 for these (`FAST_BID`), even though the listing
itself has a real minimum bid, or a real current highest bid once someone has
bid. By default the script fetches each `FAST_BID` listing's own page to get
that real number (marked `B` in the table, "bod" in the HTML report) and uses
it everywhere — price filters, the bargain comparison, the dealscore, all of
it — instead of treating it as priceless. `MIN_BID` listings already report a
number in search results, so no extra request is needed for those, but they're
marked `B` too since it's still a bid, not a fixed asking price.

This means one extra request per `FAST_BID` listing found, so a run with a lot
of them takes longer. `--bid-lookup none` (or `--no-bid-lookup`) skips it and
goes back to treating those listings as priceless.

Your filters run before the lookup, so a listing that `--min-price`,
`--max-price` or the frame-size filters already exclude never costs a request.
A `FAST_BID` has no price to filter on at that point, so those are looked up
first and then held against the price range like everything else.

**What a `MIN_BID` price actually is.** The number in the search results is
what the seller is asking; the minimum bid Marktplaats will really accept is
on the listing page and is often well below it — a listing asking €200 took
bids from €120, one asking €47.50 from €35. `--bid-lookup all` fetches those
pages too (one extra request per `MIN_BID` listing) and fills in both the real
minimum bid and how many bids have been placed. The asking price stays the
price used for filters and the score, because that's what compares fairly
against fixed-price listings — the minimum bid is shown separately, in its own
`Bod` column, as what it would cost to open the bidding. Unless someone has
already bid more than the asking price: then that bid is the price, since
below it the listing can't be had.

**Still free to bid on.** Bidding listings nobody has bid on yet get a
`VRIJ TE BIEDEN` badge and their own filter tab in the HTML report. Every run
also prints a `BIED-OVERZICHT` section: all bidding listings, sorted by
headroom (`RUIMTE` — see below), showing the minimum bid, what percentage of
the median that minimum is, and the reference model if one matched. That
percentage is only shown while nobody has bid yet: once there is a bid, the
minimum no longer buys the listing, so it stays visible as a plain number
without being presented as a cheap way in.

**`RUIMTE` — how much room is in a bid.** Estimated value minus what it costs
to get in: the minimum bid while nobody has bid, the standing bid once someone
has, and the asking price when the bid was never looked up. That last case is
deliberately *not* treated as €0 or as the minimum bid — an unfetched bid is
unknown, not free, and the column prints a dash rather than a number when
there is nothing to go on. The estimated value comes from the best benchmark
available for that listing, in this order:

1. the secondhand average observed for its reference model, if there are at
   least two sightings;
2. the median asking price of **comparable bikes** in the same set of
   listings — same frame material and same groupset tier, narrowed to the
   same brake type (rim or disc, the nearest thing to an age a listing
   usually gives) when that is known and has enough bikes. At least 5, the
   listing itself not counted, bids that are already running left out;
3. the median of the whole search — marked **rough** (`grof`). Nothing about
   the bike itself stands behind it: it's what a saddle or a pair of shoes
   listed in the racefietsen category gets. The console prints no `RUIMTE`
   figure for these, and in the report they sit below every real estimate.

All three are asking prices, corrected to a realistic selling price with the
same factor `valuation.py` uses. Even the comparable-bikes median still
mixes model years (a 2009 and a 2024 Ultegra bike can share a segment when
neither says its brake type), so read a large headroom on an old bike as a
reason to look, not as a profit. Listings whose headroom is unknown (or
rough) keep the old ordering (the ones nobody has bid on first, each group
by dealscore) and sit below the ones that have a number.

A listing only counts as "still free to bid on" when its bid count was
actually looked up and came back zero — a `MIN_BID` listing without
`--bid-lookup all` has an unknown bid count, which is not the same as zero,
and stays out of that tab. So for a full picture of what's biddable:

```bash
python racefiets_jev.py --query luidsprekers --pages 5 --bid-lookup all --bids-only
```

`--bids-only` limits the report to bidding listings. The `% v. mediaan`
column and the median printed in the footer under the table (and its HTML
equivalent) are both still measured against everything found first, not
just what's left after `--bids-only`/`--min-score` filter the rows shown —
so the comparison stays against the whole market rather than only against
other bidding listings, and the column and the footer never disagree about
which median they mean.

Keep in mind that a bid listing's price is where the bidding stands now, not
what it will sell for, so its dealscore is an upper bound — the score
breakdown says as much on those listings.

## Groupset detection (bikes)

The console table and HTML report show a recognized groupset (Shimano
Claris/Sora/Tiagra/105/Ultegra/Dura-Ace, SRAM Apex/Rival/Force/Red,
Campagnolo Veloce/Centaur/Chorus/Record/Super Record, plus an
"(elektronisch)" tag for Di2/eTap/AXS) when one is mentioned in the title or
description. This is keyword matching on free text, not a structured
Marktplaats field, so it can miss a groupset that's phrased unusually or
only visible in a photo, and SRAM/Campagnolo tier names (e.g. "Force",
"Record") only count when the brand name also appears somewhere in the text,
to avoid matching on the plain Dutch/English word — or, for SRAM, when eTap
or AXS sits in the same phrase ("Force AXS", "Red eTap"), which is how most
sellers write it.

The "(elektronisch)" tag needs the marker to belong to the groupset itself:
Di2 only counts for a Shimano groupset and eTap/AXS only for a SRAM one, and
the word has to sit in the same phrase as the groupset name ("Shimano Ultegra
R8050 Di2"). A mention further along in the text is usually about something
the bike hasn't got — "Shimano 105, Di2-upgrade mogelijk" is a mechanical 105
— so that one stays untagged, at the price of missing an ad that only names
its groupset and its Di2 in separate sentences.

## Notes

This scrapes Marktplaats' public search result pages directly (no API key
or third-party service required). Marktplaats may change its page
structure at any time, which can break parsing — the script prints a
clear error if that happens rather than failing silently.
