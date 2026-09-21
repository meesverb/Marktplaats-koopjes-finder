# Marktplaats koopjes finder

`racefiets_jev.py` searches [Marktplaats](https://www.marktplaats.nl) for
listings matching a query — road bikes ("racefiets") by default, but `--query`
works for anything (`--query muziekboxen`, `--query "canon eos"`, ...) — and
flags ones priced well below the median of what it found as a quick way to
spot bargains. The frame-height/groupset features below are bike-specific and
simply find nothing to match on other queries, which is harmless.

## Usage

```bash
pip install -r requirements.txt
python racefiets_jev.py --pages 10
python racefiets_jev.py --query muziekboxen --pages 10
```

Listings marked with `*` are priced at or below `--bargain-ratio` (default
`0.6`, i.e. 60%) of the median price across all listings fetched.

Every run also writes `racefiets_report.html` — open it in a browser for a
sortable, filterable overview (Nieuw / Koopjes) with clickable links to each
listing. It compares against `seen_listings.json` (created automatically) so
listings you've already seen in a previous run are marked accordingly instead
of showing up as "new" every time — handy if you run this script on a
schedule (e.g. every 15 minutes via cron / Task Scheduler).

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
| `--no-bid-lookup` | Skip fetching each FAST_BID listing's own page for its real bid amount (faster) | off |

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

### Bidding listings (FAST_BID / MIN_BID)

Some listings ("Bieden") don't have a fixed price — Marktplaats' search
results always report €0 for these (`FAST_BID`), even though the listing
itself has a real minimum starting bid, or a real current highest bid once
someone has bid. By default the script fetches each `FAST_BID` listing's own
page to get that real number (marked `B` in the table, "bod" in the HTML
report) and uses it everywhere — price filters, the bargain comparison, all
of it — instead of treating it as priceless. `MIN_BID` listings already
report a real number in search results, so no extra request is needed for
those, but they're marked `B` too since it's still a bid, not a fixed
asking price.

This means one extra request per `FAST_BID` listing found, so a run with a
lot of them takes longer. Use `--no-bid-lookup` to skip it and go back to
treating those listings as priceless.

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
pattern,label,original_price_eur,score
Canyon Ultimate CF SLX 8,Canyon Ultimate CF SLX 8 (2021),4000,8.5/10
```

- `pattern`: regex (case-insensitive), matched against the listing title.
  Put more specific patterns earlier in the file — the first match wins.
- `label`: what to display when matched.
- `original_price_eur`: what it cost new (optional — leave blank if unknown).
- `score`: any rating/ranking text you want shown (optional, free text).

When a listing matches, the report shows the label, what percentage of the
original price it's being asked for now (if you filled in a price), and the
score. See `reference_prices.example.csv` for the exact format — copy it to
`reference_prices.csv` and fill in models you actually care about (the
values in the example file are placeholders, not real prices). If you want
help researching a specific model's original price, just ask — that's more
reliable done one model at a time than guessed in bulk.

`reference_prices.csv` itself is gitignored by default (like the other
local/personal files), so it's yours to edit freely without it showing up as
a change to commit. Remove it from `.gitignore` if you'd rather keep it
version-controlled.

## Notes

This scrapes Marktplaats' public search result pages directly (no API key
or third-party service required). Marktplaats may change its page
structure at any time, which can break parsing — the script prints a
clear error if that happens rather than failing silently.
