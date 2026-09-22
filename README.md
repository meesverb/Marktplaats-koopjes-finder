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
Run the script separately per query instead when the filters need to differ.

Listings marked with `*` are priced at or below `--bargain-ratio` (default
`0.6`, i.e. 60%) of the median price across all listings fetched. Every
priced listing also shows `% v. mediaan` — what percentage of the median
price it's asking, e.g. `24%` means it's asking a quarter of the median — so
you can judge relative cheapness on a scale instead of only the binary `*`
cutoff. In the HTML report this is a sortable column; it also feeds the
dealscore the report is sorted by.

Every run also writes `racefiets_report.html` — open it in a browser for a
sortable, filterable overview (Nieuw / Koopjes / Topdeals / Bieden / ...) with
clickable links to each listing, and the average/median price of what was
found. It compares against
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
| `--min-frame-height` / `--max-frame-height` | Filter by frame size in cm | none |
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
cm" for a `--min-frame-height 54` filter) may still show up, and a bike with
no frame size listed at all is excluded once this filter is active.

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
also prints a `BIED-OVERZICHT` section: all bidding listings, the ones nobody
has bid on first and each group sorted by dealscore, showing the minimum bid,
what percentage of the median that minimum is, and the reference model if one
matched. Those are the ones where you can still get in at the seller's own
floor price instead of bidding against someone.

A listing only counts as "still free to bid on" when its bid count was
actually looked up and came back zero — a `MIN_BID` listing without
`--bid-lookup all` has an unknown bid count, which is not the same as zero,
and stays out of that tab. So for a full picture of what's biddable:

```bash
python racefiets_jev.py --query luidsprekers --pages 5 --bid-lookup all --bids-only
```

`--bids-only` limits the report to bidding listings. The median, the
secondhand averages and the dealscore are still computed over everything found
first, so the comparison stays against the whole market rather than only
against other bidding listings.

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
to avoid matching on the plain Dutch/English word.

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
want your local edits committed too, otherwise they just stay local.

### Off-topic results on deep pages

Past a certain page depth (roughly page 50+ for "racefiets"), Marktplaats'
own search loosens from real matches to fuzzy word matches — e.g. old
PS2/Game Boy racing games showing up because their titles contain "racer".
The script detects Marktplaats' own "dominant category" for the query (the
category it considers the query to really be about) and drops listings
outside it, which removes this. It prints how many it dropped. This doesn't
catch the rare listing a seller mis-categorized themselves (e.g. cycling
shoes listed under "Racefietsen") — use `--exclude` for those if it becomes
annoying (not yet implemented — ask if you want it).

## Notes

This scrapes Marktplaats' public search result pages directly (no API key
or third-party service required). Marktplaats may change its page
structure at any time, which can break parsing — the script prints a
clear error if that happens rather than failing silently.
