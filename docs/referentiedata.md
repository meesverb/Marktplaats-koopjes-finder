# Referentiedata — de eigen prijs- en modellendatabase

[← README](../README.md) · [alle naslag](README.md)

De CSV-bestanden waartegen advertenties herkend en vergeleken worden, en de hulpscripts om ze te onderhouden. De catalogus van sporthorloges (`reference_sport_watches.csv`) staat bij de horloges in [horloges.md](horloges.md).

## Comparing against original prices — `--reference-file`

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
  Specialized Roubaix, Trek Domane), followed by one row per model family
  that often came up unrecognised in `lijsten/zonder_referentie.txt` (Giant
  TCR, Trek Madone, Cube Attain, Koga-Miyata, ...). Those family rows name
  no original price — a family spans trims and years — and fill in
  `frame_material` only where the name itself settles it (Advanced, ALR,
  CAAD, GTC, C:62, "Carbon"); their source is a representative row of
  `reference_bike_catalog.csv`, whose counts per material are in `specs`.
  Below those come 226 rows, one per model line of that catalog that none of
  the rows above recognises (brand + first word of the model name: BH Quartz,
  Felt F75, Cervélo R5, Trek Silque, Scott Contessa, ...), plus "Giant Defy
  (overig)" for a Defy the researched rows can't place. Those are for
  recognition only: the brand has to come before the line in the title
  ("Terra" and "Supreme" are bikes of several brands), and they name no
  original price and no `frame_material`. Catalog words that are ordinary
  Dutch or a number in a title (Pinarello "MAAT", Cannondale "700", Bianchi
  "1885") and catalog typos of a line that already has a row got no row.
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

## Bike catalogue — `reference_bike_catalog.csv`

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

## Your own market price history — `--price-history-file`

Every time a listing matching a reference model is seen for the first time,
its price gets logged to `reference_price_history.csv` (created
automatically). From the second time a model shows up, the report also
displays "2e-hands gem. €X (n=Y)" — the actual average secondhand asking
price you've personally observed for that model, based on Y past sightings.
This needs no research or original price at all, grows automatically the
more you run the script, and is arguably more useful than a decades-old
retail price for judging whether an asking price is reasonable. Disable
with `--no-price-history`.

## `check_hifi_brand.py` — a research aid for filling in the reference file

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

## `check_reference_overlaps.py` — validate the reference file

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

## `reference_overview.py` — browse the reference database

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
