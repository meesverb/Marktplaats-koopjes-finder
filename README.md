# Marktplaats koopjes finder

`racefiets_jev.py` searches [Marktplaats](https://www.marktplaats.nl) for
listings matching a query — road bikes ("racefiets") by default, but `--query`
works for anything (`--query luidsprekers`, `--query "canon eos"`, ...) — and
flags ones priced well below the median of what it found as a quick way to
spot bargains. Every listing also gets a single 0-100 **dealscore** combining
all the price signals it knows about, and the report is sorted by it, so the
best deal is the top row (see "Dealscore" below). The frame-height/groupset
features below are bike-specific and simply find nothing to match on other
queries, which is harmless.

Pick a query term that's actually specific to what you want: Marktplaats'
own category data is used to filter out unrelated results (see "Off-topic
results" below), but that only works if your query has one clear dominant
category to begin with. E.g. `luidsprekers` (speakers) works well; `boxen`
doesn't — on Marktplaats that word matches baby playpens far more often
than speakers.

## Automatic rounds — `koopjes.py` and `schedule.json`

The easiest way to run all of this is not to type commands at all.
`schedule.json` describes every search (a query plus its filters) and the
time slots they run in; `koopjes.py` runs one slot:

```bash
python koopjes.py status            # check schedule.json, see when each search last ran
python koopjes.py run overdag       # one round, exactly as the scheduler will start it
python koopjes.py schedule          # Task Scheduler (Windows) / cron lines, paths filled in
python koopjes.py lists             # lijsten/beste_koopjes.txt and lijsten/zonder_referentie.txt
```

Paste what `schedule` prints into a command prompt (Windows) or `crontab -e`
(macOS/Linux) once, and the rounds run by themselves. What a round does:

1. takes a lock — a round that starts while another is still running is
   skipped, so Marktplaats never gets two crawls at once;
2. writes the searches into the watchlist table (see "Watchlists" below), so
   `schedule.json` stays the one place to change them;
3. runs `racefiets_jev.py` once for all the slot's searches, with the slot's
   `pages`, `sort` and `bid_lookup`;
4. with `"valuation": true`, runs `valuation.py`, so the valuation history
   builds up by itself;
5. rebuilds **`overzicht.html`**: per search the latest run, how many listings
   are new / better than your reference / top deals / cheaper than before, the
   new listings most worth a look, a link to each full report, the latest
   valuation of your own bike, and the schedule.

After every round two plain-text lists are rewritten in `lijsten/`, written
to be pasted into a conversation: `beste_koopjes.txt` (per search the upgrade
candidates and the highest deal scores, each with its URL and the reasons
behind the score; running bids left out, since their price is only the bid so
far) and `zonder_referentie.txt` (complete road bikes from the last 14 days
that no row in `reference_bikes.csv` recognises, grouped by brand and first
model word, most frequent first — the gaps in the reference file).

Everything a round prints goes to `logs/koopjes.log`. Relative paths in
`schedule.json` are relative to that file, so it doesn't matter which
directory the scheduler starts the round in.

The shipped `schedule.json` follows a measurement of Marktplaats itself
(September 2026, category racefietsen): 400-500 new listings a day, spread
fairly evenly over 09:00-22:00 at 25-30 an hour, few at night. So:

| Slot | When | What |
| --- | --- | --- |
| `overdag` | 08:30, 13:30, 19:30 | racefietsen around size 56, newest first, 8 pages — 150-180 arrive between two runs, 8 pages leaves room |
| `nacht` | 03:00 | complete crawls of "giant defy" and "ultegra 6700" (comps for your own bike, and complete, so sold listings are counted), the powermeter and bike computer searches, then `valuation.py` |
| `week` | Sunday 05:00 | all racefietsen Marktplaats will show (~5000, about 10 days' worth), without bid lookups |

Change the searches' filters (a `max_price` for your budget, say) and the
times in `schedule.json`; `python koopjes.py status` tells you straight away
if something in it is wrong. Searches accept the same filters as a watchlist;
slots take `searches`, `pages` (0 = everything), `sort`, `bid_lookup`,
`times` (`"HH:MM"` or `"zo HH:MM"`, Dutch day abbreviations), `valuation` and
`open_browser`.

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

### Options

| Flag | Description | Default |
| --- | --- | --- |
| `--query` | Search query | `racefiets` |
| `--pages` | Number of result pages to fetch (30 listings/page). `0` = fetch everything Marktplaats allows browsing to (see note below) | `1` |
| `--min-price` / `--max-price` | Filter by price in EUR | none |
| `--min-frame-height` / `--max-frame-height` | Filter by frame size in cm; bikes without a stated size are kept (see below) | none |
| `--strict-frame-height` | With the frame size filter, also drop bikes that don't state a size | off |
| `--sort` | `optimized` (Marktplaats' own "Standaard" order) or `newest` (newest first — use this for scheduled runs, see below) | `optimized` |
| `--category` | Only search these Marktplaats categories (comma-separated key or number, e.g. `fietsonderdelen`), filtered by Marktplaats itself (see below) | none |
| `--bargain-ratio` | Fraction of the median price at/below which a listing is flagged | `0.6` |
| `--delay` | Seconds between page requests | `1.5` |
| `--output` | Write results to a CSV file | none |
| `--html` | Path to write the HTML overview to | `racefiets_report.html` |
| `--no-html` | Skip writing the HTML overview | off |
| `--history-file` | Path to the file that remembers which listings were already seen | `seen_listings.json` |
| `--reference-file` | Optional CSV of known models to compare asking prices against (see below) | `reference_prices.csv` |
| `--open-browser` | `auto` (open only when there are new listings), `always`, or `never` | `auto` |
| `--log-file` | CSV that newly found bargains get appended to (a running history) | `bargains_log.csv` |
| `--no-log` | Skip appending to the bargains log | off |
| `--price-history-file` | CSV that logs observed prices of reference-matched listings (builds your own market price database) | `reference_price_history.csv` |
| `--no-price-history` | Skip recording/using observed secondhand prices | off |
| `--no-notify-better` | Skip the sound/notification when a listing beats the reference baseline | off |
| `--bid-lookup` | Which bidding listings to fetch bid details for: `fast` (FAST_BID only), `all` (also MIN_BID), `none` | `fast` |
| `--no-bid-lookup` | Alias for `--bid-lookup none` | off |
| `--bids-only` | Only report bidding listings | off |
| `--min-score` | Only report listings with at least this dealscore (0-100) | none |
| `--db` | Path to the SQLite database that mirrors the CSV/JSON files (see below) | `koopjes.db` |
| `--no-db` | Skip writing to the SQLite database | off |
| `--summary-file` | Append one JSON line per report (counts, report path, most interesting new listings) — what `koopjes.py`'s overview page reads | none |
| `--mijn-fiets` | Intake of your own bike, for the report's `Mijn fiets` and `Upgrade` tabs (see below) | `mijn_fiets.md` |
| `--watchlist` | Run saved searches by name (comma-separated, or `all` for every active one), each with its own filters and report (see below) | none |
| `--watchlist-add NAME` | Save `--query` plus the filter flags on this command line as watchlist `NAME` (replaces an existing one); doesn't crawl | none |
| `--watchlist-remove NAME` | Delete a watchlist; doesn't crawl | none |
| `--watchlist-list` | List the saved watchlists; doesn't crawl | off |

Example — bikes up to €150 with a frame size between 54 and 60 cm:

```bash
python racefiets_jev.py --pages 0 --max-price 150 --min-frame-height 54 --max-frame-height 60
```

### First run: fetch everything

Use `--pages 0` once to seed `seen_listings.json` with every listing
Marktplaats currently has, so your first scheduled run doesn't mark all of
them as "new" at once. A full crawl takes a few minutes (Marktplaats caps
pagination at a few hundred pages regardless of how many results a query
technically matches, so "everything" means everything it lets you browse
to — typically its few thousand most relevant/recent listings, not literally
every listing that ever matched). After that, run it with a small `--pages`
on your recurring schedule — new listings are what you're after, and they'll
show up on the first page(s) already.

### Frame size filtering

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

### Sort order — `--sort newest`

Marktplaats' default order ("Standaard", `--sort optimized`) is not by date.
On a 40-page crawl of "racefiets", today's listings were spread over all 40
pages — 83 of 314 on the first three — and the 1200 result slots held only
951 distinct listings: the default order serves some listings on several
pages and skips others. `--sort newest` fetches newest first through
Marktplaats' search API (the one the site's own "Sorteer op" menu uses), so
a scheduled run of a few pages sees everything that's new since the last
one. The default stays `optimized` so an existing setup keeps behaving as
it did.

### Categories — `--category`

Marktplaats flags the category a query is really about (see "Off-topic
results" below), and the script keeps only that one. Some queries have two:
"powermeter" is dominant in both *fietsonderdelen* (loose powermeters) and
*fietsen-racefietsen* (bikes with one fitted), and only the bikes were kept.
The script now says so when it happens. `--category fietsonderdelen` picks
the category (or categories) yourself, and Marktplaats filters server-side,
so no pages are spent on the rest. Use the category's key from the URL on
marktplaats.nl or its number; an unknown one lists the categories that do
have results for the query. Several categories must share a main category
(e.g. `fietsonderdelen,fietsen-racefietsen`, both under *fietsen-en-brommers*).
Common ones for bikes: `fietsen-racefietsen`, `fietsonderdelen`,
`fietsaccessoires-fietscomputers`.

### Dealscore

Each listing gets one 0-100 score that folds together every price signal the
script has for it, so you don't have to weigh the individual columns yourself.
The console table and the HTML report are both sorted by it (best first), the
HTML report has a sortable `Score` column with a label (Topdeal / Goede deal /
Redelijk / Aan de prijs / Duur) and a `Topdeals` filter tab, and hovering a
score shows exactly which signals produced it. `--min-score 70` drops
everything below that score from the report.

Three price signals feed in, each comparing the asking price to a benchmark.
Each is scaled so that sitting exactly on its benchmark scores 50:

| Signal | Benchmark | Weight |
| --- | --- | --- |
| % of median | the median price of everything found for this query | 1 |
| % of secondhand average | what this exact model went for in your own past runs (needs 2+ sightings) | 2 |
| % of original price | what the model cost new, from `reference_prices.csv` | 0.75 |

The secondhand average weighs heaviest because it's the most honest benchmark:
it's what this specific model actually gets asked for, observed first-hand.
The original retail price weighs least — for anything vintage, every listing
sits far below it, so it barely separates a good deal from a bad one.

Only signals that are actually available count, and the weights are
renormalized over those, so a listing with no reference data is scored on what
is known rather than penalized for the empty columns. That does mean a score
can rest on a single signal, which is why every score comes with the list of
signals behind it. On top of the average come two bonuses: up to +10 for a
price drop (scaled to how big it was) and +8 for a `better_than_baseline`
reference match.

A few things the score deliberately does not do. It says nothing about
condition, completeness or how far away the seller is — it's a price signal,
not a verdict. Anything at or above 1.7x the median scores 0, so it doesn't
rank "expensive" against "absurd". And a bidding listing's price is wherever
the bidding stands now, not what it will sell for, so its score is an upper
bound — the score breakdown says so on those listings.

### Bidding listings (FAST_BID / MIN_BID)

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
`Bod` column, as what it would cost to open the bidding.

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
available for that listing: the secondhand average observed for its reference
model if there are at least two sightings, otherwise the median of this
search, in both cases corrected from an asking price to a realistic selling
price with the same factor `valuation.py` uses. Without reference models
matched, every listing in a search shares the same benchmark, so the column
then effectively ranks by entry price — it gets sharper the more of
`reference_prices.csv` applies to what you are searching for. Listings whose
headroom is unknown keep the old ordering (the ones nobody has bid on first,
each group by dealscore) and sit below the ones that have a number.

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

### Groupset detection (bikes)

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

### Comparing against original prices — `--reference-file`

There's no free database of "every model with its original price and a
score" to plug in, for bikes or anything else. Instead, `--reference-file`
lets you maintain your own — a plain CSV that grows as you go, at zero cost
and no API key:

```csv
pattern,label,original_price_eur,specs,score,better_than_baseline
Canyon Ultimate CF SLX 8,Canyon Ultimate CF SLX 8 (2021),4000,"11.7 kg, Ultegra Di2",8.5/10,1
```

- `pattern`: regex (case-insensitive), matched against the listing title and
  description combined. Put more specific patterns earlier in the file — the
  first match wins.
- `label`: what to display when matched.
- `original_price_eur`: what it cost new (optional — leave blank if unknown).
- `specs`: the objective specs worth comparing (power, sensitivity, weight,
  whatever matters for that category) — optional, free text.
- `score`: any rating/ranking text you want shown (optional, free text).
- `better_than_baseline`: `1` if this model is better than whatever you're
  comparing against (e.g. your own gear's reference row) — used for the
  HTML report's "Beter dan referentie" filter tab. Leave `0`/blank otherwise.

When a listing matches, the report shows the label, the original price and
what percentage of it is being asked now, the specs, and the score — in
their own columns in the HTML report (Referentie / Nieuwprijs / Specs), plus
a purple "BETER" badge when `better_than_baseline` is set. See
`reference_prices.example.csv` for the exact format — copy it to
`reference_prices.csv` and fill in models you actually care about (the
values in the example file are placeholders, not real prices). If you want
help researching a specific model's original price, just ask — that's more
reliable done one model at a time than guessed in bulk.

**Bikes have their own reference files.** `reference_prices.csv` is the
speakers; a bike pattern in there would be matched against speaker titles.
For bike searches, point `--reference-file` at one of these instead:

```bash
python racefiets_jev.py --query "giant defy" --reference-file reference_bikes.csv
python racefiets_jev.py --query "garmin edge" --reference-file reference_bike_accessories.csv
```

- `reference_bikes.csv` — the Giant Defy family (the owner's own bike is the
  row marked "Baseline") plus common upgrade targets (Canyon Endurace,
  Specialized Roubaix, Trek Domane).
- `reference_bike_accessories.csv` — bike computers (Wahoo, Garmin) and
  power meters. These are deliberately **not** in the bike file: the first
  matching row supplies the original price the dealscore compares against,
  so a "Garmin Edge 530" row there would make a €900 bike that mentions its
  computer look like 300% of a €299.99 original price.

Both files add three optional columns after the usual six: `kind` (`bike`,
`computer`, `powermeter`, ...), `brand` and `source_url`. The script ignores
them; the SQLite import (`--db`) stores them in the `model` table. Every row
has a source, and `original_price_eur` is only filled in where a source
gives a euro price — a model year or trim whose price couldn't be found is
left blank rather than converted from dollars or guessed.

`reference_bikes.csv` has one more column, `frame_material` (`carbon`,
`aluminium`, `staal`, `titanium` or empty), filled in only where the row's own
sourced specs name the material. The valuation uses it: a listing matched to
the aluminium "Giant Defy 0-5" row is no comp for a carbon Defy Composite,
even when its text never says "alu".

### Bike catalogue — `reference_bike_catalog.csv`

A third bike file, and a different kind: not regex patterns to match titles
against, but one row per brand / model / model year with the specs and the
original price. The pattern files can't hold this — every "Defy Advanced 2"
from 2016 to 2025 would share one pattern, and with first-match-wins only
the first of those rows would ever be used. Nothing reads the catalogue
automatically yet; it's reference data for the valuation (what did this
bike cost new, in which year) and for looking things up by hand.

Columns: `brand`, `model`, `model_year`, `seen_date`, `category`,
`frame_material`, `groupset`, `electronic`, `speeds`, `brake_type`,
`weight_kg`, `new_price`, `currency`, `market`, `price_basis`, `specs` (the
full spec list as the source gives it), `source_url`, `spec_source_url`.

Where it comes from, per brand:

| Brand | Specs and model year | Price |
| --- | --- | --- |
| Giant | giant-bicycles.com/nl — archived model pages (Wayback Machine) and Giant's own "Oudere modellen" archive | the NL price on the archived page, the earliest capture of that model year |
| Trek | trekbikes.com/nl — Trek's bike archive (2011-2026) | NL price from archived overview/product pages; today's price for bikes still on sale |
| Sensa | sensabikes.com — archived model pages | the price on the page. **No model year**: the pages don't state one, so `model_year` stays empty and `seen_date` holds the capture date |
| Cube (today's line-up) | cube.eu/nl-nl — no model year on the page, so `seen_date` | the NL price shown today |
| Cube (to 2024) and 26 other brands | bikezona.com catalogue: Specialized, Cannondale, Scott, Canyon, BMC, Bianchi, Merida, Orbea, Ridley, Cervélo, Pinarello, Focus, Lapierre, Rose, Stevens, KTM, Felt, Wilier, Colnago, De Rosa, Kuota, Time, BH, Fuji, GT, Btwin | bikezona's price, `market` = `ES` |

Things to keep in mind when using it:

- **`market` matters.** `NL` is the brand's own Dutch price; `ES` is the
  Spanish catalogue price from bikezona.com — a real euro list price, but not
  the Dutch one. An ES row only appears where the brand's own Dutch page gave
  no price for that model year.
- **A price is what the source showed, on the date in `price_basis`.** For an
  archived page that is usually the launch price; a capture late in the
  season can already show a reduction. For bikes on sale today, Giant's
  webshop discount is not counted (the "Reguliere prijs" is used), Trek's
  `wasPrice` likewise.
- **Derived columns are read from the row's own spec text** and left empty
  when that text doesn't say — `brake_type` in particular is often empty for
  older bikes whose spec list names the brake model without saying
  "rim" or "disc". "Disc" in the model name counts.
- Framesets, e-bikes, flat-bar fitness bikes and kids' bikes are left out.

Rebuilding it is slow (hours: every request is spaced out, and the Wayback
Machine is often slow or briefly offline). The tools are in `catalog_tools/`;
run them from an empty scratch directory, because they write a page cache and
intermediate JSON to the working directory:

```bash
mkdir /tmp/catalog && cd /tmp/catalog
sh /path/to/repo/catalog_tools/run_all.sh
```

`tests/test_bike_catalog.py` checks every row has a source, every price a
market and a basis, and that no model year appears that the source didn't
state.

### Your own market price history — `--price-history-file`

Every time a listing matching a reference model is seen for the first time,
its price gets logged to `reference_price_history.csv` (created
automatically). From the second time a model shows up, the report also
displays "2e-hands gem. €X (n=Y)" — the actual average secondhand asking
price you've personally observed for that model, based on Y past sightings.
This needs no research or original price at all, grows automatically the
more you run the script, and is arguably more useful than a decades-old
retail price for judging whether an asking price is reasonable. Disable
with `--no-price-history`.

### SQLite mirror — `--db`

Every run also mirrors its listings into a local SQLite database
(`koopjes.db` by default, created automatically), on top of — not instead
of — the CSV/JSON files above: every field the script parses (price, city,
condition, frame size, bid status, ...) gets upserted per listing, a
`crawl_run` row logs the query and page count, and `seen_listings.json` /
`reference_prices.csv` / `reference_price_history.csv` get re-imported into
the same database so it stays in sync with them. Only a full crawl
(`--pages 0`) marks previously-seen listings for that query as disappeared
if they no longer turn up — a shallow `--pages 3` run only looked at part of
the market, so it never draws that conclusion. Neither does a `--pages 0`
crawl that didn't see every result: Marktplaats stops paging after about
5000 listings (167 pages; "racefiets" has 26000+ results), a page can fail
to load, and the default sort order repeats listings across pages. The sweep
only runs when the number of distinct listings seen matches the total
Marktplaats reports, and says why it skipped otherwise — use a narrower query
(e.g. "giant defy"), `--category`, and `--sort newest` for the full crawl
whose disappearances you want to count. The database remembers every query that
found a listing (table `listing_query`), so a Defy last seen by the daytime
"racefiets" run still counts for the nightly "giant defy" sweep. `valuation.py` reads from this
database (see below); disable writing to it entirely with `--no-db`.

### Watchlists — `--watchlist`

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

### `valuation.py` — what is my own bike worth?

The first thing that reads `koopjes.db` rather than writing to it. It values
the bike described in `mijn_fiets.md` against the listings the crawler has
collected, and writes the result to the `valuation` / `valuation_evidence`
tables (PLAN_FIETSWAARDE.md fase 3).

```bash
python racefiets_jev.py --query "giant defy" --pages 0 --sort newest --reference-file reference_bikes.csv   # collect comps first
python valuation.py --db koopjes.db
```

Three estimators, mixed into one band:

- **E1 — comparable listings.** A ladder with decreasing confidence: same
  model + model year ±2 + same groupset tier (high), same model family +
  year ±3 (medium), same segment — frame material, brake type, gearing,
  year range (low). The highest rung with at least 5 comps wins; below that
  the estimate is marked `indicatief` and says so in its own evidence line.
  On every rung a comp must be a complete road bike (a listing in the
  racefietsen category — a frame or crankset from a parts watchlist is not)
  and must not have a different frame material (from the text, or from the
  reference model it matched).
- **E2 — asking price → selling price.** Marktplaats publishes asking
  prices, not selling prices. Once at least 20 listings have disappeared
  within two weeks and 20 others have been sitting online for 60+ days —
  disappeared *or* still online, both count, "sitting online" is measured
  from when we first saw the listing, not its Marktplaats posting date —
  the ratio between those two medians becomes a measured correction factor
  per category; until then a heuristic 10-15% is applied and labelled as
  such. Disappeared is not the same as sold — that caveat is in the output.
- **E3 — sum of the parts.** Component prices from `component_price` times a
  bundle factor. With that table empty it contributes nothing, and every
  component without observations gets an evidence line saying so.

Every number shown is traceable to an evidence line, including a clickable
link per comp. Options: `--scenario a|b` (complete with the carbon wheelset,
or with the stock wheels and the wheelset sold separately — repeatable,
default both), `--query` to restrict the comps to one crawl query,
`--window-days` for how far back comps count (default 180), `--dry-run` to
print without writing to the database.

What it does **not** do: invent numbers. No comparable listings means no
valuation, not a guess — crawl the model first. The 10-15% negotiation
margin, the bundle factor and the share of an upgrade that a buyer of a
complete bike pays for are heuristics, not measurements, and each is printed
as its own line so it is clear what it contributed.

### `scoring.py` — how good is a bike, regardless of price?

The **quality score** from PLAN_FIETSWAARDE.md fase 4, and not to be confused
with the dealscore above: that one says whether a price is good, this one says
whether a *bike* is good. Five dimensions — frame, drivetrain, brakes, wheels,
extras — each 0-100 with the signals that went into it spelled out, weighted
into one total. The weights and score tables live in `scoring_config.json`, so
changing what you care about is an edit to that file rather than to the code.

```bash
python scoring.py                 # the baseline: your own bike from mijn_fiets.md
```

The same function scores a listing and your own bike, which is what makes
"better than mine" a comparison rather than an opinion. Missing information
scores neutrally and says so, instead of being guessed at.

A listing only offers its title and the first ~200 characters of the
description, so a few shorthand forms are read as well: "Disc" in a model
name ("Emonda SL5 Disc") counts as a disc brake (but "disc wiel" is a closed
wheel, not a brake), and a wheel brand named without a material ("Roval
Rapide CLX", "Newmen wielen") scores `wheels.merk_materiaal_onbekend` — above
unknown, below branded carbon, since the same brand also makes aluminium
wheels. A brand name followed by cockpit/stuur/zadel/vork doesn't count.

### `upgrade.py` — which better bike can I buy for that?

The other half of the question `valuation.py` answers: it takes the valuation
as the budget, the quality score from `scoring.py` as the baseline, and ranks
the listings in `koopjes.db` on how much bike each one adds per euro
(PLAN_FIETSWAARDE.md fase 5).

```bash
python racefiets_jev.py --query "racefiets" --pages 0   # collect candidates first
python upgrade.py --db koopjes.db
```

A listing is a candidate when all four hold: it is a complete road bike
(listed in the racefietsen category — parts from a powermeter watchlist are
not candidates), it fits the frame size, it scores more than the baseline
plus a margin, and its effective price is within budget.

Without enough comps there is no valuation and so no budget. For that case,
`mijn_fiets.md` has a `verkoopprijs_handmatig` line in its scoring block: put
your own expected sale price there and the upgrade finder (and the report's
Upgrade tab) use it instead, saying so in the budget's origin. Left empty,
it's not used. Everything that falls out comes back with a reason (`--show-rejected`).

- **Frame size is a gate, not a score.** A bike outside the target size never
  appears, whatever it scores. A bike whose size Marktplaats does not report
  is a separate case — it stays in the list flagged `maat onbekend`, because
  on Marktplaats the size is often only in the description and dropping all of
  those costs more candidates than it saves. `--strict-size` drops them too;
  `--size` and `--size-tolerance` override the target (default: the `size_cm`
  line in `mijn_fiets.md`, ±2 cm).
- **The budget depends on the candidate.** The carbon wheelset is a rim-brake
  set. For a rim-brake candidate it moves over to the new bike, so it is not
  money to spend but points to score — the candidate is scored with those
  wheels if they beat its own. For a disc-brake candidate it cannot move and
  has to be sold, so its proceeds are budget instead. A candidate whose brake
  type could not be read gets the rim-brake (lower) budget and no wheel bonus:
  until it is established that the wheelset can be sold, its proceeds are not
  spendable. `--budget-extra` sets the money on top of the sale (default: the
  `budget_extra` line in `mijn_fiets.md`).
- **Effective price.** An asking price times the negotiation factor, or what
  it costs to get into a bid (see `RUIMTE` above). The asking price stays
  printed next to it, so a corrected number is never mistaken for one.
- **Model year.** A year labelled in the text ("bouwjaar 2016") wins; without
  one, a bare year in the title ("Giant Defy 2012") is used — the same rule
  the valuation's comp ladder uses — and the candidate says so
  (`bouwjaar 2012 uit de titel`). A year that only appears unlabelled in the
  description is not taken ("sinds 2018 in bezit" is no model year). Without
  any year the frame gets no age decay, so a bike whose year is unknown still
  scores somewhat higher than the same bike with its year known.
- **Ranked on upgrade per euro** — `(score − baseline) / effective price`,
  printed as points per €100. No brake type is excluded up front: a genuine
  bargain on a disc-brake bike is the reason this tool exists, so the ranking
  does the work instead of a filter.

Every candidate prints its full per-dimension breakdown, and the budget prints
its own sum. Options: `--margin` (points above baseline before something
counts as an upgrade, default 5), `--query`, `--window-days`, `--limit`,
`--config` for the scoring weights, `--show-rejected`.

With `component_price` still empty there are no observations of what a loose
wheelset sells for, so the two budgets come out equal and the output says so
rather than guessing a number. It also bids on nothing and contacts no seller:
that is out of scope, by design.

### Report tabs — Biedpaneel, Upgrade, Mijn fiets

Next to the listings table (which keeps its row filters and sortable columns
as before) the HTML report has three more tabs (PLAN_FIETSWAARDE.md fase 6).
The chosen tab is kept in the URL (`#upgrade`), so reloading the report after
a new run lands on the same one.

- **Biedpaneel** — every bidding listing, sorted on headroom (estimated value
  minus what it costs to get in, the same numbers as the `RUIMTE` column in
  the console). Unknown headroom sorts last and reads `onbekend`, never €0.
- **Upgrade** — the candidates `upgrade.py` would print, for this run's
  listings: ranked on upgrade per euro, with asking price, effective price,
  budget, the size verdict and the per-dimension breakdown (hover a dimension
  for its reasons). What fell out is listed under `Afgevallen`, with the reason.
- **Mijn fiets** — the valuation of your own bike per scenario (A and B) as a
  low–mid–high band with n, the budget it gives the upgrade-finder, the full
  evidence list with links to the comps, and the baseline quality score.

The last two read `mijn_fiets.md` (`--mijn-fiets`) and value the bike on the
comps in `koopjes.db` — read-only, nothing is saved; `valuation.py` stays the
one that writes valuations. With `--no-db`, a missing intake file, or no
comparable listings in the database yet, those tabs say why instead of
showing a number.

**Waardescore.** The Upgrade and Biedpaneel tabs have a `Waardescore` column:
estimated value divided by effective price, where 1,00× means the price is
what it is worth and higher is cheaper. It is deliberately a separate column
from the dealscore, and a different measure — the dealscore scores the price
against the median, the average second-hand price and the original price on
0-100. The value is the model's observed second-hand average (if there are at
least two observations) or else the query median, both corrected from asking
price to selling price; the divisor is the effective price, not the bare
asking price, so a fixed-price listing at the median scores 1,00× and a bid is
measured against what it costs to get in. Hover the number for the sum.

### `check_hifi_brand.py` — a research aid for filling in the reference file

When researching models for `reference_prices.csv` (audio speakers), this
checks which models a brand actually has on hifidatabase.com, with
view/vote counts, in a single request — much cheaper than a full web
search per model, and the vote count tells you upfront whether a model
is even worth researching further before spending that search.

```bash
python check_hifi_brand.py "Mission"
python check_hifi_brand.py "Wharfedale" --min-votes 5
```

Not wired into `racefiets_jev.py` itself — it's a standalone lookup you run
by hand while researching, not something the main script needs. The site
has bot-protection that kicks in after several rapid requests, so use it a
brand at a time rather than in a loop.

### Price drops

If a listing you've seen before shows up again at a lower price, it's
flagged `v` in the console and gets an orange `-€X` badge in the HTML report
(with its own "Prijsverlaging" filter tab) — often a stronger buy signal
than "new". Needs no extra setup; it's derived from the same history file
that already tracks "new" listings.

### Notification on a reference match — `--no-notify-better`

When a new listing matches a reference model flagged `better_than_baseline`,
the script plays a system sound (Windows) or the terminal bell (elsewhere)
and prints a highlighted summary — separate from `--open-browser`'s general
"something new" behavior, so this specifically flags the thing you're
actually hunting for. Disable with `--no-notify-better`.

### `check_reference_overlaps.py` — validate the reference file

As `reference_prices.csv` grows, a pattern can end up broader than intended
and start matching listings meant for a different row (first match in file
order wins, so the broader row silently steals them). This checks every
row's pattern against every other row's own label and reports any
unexpected match — no network access needed.

```bash
python check_reference_overlaps.py
python check_reference_overlaps.py --file reference_bikes.csv
python check_reference_overlaps.py --file reference_bike_accessories.csv
```

### `reference_overview.py` — browse the reference database

Renders `reference_prices.csv` (plus `reference_price_history.csv` if
present) as a standalone, searchable, sortable HTML page — a way to review
your whole reference database without opening the CSV.

```bash
python reference_overview.py
```

`reference_prices.csv` itself is gitignored by default (like the other
local/personal files), so it's yours to edit freely without it showing up as
a change to commit — except this repo's copy is force-added anyway, since it
already has real researched entries in it (currently a handful of bookshelf
speakers, compared against a Denon SC-N10 baseline — see git log for the
sources). Keep adding to it freely; `git add -f reference_prices.csv` if you
want your local edits committed too, otherwise they just stay local. The
same goes for `reference_bikes.csv` and `reference_bike_accessories.csv`
(force-added, with a `source_url` per row).

### Off-topic results on deep pages

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
the others in its output; `--category` (above) chooses instead.

"Wanted" ads — someone looking to buy, posted in the same category — are
skipped too, and counted in the output. Nothing in the listing data marks
them, so this goes by the title: "gezocht" at the start, at the end, or in
brackets ("Gezocht: racefiets", "Garmin Edge 530 gezocht", "(Gezocht)"), but
not "veel gezocht model".

## Notes

This scrapes Marktplaats' public search result pages directly (no API key
or third-party service required). Marktplaats may change its page
structure at any time, which can break parsing — the script prints a
clear error if that happens rather than failing silently.
