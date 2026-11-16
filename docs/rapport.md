# Het rapport per zoekopdracht

[← README](../README.md) · [alle naslag](README.md)

Wat er in `racefiets_report*.html` staat en hoe de getallen tot stand komen: de dealscore, de slapers, prijsverlagingen, de melding bij een referentiematch en de tabbladen Biedpaneel / Upgrade / Mijn fiets.

## Dealscore

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

## Slapers — listings whose text says nothing about the bike

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

## Price drops

If a listing you've seen before shows up again at a lower price, it's
flagged `v` in the console and gets an orange `-€X` badge in the HTML report
(with its own "Prijsverlaging" filter tab) — often a stronger buy signal
than "new". Needs no extra setup; it's derived from the same history file
that already tracks "new" listings.

## Notification on a reference match — `--no-notify-better`

When a new listing matches a reference model flagged `better_than_baseline`,
the script plays a system sound (Windows) or the terminal bell (elsewhere)
and prints a highlighted summary — separate from `--open-browser`'s general
"something new" behavior, so this specifically flags the thing you're
actually hunting for. Disable with `--no-notify-better`.

## Report tabs — Slapers, Fietscomputers, Biedpaneel, Upgrade, Mijn fiets

Next to the listings table (which keeps its row filters and sortable columns
as before) the HTML report has more tabs: **Slapers**, **Fietscomputers**
(only when the run has any; see "Slapers" above and [dashboards.md](dashboards.md)) and the three below
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
one that writes valuations. The comps are the listings you took along on
`/fiets`. With `--no-db`, a missing intake file, or nothing taken along yet,
those tabs say why instead of showing a number.

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
