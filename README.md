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
python koopjes.py dashboard         # rebuild dashboard.html and dashboard_horloges.html without a round
```

Paste what `schedule` prints into a command prompt (Windows) or `crontab -e`
(macOS/Linux) once, and the rounds run by themselves. What a round does:

1. takes a lock — a round that starts while another is still running is
   skipped, so Marktplaats never gets two crawls at once;
2. writes the searches into the watchlist table (see "Watchlists" below), so
   `schedule.json` stays the one place to change them;
3. runs `racefiets_jev.py` once for all the slot's searches, with the slot's
   `pages`, `sort` and `bid_lookup` — and once more, with `--no-html`, for
   the searches marked `"report": false` (see below). A search can have its
   own `"bid_lookup"`, which goes before the slot's (the sport watches use
   `"fast"`, also by day, see "Sport watches"); it then runs in a call of its own;
4. with `"valuation": true`, runs `valuation.py`, so the valuation history
   builds up by itself;
5. rebuilds **`overzicht.html`**: per search the latest run, how many listings
   are new / better than your reference / top deals / cheaper than before, the
   new listings most worth a look, this run's new **slapers** with their first
   photo (see "Slapers" below), a link to each full report, the latest
   valuation of your own bike, and the schedule;
6. rebuilds **`dashboard.html`**, one page with every bike computer on
   Marktplaats (see "Fietscomputers" below), and **`dashboard_horloges.html`**,
   the same for Garmin sport watches (see "Sport watches"). `overzicht.html`
   links to both, and each dashboard to the other. A new flip is logged
   ("Nieuwe flip: …", or "Nieuwe flip (horloges): …") and, in a slot with
   `"open_browser": "auto"`, opens the dashboard it is on.

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
| `overdag` | 08:30, 13:30, 19:30 | racefietsen around size 56, newest first, 8 pages — 150-180 arrive between two runs, 8 pages leaves room. With the category set, "racefiets" returns the whole category (12780 results with the query, 12780 without, 23-09-2026), so a listing titled just "fiets" or "Cannondale CAAD10" is in there too |
| `nacht` | 03:00 | complete crawls of "giant defy" and "ultegra 6700" (comps for your own bike, and complete, so sold listings are counted), the powermeter and bike computer searches, all Garmin, Polar, Suunto and Coros watches (`sporthorloges`, `polar`, `suunto`, `coros`: ~71 pages, plus a bid lookup for each of the ~370 "bieden" listings without a price), then `valuation.py` |
| `computers` | 10:00, 14:00, 18:00, 22:00 | the newest bike computers and Garmin watches only, 2 pages each (3 requests per search, 6 a round), so a cheap flip doesn't wait for the night. Polar, Suunto and Coros only run at night: with ~5 new listings a day, 2 pages would fetch the same listings and bids every round. Watches: ~115 new on a Monday until 20:45 (28-09-2026), so 2 pages every 4 hours is enough there too. The whole category gets about 100-120 new listings a day, roughly a quarter of them a computer with a known model (measured 28-09-2026: at 18:40 "Vandaag" filled 3-4 pages newest first, "Gisteren" about 4), so 2 pages every 4 hours leaves room — also for the ~7 paid "Dagtoppers" Marktplaats puts on top of page 1 whatever the sort. For the bike computers `bid_lookup` `fast` cost 17 bid lookups a round on top of that, so the slot has `none`: a bidding bike computer shows under "Zonder prijs — bied maximaal" by day, and the night round fills in the running bid. The Garmin watches override that with their own `"bid_lookup": "fast"` (~15 lookups a round). A looked-up bid stays in the database until the next lookup (migration 11), so a round without lookups no longer wipes it. Being shallow, it never marks anything as gone: that stays with the night round |
| `week` | Sunday 05:00 | all racefietsen Marktplaats will show (~5000, about 10 days' worth), without bid lookups |
| `horloges` | by hand (`python koopjes.py run horloges`) | all sport watches at once — the `sporthorloges`, `polar`, `suunto` and `coros` searches, complete, with bid lookups (~71 pages plus ~400 lookups, 15-20 minutes) — then both dashboards; `dashboard_horloges.html` opens if there's a new flip. The night round does the same every night; this slot is for looking now. `koopjes.py schedule` leaves it out, `status` shows it as "handmatig" |

Change the searches' filters (a `max_price` for your budget, say) and the
times in `schedule.json`; `python koopjes.py status` tells you straight away
if something in it is wrong. Searches accept the same filters as a watchlist,
plus `"report": false` for a search whose listings only need to be in the
database — the bike computer search has it: it used to query 17 brands,
which gave 17 separate reports (`racefiets_report_garmin-edge.html`, …); now
everything is on the dashboard, and those files are no longer written (old
ones can be deleted). Slots take `searches`, `pages` (0 = everything), `sort`, `bid_lookup`,
`times` (`"HH:MM"` or `"zo HH:MM"`, Dutch day abbreviations), `valuation` and
`open_browser` (and a `note`, which is ignored). With `open_browser` `auto`,
`overzicht.html` opens when a search *with* a report found new listings, and
`dashboard.html` opens when the round found a new **flip** — a bike computer
first seen this round, below its expected selling price after shipping, not
bought by you and not reserved. The log names each one (`Nieuwe flip: €25
winst — Garmin Edge 530 voor €90 — https://...`). A new listing in a search
without a report doesn't open anything: in the bike computer category that is
mostly an e-bike display.

A shallow round sorted newest first can tell when its pages weren't enough:
if the bottom 5 listings of its last page were all new, the previous round
wasn't reached and there may be new listings beyond that page. Only listings
that pass the search's filters count: one outside the price or frame range
never goes into the history, so it would look new every time. The log then
says `let op: de onderste 5 advertenties op pagina 2 waren allemaal nieuw` —
raise `pages`, or run the slot more often. (The bottom 5 rather than the
whole page, because page 1 starts with the Dagtoppers, which are usually old.)

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
| `--detail-lookup` | `budget`: fetch the listing page (full description, "Kenmerken") for complete road bikes within your size and budget — at most 10 per run, each listing once, only with `--db`. `none` skips it | `budget` |
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
have results for the query. With several categories, one that has no results
for the query today is skipped with a warning ("let op: categorie ... heeft
nu geen resultaten"), so a quiet day in one category doesn't cost the whole
search; only when none of them has results is it an error. Several categories must share a main category
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

### Slapers — listings whose text says nothing about the bike

The dealscore needs a price and, to be any good, a recognised model. Some of
the best buys have neither. The case this was built on: a Cannondale CAAD10
(23-09-2026) titled "Heren racefiets", described as "Moet weg wegens
verhuizing!", brand field "Overige merken", bieden zonder minimum — gone for a
€45 bid two hours after it went up. Nothing in the text said Cannondale; the
photos did. Nobody searching on a brand finds such a listing, and a seller who
writes five words isn't holding out for the best price.

`sleepers.py` looks for exactly that, using only what the search results
already contain (no extra requests to Marktplaats):

| Signal | Points |
| --- | --- |
| title made up of generic words only — type, sex, size, material, colour, condition ("Heren racefiets", "Racefiets 56cm") | 35, **required** |
| description of 15 words or fewer, or Marktplaats' own `thinContent` flag | 20 |
| a phrase that says it has to go: "moet weg", verhuizing, opruimen, zsm, weg=weg, plaatsgebrek, nalatenschap, … | 20 |
| a bid listing nobody has bid on yet, or an asking price at or below 60% of the search's median | 15 |
| first seen this run | 10 |

At 70 points a listing is a **slaper**. Ruled out altogether: a title with any
word outside the generic list (a brand, a groupset, a model name), a
description that names a brand (the brands in `reference_bike_catalog.csv`
plus a short list in `sleepers.py`), and a listing Marktplaats marks as
reserved. A running FAST_BID counts for no price points: its price is the
bidding so far. On a crawl of 240 racefietsen (8 pages, newest first,
23-09-2026) 13 titles passed the generic-words test, 8 of those named a
brand in the description, and one listing ended up a slaper.

The report has a **Slapers** tab with a card per listing — its photos (up to
three, as big as the search results give them), price, place, the reasons
and the description — the console prints a `SLAPERS` block after the bid
overview, and `overzicht.html` lists this run's new ones. This is not a
valuation and not a dealscore: it only says "look at the photos". Speed is
what counts with these, and bidding stays something you do yourself.

The report CSV (`--output`) gains five columns at the end: `thin_content`,
`reserved`, `image_urls`, `sleeper_score`, `sleeper_reasons`. Existing
columns keep their place.

The generic-words list is written for road bikes; on other queries (hifi, for
instance) hardly any title passes it, so there will simply be no slapers.

### Fietscomputers — the dashboard (`dashboard.py`, `computers.py`)

**`dashboard.html`** is the one page for bike computers: everything the
`fietscomputer` search found, across all its brands and earlier rounds, built
from `koopjes.db`. `koopjes.py` rebuilds it after every round;
`python dashboard.py` (or `python koopjes.py dashboard`) does it by hand.
Active means: not disappeared, and seen within 3 days of the newest listing
in the category (`dashboard` in `computer_scoring.json`). Tabs:

| Tab | What |
| --- | --- |
| **Flips** | every computer below its expected selling price, biggest profit first; reserved listings are left out (they're in Alle computers, marked "gereserveerd"), and so are listings you put away yourself (below) until their price drops. Per listing: the profit, the band around it, what it costs and what kind of price that is (fixed price / asking price, bidding possible / current bid, still rising), the expected selling price with n, and a photo. Below that: listings without a price, with the **maximum bid** at which you still break even at the low estimate |
| **Favorieten** | the listings you marked ★ favoriet (below), with your note and the price when you marked them if it has changed since; below that, favourites that are no longer online ("verdwenen" or "laatst gezien") |
| **Mijn flips** | what you bought and sold yourself: realised profit, what's in stock and what it should bring now, average days to sell, how far the dashboard's estimate was off, and profit per month. Entered in the live version (below) |
| **Upgrades** | computers that do more than your own, with the points they add, the **net** cost (price minus what your own computer would sell for) and what you gain or give up ("plannen op het apparaat: volledig i.p.v. beperkt", "touch i.p.v. knoppen") |
| **Alle computers** | everything, including computers whose model isn't in the file ("model onbekend": Van Rysel GPS 500, Sigma BC 509, ...) — search box (also searches your notes), brand filter, "alleen nieuw", sortable columns. **Toon** hides the listings you put away (the default); set it to *favorieten*, *weggezet* (to put one back), *met notitie* or *alles* |
| **Marktprijzen** | per model: how many for sale, lowest and median asking price, expected selling price, original price, score |
| **Vinted** | once you've read in a Vinted export (below; until then the tab says how, and which database it reads): Vinted listings you could buy and sell on Marktplaats at a profit — what you pay there (asking price + buyer protection + shipping) against the Marktplaats selling price — and per model the Vinted asking prices next to Marktplaats |
| **Patronen** | long-term patterns from everything the crawl ever saw, gone listings included (`patterns.py`): per model how long listings stay online, how many are gone within 14 days, the median asking price, the last price of the quick ones, and how often the price was lowered; the **measured haggling factor** (last price of listings gone within 14 days ÷ the model's median asking price, shown from 20 such listings — then you can put it in `computer_scoring.json` instead of the assumed 0,875); whether the listings that were flips at first sight went faster than the rest; the median asking price per month; and new listings per weekday. Gone is not sold (a listing can be withdrawn), and a listing is only marked gone by a complete nightly crawl, so this needs a few weeks of `python koopjes.py run nacht`. Gone listings that were reserved when a round last saw them are counted apart ("eerst gereserveerd"): those were almost certainly sold. Only reservations a round actually saw count, so it's a lower bound. The hour of posting isn't available: Marktplaats only says "Vandaag"/"Gisteren" |
| **Uitgefilterd** | holders, cases, parts, broken ones and wanted ads, each with the reason, to check that no real computer ended up there |

Photos come from the search results (stored since database migration 6); a
listing from before that shows a grey square until the next round sees it.

**Recording your own buys and sales — `python dashboard.py --serve`.** The
written `dashboard.html` only reads. `--serve` starts a small program on your
own computer (only reachable at `http://127.0.0.1:8765/`, `--port` to change)
that shows the same dashboard live and opens it in your browser; stop it with
Ctrl+C. Every listing then has a **Gekocht** button with its price filled in,
and **Mijn flips** has a **Verkocht** form per item in stock (sale price,
shipping — €3 filled in —, date, Marktplaats/Vinted/other), "terug naar
voorraad", "verwijderen", and a form for buys made elsewhere (a Vinted buy,
say). Everything goes into `koopjes.db`, table `trade` (migration 7): what
you paid and got, plus what the dashboard expected at the time you bought,
so you can see how good its estimates are. Your own buys and sales are never
used as comparables for other listings, and your own buy doesn't count
towards the estimate of what it will sell for. Something you bought
disappears from Flips and Upgrades and gets a ✓ in Alle computers. Every form
carries a secret chosen at start-up, and the program checks where a request
comes from, so another website can't write into your database through your
browser.

**Favourites and putting listings away.** So you don't keep going through
the same listings, every listing in the live version also has
**☆ favoriet** and **weg: niet waard / gereserveerd**. A favourite gets a ★
and its own tab, Favorieten. A listing you put away leaves Flips, Upgrades
and "Zonder prijs" (also in `python watches.py`); Flips says how many you
put away. It stays in Alle computers behind the **Toon** filter, where
**terugzetten** undoes it. Putting away isn't forever: the price at that
moment is stored,
and once a round sees the listing cheaper it is back on Flips with a line
"Weer terug: de prijs zakte van €90 naar €70" — put it away again and the new
price counts. Every listing can also carry a **notitie** of your own
("gevraagd of €120 kan", "mail gestuurd, wacht op antwoord"), marked or not:
click "notitie toevoegen" under it. The note shows under the listing
everywhere it appears, also under a favourite that went offline; the search
box in Alle computers searches it too, and **Toon: met notitie** shows all
listings that have one. A note is about the listing, not your mark: removing
the mark leaves it. One line, at most 500 characters; an empty note clears
it. After a click the page comes back on the same tab, at the same place,
with the same search. Marks go into `koopjes.db`, table `listing_mark`
(migration 12, `marks.py`), one per listing; notes into table `listing_note`
(migration 14, which moves over the notes migration 13 kept on marks). Both
are your judgement, not a market observation, so a listing you put away
still counts as a comparable. The written `dashboard.html` shows the marks
and notes but has no buttons. Vinted listings and the Uitgefilterd tab have
no marks or notes (yet).

**Your own computer's value.** "Netto" in Upgrades is the price minus what
your own computer sells for: `eigen_verkoopprijs_eur` under `baseline` in
`computer_scoring.json`, set to €75 (a black spot bottom right on the screen,
otherwise fine; an undamaged Roam v1 was estimated at ±€109). Set it to
`null` to use the market estimate again.

**Profit** = expected selling price − price − shipping (€3). The selling price is the
median of what other listings for the same model ask (this and earlier rounds,
last 180 days, sold ones included), × 0,875 for haggling (the same heuristic
as `valuation.py`); the band uses the lower and upper quartile instead of the
median. Only with at least 3 other listings; a running bid is never a
comparable.

**Per variant first.** Variants share a row in the reference file ("Edge 530"
is also the sensor bundle, "Fenix 7" also the 7S and the 7X Sapphire Solar),
so one median would mix them. `computers.title_variant()` reads the variant
from the title: a size letter right after the model number (7S, 7X, 6S Pro,
265S), a case size in mm (35-55 mm; "22mm" is a strap), and the words Solar,
Sapphire, Titanium, AMOLED (also "OLED"), MicroLED, Music, LTE, bundle and the
MARQ editions (Athlete, Aviator, Captain, ...). A flip is compared with
listings of the same variant when there are at least 3 of them — a title that
names none is the plain variant, and a missing mm size fits any size — and
otherwise with the whole model, as before. The dashboard says which, under the
selling price ("n=6, zelfde uitvoering: X · Solar · Sapphire" or "n=12, hele
model; S: 1"), and Marktprijzen lists the variants on sale per model with
their median asking price. On the full Garmin watch crawl of 28-09-2026, 778
of 1229 watches had enough of their own variant: a plain Fenix 7 at +€3 and a
Fenix 8 AMOLED 47 mm at +€29 turned out not to be flips, a Fenix 6 Sapphire
Titanium went from −€7 to +€63. Mijn flips and the model rows in Marktprijzen
still use the whole model. `costs_eur` in `computer_scoring.json` comes off every flip and
off the maximum bid: €3 shipping by default (the owner's choice, 28-09-2026);
raise it if you also want fuel or packaging counted. A "gratis" listing
(priceType FREE, €0) has no price rather than a price of €0: it's never a flip
or a comparable and shows under the maximum bids, labelled "gratis of ruilen,
prijs onbekend" — among the sport watches it was a swap offer that topped the
flips at +€559. A title with an accessory word right after the model and only
a device word in between, no "met"/"incl."/"+" ("Garmin Venu Smartwatch
bandjes en beschermhoezen", €25), is checked against the price: under 40% of
the same model's median (`max_share_of_median`) it counts as an accessory.
With a linking word ("Venu Sq - Inclusief Oplaadkabel", €40) it stays the
device — a cheap one.

**What counts as a computer.** Only the title is used, and every title with a
known model gets one kind: `computer`, `accessoire`, `onderdeel`, `defect`
or `gevraagd` (a bike, or a listing in a bike category, is left out
altogether). From the full crawl of the category (28-09-2026, 361 listings):
a real computer names the device or a connector before the holder or case
word — "Garmin Edge 530 + stuurmount", "Garmin Edge Explore fietscomputer met
houder en doos", "Garmin 840 Sensor Bundle" — while a loose accessory has that
word before the model ("Hoesje voor Garmin 1000", "K-Edge ... Bolt ... mount")
or right after it with nothing in between ("Hammerhead Karoo 3 houder nieuw").
That last case is decided on price: under 40% of the median for the model,
or without a median under 20% of the original price, or without either under
€30 (`filter` in `computer_scoring.json`), it's an accessory. A doubtful title
without a price stays a computer, marked "kijk op de foto" — better a holder
that slips through (the photo shows it) than a computer that disappears.
Titles without a known model go through the same kind of rules: e-bike and
fatbike displays (Bosch, Sparta, Gazelle, Batavus, H6C, Shimano SC-E…,
"display", "scherm") are `e-bike`, a holder or sensor without a computer
before it is `accessoire`, and a title that names neither a bike computer nor
a brand that makes them is `overig`. What's left shows as "model onbekend".

Spellings sellers use are tidied before matching: runs of spaces become one
("Garmin Edge  1030 Plus"), a hyphen between a name and a number becomes a
space ("EDGE-530"), and "Egde" reads as "Edge". "520+", "Explorer 2",
"Garmin Explore 2" and "Wahoo Element Ace/Mini/Bolt/Roam" match their model.
Holder and case words also count in French, Spanish, Italian and German
(support, soporte, supporto, Halterung, staffa, capa, coque, funda, housse,
étui, protection), and so do the connectors "mit", "inkl", "avec" and "con".
"For", "voor", "pour", "para" or "für" right before the model name makes it
an accessory ("Wahoo bike computer for Element ROAM"). All of these came from
a Vinted export of 867 Garmin and Wahoo titles (28-09-2026).

The `fietscomputer` search covers the **whole category**: with the category
set, "fietscomputer" returns everything in it (2800 listings on 28-09-2026,
as many as no query at all). About 95 pages a night instead of ~360 listings
for 17 brand names, but it found 87 more computers with a known model —
titles like "Garmin 830" or "Garmin 1030 incl. stuurmontage" that "garmin
edge" doesn't match. On that crawl 1734 listings were e-bike displays and
went to Uitgefilterd, and no computer the brand searches had found was lost.

Always excluded: repairs and defects ("scherm vervangen", "defect", "voor
onderdelen", "batterij vervangen"), parts ("LCD", "color kit", "koord"),
wanted ads ("ik zoek ...") and — the one rule that reads the description — a
listing whose description says the computer isn't included ("accessoires
zonder de fietscomputer"). On that crawl this kept 277 computers with a
known model and put exactly the 18 accessories, parts, repairs and wanted ads
in Uitgefilterd.

Two measures, shown separately — neither is the dealscore:

- **Upgrade** — the model's feature score (0-100) minus that of your own
  computer (`baseline` in the JSON: the Wahoo ELEMNT ROAM v1). The weights
  were chosen by the owner (28-09-2026): navigation 35 (rerouting, routable
  maps, automatic Strava/Komoot sync), planning on the device itself 20,
  training 25 (ANT+, Di2/AXS, workouts, climb feature), controls 10 (buttons
  over touch), battery 10. A model without updates any more loses 15 points,
  one whose maker stopped but still supports it 5. An empty field was not
  researched and earns nothing — the dashboard says per model how many fields
  are unknown, so a low score can mean "unknown" rather than "bad".
- **Flip profit** — see above.

A regular report (`racefiets_jev.py`) of a run that contains bike computers
still gets a small **Fietscomputers** tab with its flips, upgrades and what
was filtered out; a run without any doesn't show the tab.

**Vinted next to Marktplaats — `vinted.py`.** Vinted has no crawl here: you
export a Vinted search yourself (a CSV with the columns "Item Title", "Item
Price", "Item Service Fee", "Item Total Price", "Item Currency", "Item URL",
...) and read it in. The time of the export comes from the file name
(`productsList_2026-09-28T14-57-35-028Z.csv`), or `--at`. A file without
those columns stops with the name of the missing one. It always writes to the
`koopjes.db` next to the script (the one `koopjes.py` uses), whatever folder
you type the command in, prints which file that is, and warns when it had to
create it — so an import from your Downloads folder still ends up in the
dashboard. `--db` picks another one.

```bash
python vinted.py import productsList_2026-09-28T14-53-37-277Z.csv productsList_2026-09-28T14-57-35-028Z.csv
python vinted.py                   # per model Vinted vs Marktplaats, and what to buy on Vinted
python dashboard.py                # the same in the tab Vinted
```

The listings go into their own tables (`vinted_listing`, `vinted_price`,
database migration 8), never into `listing`: a Vinted price is never a
comparable for a Marktplaats flip, and a listing missing from a later export
isn't marked sold (an export is one search, not a full crawl). What you pay is
the asking price plus the buyer protection the export states (€0,70 + 5% on
28-09-2026) plus `vinted.shipping_eur` in `computer_scoring.json` (€4,50, the
top of what a small parcel within the Netherlands costs; more from abroad —
the export doesn't say from where). The profit is the Marktplaats selling
price from Flips minus that and minus `costs_eur`. Titles are sorted with the
same rules as the dashboard, plus what only Vinted returns because it doesn't
search within a category: watches (Wahoo Rival, Forerunner, "montre",
"reloj"), trainers, pedals, car navigation, and anything above
`vinted.max_price_eur` (€1000: a bike with a computer thrown in). Doubtful
titles are judged against the Marktplaats median, as on the dashboard.

What a comparison of both sites on 28-09-2026 showed (Garmin and Wahoo, 562
computers on Vinted, 254 on Marktplaats): for the models that sell a lot
(Edge 530, 830, Explore, Explore 2, 540, 840, 1040, 1050) the median asking
price is within 10% on both sites, so buying on Vinted pays only listing by
listing. Older models ask much more on Vinted (Edge 1000 twice as much), but
most of those listings have been online a long time, so that's no higher
selling price.

```bash
python koopjes.py run nacht        # includes the "fietscomputer" search: the whole category, all pages
python koopjes.py run computers    # by day: only the newest 2 pages; opens the dashboard on a new flip
python dashboard.py --open         # rebuild dashboard.html from koopjes.db and open it
python dashboard.py --serve        # live, with Gekocht/Verkocht and favoriet/weg buttons (Ctrl+C to stop); watches at /horloges
python computers.py                 # feature score per model, with the difference to your own
python computers.py --merk wahoo
```

The CSV uses fixed words so the score can read it: `rerouting` is `ja`,
`via_telefoon` or `nee`; `kaarten` `routeerbaar`, `los_te_koop`, `basiskaart`
or `nee`; `planning_op_apparaat` `volledig`, `beperkt` or `nee`; `bediening`
`knoppen`, `touch+knoppen` or `touch`; `ondersteund` `ja`, `beperkt` or `nee`.
Anything else stops the load with the row number. Numbers use a dot. The file
order is the match order, so "Edge 1030 Plus" comes before "Edge 1030". Like
the other reference files it is added with `git add -f`.

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
the first of those rows would ever be used — which is also why it can't be
passed to `--reference-file` (the run warns and matches nothing). Only its
`brand` column is read automatically: `sleepers.py` uses it to rule out
listings that name a brand, and `koopjes.py`'s list of unmatched listings
groups by it. The rest — specs and new prices per model year — is reference
data for looking things up by hand; the valuation doesn't read it (yet).

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

### Sport watches — `dashboard_horloges.html` (`markets.py`, `watches.py`)

A second market next to bike computers, built the same way: every Garmin,
Polar, Suunto and Coros watch on Marktplaats, its model recognised from the
title, flips worked out against the same model's asking prices, and a
dashboard of its own. Smartwatches (Apple, Samsung, Fitbit, Huawei) are a
different market and not followed (yet); they land in Uitgefilterd as
"ander merk" when a search picks them up.

- **The search** `sporthorloges` in `schedule.json`: "garmin" in the
  categories `sporthorloges`, `smartwatches` and `activity-trackers` — that's
  where the watches are; straps and cables mostly sit in phone and wearable
  categories, and `activity-trackers` also holds Fenixes and Forerunners that
  sellers put there. 1707 listings on 28-09-2026, 58 pages. In the night slot
  (complete, so gone listings are marked for Patronen) and in the `computers`
  slot by day (2 pages). Its own `"bid_lookup": "fast"`, night and day: about
  300 of those listings are "bieden" without a price, and bids matter here, so
  each is looked up (~300 extra requests a night; by day only those on the 2
  newest pages). The price then reads "3 biedingen · min. €100 · opgehaald
  dd-mm-yyyy HH:MM" or "nog geen bod", and it stays until the next lookup
  (migration 11: `listing.bid_count`, `bid_minimum`, `bids_checked_at`).
- **The searches** `polar`, `suunto` and `coros`: the same three categories,
  night slot only, also with bid lookups. 214, 84 and 36 listings on
  28-09-2026 (13 pages together); with ~5 new a day, a day round would fetch
  the same listings and bids over and over. Suunto's dive computers mostly
  sit in the `duiken` category and stay out.
- **The models** in `reference_sport_watches.csv` (below): 81 Garmin models,
  from the Forerunner 30 and Venu Sq to the Fenix 9 Pro and MARQ, plus 18
  Polar, 19 Suunto and 13 Coros models. On the full Garmin crawl 1263 of 1707
  titles name one; the rest are mostly straps, cables and other brands. Of
  the 327 listings from `polar`, `suunto` and `coros` (28-09-2026), 192 name a
  Polar, Suunto or Coros model (4 more a Garmin); most of the rest are
  older models without a source (Polar M400, V800, M600, Loop; Suunto Core,
  Traverse) that show as "horloge, model onbekend".
- **The dashboard** `dashboard_horloges.html`: the same page as the bike
  computers' — tabs Flips, Favorieten, Mijn flips, Alle horloges, Marktprijzen,
  Patronen and Uitgefilterd — without Upgrades (there is no own watch to
  compare with), Vinted and the feature score. `koopjes.py` writes it after
  every round; `python dashboard.py --markt sporthorloges` (or `--markt alle`)
  by hand. `python dashboard.py --serve` shows it live at
  `http://127.0.0.1:8765/horloges`, with the same Gekocht/Verkocht and
  favoriet/weg buttons;
  a buy remembers its market (database migration 10, `trade.market`), so each
  dashboard's Mijn flips shows its own. Buys from before that have no market
  and belong to the bike computers, unless their model is a watch.
- **The calculation** is the bike computers' (`computers.apply_computer_signals()`)
  with the watch catalogue and the same `computer_scoring.json` — the same
  assumed 0,875 and €3 costs — with comparables from the three watch
  categories only. `watches.py` holds what is specific to watches: the
  categories, and what a title without a known model is (`classify_unknown()`:
  a Garmin, Polar, Suunto or Coros watch with an unknown model stays visible
  in Alle horloges — "Te koop Garmin horloge" may be a sleeper, and "Suunto
  Traverse GPS-horloge + hartslagband" is a watch with a strap —; straps,
  chargers, other brands such as Apple, and products that aren't watches such
  as the Garmin Index scale or a Polar bike computer go to Uitgefilterd, each
  with the reason). `markets.py` puts the two
  markets side by side: categories, catalogue, file, which tabs.
- `python watches.py` prints the same per model and the flips in the console.

Read the flips with care. Variants share a row (5/5S, Solar, Sapphire, Music,
43/47/51 mm); a flip compares with the same variant when there are at least 3
of them (see "Per variant first" above), but a title that doesn't name its
variant is taken for the plain one, and with too few of the same variant the
whole model's median still mixes them — the band under each profit shows how
wide the spread is, and the line under the selling price which median it is. The 0,875
is not measured for watches; Patronen measures it once 20 quickly-gone
listings of the market are in (a few weeks of night rounds). What the first
crawl said, one snapshot, same method and day for both ("garmin,wahoo" in the
bike computer category for comparison):

| | Known model | Flips > €0 | Still a profit at the low estimate | … of which > €25 |
| --- | --- | --- | --- | --- |
| bike computers | 216 | 14 | 10 (4.6 per 100) | 6 |
| sport watches (Fenix/Forerunner/Epix only) | 605 | 96 | 46 (7.6 per 100) | 15 |

### The sport watch catalogue — `reference_sport_watches.csv`

One row per model, same shape as `reference_bike_computers.csv` — a regex
`pattern`, and the file order is the match order, so "Fenix 7 Pro" comes
before "Fenix 7" — and it loads with `computers.load_catalog(path)`.

Columns: `merk`, `model`, `pattern`, `introductiejaar`, `nieuwprijs_eur`,
`prijs_bron`, `nieuwprijs_usd`, `kaarten_op_horloge` (`ja`/`nee`/empty),
`extra_opmerkingen`, `bron_url`.

- **A euro price only where a source gives euros**: Garmin's Benelux press
  releases (garmin.prezly.com, "adviesprijs"; all ~110 read through its
  sitemap), a DC Rainmaker comparison table that states EUR, or, for the
  Fenix E, Android Planet's launch article. `nieuwprijs_usd` is DC Rainmaker's
  US price and is never converted. DC Rainmaker updates its comparison
  tables over time (the Vivoactive 3 shows $129 there), so a table price is
  only used where another source agrees; otherwise the note mentions it and
  the field stays empty.
- **No source, no row.** Tactix, Quatix, Approach S12/S42/S70 and Descent
  Mk3/G1 had no source with a year or price; they show as "horloge, model
  onbekend". The same for older Polar (M400, V800, M600, A360, RC3), Suunto
  (Core, Traverse, Ambit 1/2) and the Coros Apex Pro. The Polar Loop is left
  out on purpose: sellers call both the 2025 Loop and the 2015 Loop 2 "Loop
  gen 2".
- **Polar, Suunto and Coros come from DC Rainmaker's reviews**: the year from
  the review (published at launch), the price only as the review text states
  it — "$229/229EUR" gives both, "$449USD" only the dollar price. Patterns
  need the brand in front ("Polar Vantage V2", "Suunto Race", "Coros Pace 3"),
  because "Race", "Pace" and "Vantage" alone say too little.
- **`kaarten_op_horloge` only where the source says so.** It is not the
  `kaarten` column of the bike computer file (`routeerbaar`, `basiskaart`,
  ...); that vocabulary says something the sources for watches don't.
- **Variants share a row** where the price tier is the same (5/5S, 265/265S,
  Music editions, Solar/Sapphire); the flip separates them by the title where
  it can (`title_variant()`, above). Where the tier differs, they have their own
  row (Fenix 5X, Fenix 6 Pro, Fenix 7 Pro, Epix Pro, MARQ Gen 2). A "Fenix 6S Sapphire"
  without "Pro" lands on Fenix 6; whether every Sapphire edition was a Pro is
  not checked.
- **Two-digit Forerunners need the name**: "Forerunner 55" or "FR55", never
  "Garmin 55" — too easily a size in mm.

`tests/test_sport_watches.py` checks sources, fixed words, shadowing, and a
set of real titles; `tests/test_watches.py` the flip calculation, the
dashboard, the live version and Mijn flips per market.

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
  reference model it matched). Only asking prices count: a fixed price, and
  also a "bieden vanaf" (MIN_BID) price, since that's what the seller asks —
  over half the Defy listings are MIN_BID. A bid listing that already has
  bids is left out, because its price may then be the highest bid. Rows
  stored before this rule existed are re-judged the next time a crawl sees
  them.
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

Besides the text, the search results carry some of the seller's own
structured choices ("Kenmerken" on the listing page): the frame material on
roughly half the racefietsen, now and then the brake type. Those are read as
well and stored in `spec` under source `marktplaats`; where the text says
something about the same thing, the text wins (it's more specific —
"hydraulische schijfrem" where the attribute says "Schijfrem"). On 240
racefietsen this gave the frame material for 114 listings whose text didn't
name it.

The groupset is the bigger gap, and it's rarely in the first 200
characters. So for the few listings that could be an upgrade — a complete
road bike, not the wrong frame size, an effective price within the larger of
your two budgets — the run fetches the listing page itself
(`--detail-lookup budget`, the default): the full description and the
"Kenmerken" list (material, brake, frame height). At most 10 per run, most
promising first, and never the same listing twice: the text is stored in
`koopjes.db` (`listing.full_description`) and put back on later runs. The
quality score, the upgrade finder and the valuation read the full text;
reference matching and the slapers stay on the search snippet, since a
slaper is about what the *search* shows. Needs the database and a budget
(`mijn_fiets.md`); without either it does nothing. Two rules got stricter
with the longer text: a labelled groupset line ("Groepset: Ultegra") wins
over a higher-tier part further down ("Cassette: Dura Ace"), and "Garmin
houder" or "Wahoo Kickr" isn't a bike computer.

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
your own expected sale price there — the bike with its stock wheels, since
the carbon wheelset is budgeted separately per route — and the upgrade
finder (and the report's Upgrade tab) use it instead, saying so in the
budget's origin. It also wins over an `indicatief` valuation (fewer than 5
comps): one stray comp shouldn't quietly move your budget. A valuation on 5+
comps wins over it. Left empty, it's not used. Everything that falls out comes back with a reason (`--show-rejected`).

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

### Report tabs — Slapers, Fietscomputers, Biedpaneel, Upgrade, Mijn fiets

Next to the listings table (which keeps its row filters and sortable columns
as before) the HTML report has more tabs: **Slapers**, **Fietscomputers**
(only when the run has any; see those sections above) and the three below
(PLAN_FIETSWAARDE.md fase 6).
The chosen tab is kept in the URL (`#upgrade`), so reloading the report after
a new run lands on the same one.

- **Biedpaneel** — every bidding listing, sorted on headroom (estimated value
  minus what it costs to get in, the same numbers as the `RUIMTE` column in
  the console): first the ones valued on a reference model or comparable
  bikes, then the rough ones (marked `grof`), then the unknown ones, which
  read `onbekend`, never €0.
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
already has real researched entries in it (currently 43 bookshelf
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
