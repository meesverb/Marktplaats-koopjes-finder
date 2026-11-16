# Racefietsen — `/racefietsen`

[← README](../README.md) · [alle naslag](README.md)

Alle racefietsen op één live pagina: kaarten met foto's, schatting, upgrade-oordeel, het dossier voor Claude en de fietsmodellen (koppelen, regels, vergelijken op model).

## Racefietsen — `/racefietsen` (`racebikes.py`)

`python dashboard.py --serve` also serves **`/racefietsen`**: every road bike
in `koopjes.db` (category racefietsen, whichever search found it:
`racefietsen`, `giant-defy`, `ultegra-6700`) on one live page, to decide
quickly whether a bike is worth it. The per-round report
(`racefiets_report.html`) stays as it is; it has no buttons and only shows
that one round. Active here means: not gone and seen within 8 days of the
newest road bike — wider than the computers' 3 days, because by day only
the newest pages come by and an older bike is only seen again by the Sunday
round (`week`).

Each bike is a card with three photos (all the search results give), price
and kind of price, distance, the specs on one line (size, material,
groupset, brakes, year, wheels, weight, condition), the seller's text
(*beschrijving*, the full text where `--detail-lookup` fetched it) and two
verdicts side by side:

- **flip** — expected selling price minus what it costs you, from the
  other listings of **the same bike model** (`bike_identity.py`), every road
  bike of the last 180 days, gone ones included. See *Bike models* below for
  what a model is and how the comparison steps down when there are too few.
  Within the chosen step: when at least 3 of them **sold fast** — gone within
  7 days of first being seen, or reserved and then gone — the estimate is the
  median of their last price, without a negotiation factor (it is roughly
  what was paid; the real price isn't known, the card says so). Otherwise
  the median of all asking prices × 0,875, with "(nog geen snelle
  verkopen)". Gone is only established after a complete crawl (the Sunday
  round `week`, see *Everything in a category*), so the first weeks there are
  few fast sales. The card says what the bike hangs on and how it compares,
  e.g. *Trek Domane SL6 · 6 snel verkocht (≤7 d), mediaan €620 · 14 te koop,
  mediaan €690 — deze €480 (−23% t.o.v. de schatting)*; *vergeleken met N
  fietsen* lists the fast sales and the cheapest others, with links. No
  model, no estimate ("model niet herkend", "te weinig vergelijkbare
  fietsen") — never a median of all road bikes (the owner, 30-09-2026: a 2024
  carbon bike is not comparable to a 2014 one). No costs are subtracted:
  parts and travel you work out per bike on `/flips`.
- **upgrade** — `upgrade.find_upgrades()` against your own bike in
  `mijn_fiets.md`, exactly as the report's Upgrade tab: better than yours by
  more than the margin, within budget, size not wrong. A bike without a
  known year is never a green upgrade: the score has no age to discount
  then, so an old bike with good parts looked new ("bouwjaar onbekend — vraag
  het jaar na"). Without a readable `mijn_fiets.md` the page says why there
  is no verdict.

Plus the **waardescore** (estimated value / price). Not the dealscore: that
belongs to the report.

### Dossier for Claude — `dossier.py`

The card shows part of what is known about a bike. The **dossier** button
next to *controleer* (key **d**) gathers all of it as one Markdown text to
paste into a conversation with Claude, with the questions on top: is it a
good deal (as a flip and as an upgrade), what needs replacing and roughly
what that costs (with sources, no made-up prices), an analysis of the
comparables, and what to ask the seller. Like controleer it first fetches
the listing page — one request per click, the same rules (`recheck.py`) —
and stores what controleer stores, plus what a round stores when it fetches
a listing page: the full description (`details_fetched_at`, as the year
lookup does), the frame height from the *Kenmerken* when the search results
had none, and material and brakes from the *Kenmerken* where the search
results said nothing (`spec`, source `marktplaats`) — without those a fetched
page would never be fetched again by a round, and a bike without a size in
the search results would stay "maat onbekend". So the estimate and upgrade
verdict in the dossier (and on the card after it) already use them. The
page also gives every photo (the search results give three; here the
largest size the page lists), the rest of the *Kenmerken*, private seller or
not and how long on Marktplaats, whether shipping is possible, and the bids
with their dates; those go into the dossier only, not into the database.
The seller's and bidders' names don't go in at all. If fetching fails (no connection, gone, page structure
changed) the dossier still comes, from the database, and says so on top.

What it holds: the listing (price with what kind of price it is, the asking
price only where it is certain — from the page just fetched, or a price
without bidding; a minimum bid or running bid is never called an asking
price — bids, reserved, place and distance, condition, size, days online,
price history, views and saves; times on your own clock), the
*Kenmerken* and what the finder read from the text, the description, the
photo links, which bike it is (model and where that came from, year,
material, groupset, brakes), the estimate exactly as on the card (resale,
step, median, fast sales, flip, waardescore, negotiation factor), the
upgrade verdict with the quality score per part next to your own bike, the
table you filled in `mijn_fiets.md` with your size and budget, your mark,
note and bids, the part prices from your own flips (`/flips`, kind
*onderdeel*: what you paid or estimated), and the **comparables**: a summary
(spread, fast sold, still for sale, per year; over all of them) and a CSV
with every bike of the estimate's step plus the rest of the same model and
model family (all years, all materials; `in_schatting`, `relatie`), at most
300: when there are more, first every fast sale of the estimate, then the
rest shared over the groups in proportion (each at least one where there is
room), each group spread evenly over its prices (not just the cheapest),
each with
price, year, material, groupset, speeds, brakes, size, condition, first and
last seen, gone, days online, reserved, sold fast and link. It computes
nothing new; it only puts more side by side.

The page copies it to the clipboard and shows it in a window with *kopieer*
and *bewaar als .md*. The same from the command line:

```bash
python dossier.py m2449549680                 # from the database, no request
python dossier.py m2449549680 --ophalen --uit dossier.md   # fetch the page first, write a UTF-8 file
```

### Bike models

Every bike hangs on a **model**: brand + model + *uitvoering* (variant), e.g.
"Trek Domane SL6", "Giant Defy Advanced 2", "Canyon Aeroad CF SLX 8". Where
it comes from, first match wins:

1. **your own link** (`bike_link`, migration 19), set on the card;
2. a **rule** you applied (see *Rules* below);
3. a **reference model** from `reference_bikes.csv` whose pattern matches —
   unless the title says more: some reference models cover a whole line
   ("Trek Domane", "Giant Defy (overig)"), and then "Trek Domane SL6" from
   the title is the model; a more precise reference model ("Giant Defy
   Composite 1") stays;
4. brand + model + variant from the title: the brand as the sleepers know
   it, the model word from `reference_bike_catalog.csv` or the word after the
   brand ("Koga Kinsei"), and as variant the 1-3 words right after it that
   look like one (`sl`, `slr`, `al`, `cf`, `slx`, `advanced`, `pro`, `comp`,
   `sport`, `elite`, `expert`, `disc`, `team`, `ltd`, a one- or two-digit
   number, letters with a digit like `sl7`) — not "105" (groupset), not a
   year, and it stops at the first other word. A number with a unit after
   it ("28 inch", "56 cm"), a decimal from 20 up ("55.5") and a model-year
   code ("MY16") are sizes or years, not a variant; "2.0" counts as "2",
   `disc` always goes last and doesn't count towards the three words
   ("Advanced Disc 1" = "Advanced 1 Disc"), and "Tcr-team" is "TCR Team".

Models compare without spaces and without what is in brackets ("SL 6" =
"SL6", "Trek Émonda (overig)" = "Trek Emonda"). The year comes from the text
or the title, or from your own link, which goes first — also for the
upgrade verdict, so the age discount counts.

The comparison wants **at least 5** listings per step and otherwise goes one
step coarser; the card says which step:

1. same model + variant, year ±2 (both known) — *model, ±2 jaar*
2. same model + variant where one of the two has no year, plus those of 1 — *model*
3. same brand + model (any variant), same material, year ±2 — *modelfamilie, ±2 jaar*
4. same brand + model, same material, same era when a year is missing (disc
   or rim, electronic or not, speeds when both say) — *modelfamilie, zelfde tijdperk*
5. any model, same material, groupset tier and brakes, year ±2 — *zelfde opbouw, ±2 jaar*
6. only when the bike itself says neither year nor brakes: same brand +
   model of any year — *onzeker*, with the range, never green.

When no step has 5, the ladder runs again with 3 and the step gets
*(weinig)*. The ±2 years is the generation; no generation years are looked
up or invented (CLAUDE.md).

**Correcting, on the card**, under *gekoppeld aan …*:

- **klopt** — the model is right: it becomes one of your models
  (`bike_model`) and the link is marked checked (*✓ gecontroleerd*);
- **ander model** (key **m**) — a search field and a scrolling list of all
  models with how many listings hang on each; pick one to link, or type a
  new one ("merk model uitvoering", e.g. "Koga Kinsei Pro": 3-80 characters,
  brand plus at least one word) to create and link it;
- **bouwjaar** — your year (1970 to next year), empty to remove it;
- **ontkoppelen** — back to what the listing says.

A correction recomputes only that bike (about 0,1 s, also with 14.000 bikes);
the comparison of the other bikes of the old and new model is updated after
the next round, the message says so.

**Rules.** When you link 3 listings that were recognised as the same model
("Trek Domane") to the same model of yours ("Trek Domane AL 2"), the view
**Modellen** proposes a rule at the top — "advertenties die als *Trek
Domane* herkend worden → *Trek Domane AL 2*?" — and the button says
*Modellen (1 voorstel)*. **toepassen** makes it work for every listing
recognised that way, gone ones included (`bike_rule`, migration 20; the card
says *eigen model via een regel*); **nee** is remembered, so it isn't asked
again. Your own link on a single listing still goes before a rule. Applied
rules are listed under the proposals, each with **weghalen**. *klopt* on the
recognised model is not a correction and never makes a proposal.

**The year for the likely bargains.** The year is rarely in the title (about
6 in 100), and without it a bike stays on a coarse step. After the searches,
the `overdag` and `nacht` rounds (`"year_budget": 20` in `schedule.json`)
fetch the listing page of at most 20 road bikes that are active, have a
price, are not reserved or put away, don't have a known year, look cheap —
at least 15% below the estimate of their step, or below the median on the
*onzeker* step — and whose page was never fetched before; cheapest first,
with the usual 1,5 s between requests, stopping at a 403. The full
description is stored (the same column `--detail-lookup` fills), and
`/racefietsen` and the upgrade verdict read the year from it after the next
round. So is what a round keeps from a listing page: the frame height from
the *Kenmerken* when the search results had none, and material and brakes
where they said nothing — a fetched page is never fetched again, so without
that a bike without a size in the search results stayed "maat onbekend". The views and saves on the page are stored too (see *Views and
saves*). By hand: `python racebikes.py plan 20` shows which bikes it would
be, `python racebikes.py jaar 20` fetches them (at most 20).

**Onderdelen** (view): spare parts for your flips. Loose parts the rounds come
across anyway, by kind — cassettes, chains, saddles, pedals, tyres, inner
tubes, wheels, chainrings/cranks, derailleurs, shifters, brakes, groupsets,
bars/stems, seatposts, bar tape, bottle cages (`spares.KINDS`). Switch on the
kinds you want spares of (stored in `koopjes.db`, table `setting`; at first
cassettes, chains, saddles and pedals); per kind the cheapest that are for
sale now (at most 40), with photo, price, place, distance, and favourite /
put away / your bid as for the bikes. A kind counts when the title names it
("zadel", not "zadelpen"); outside the category fietsonderdelen a title that
is a whole bike ("racefiets", "maat 56") doesn't count, and neither does a
wanted ad, a tool named right after the part ("cassette sleutel",
"kettingzweep"; "cassette met afnemer" is still a cassette), a mount
("houder voor stuur") or shoes. **No search was added** (the owner's choice, 02-10-2026): the
parts come from what the rounds find anyway — between the road bikes, the
`category: alle` searches (giant-defy) and the powermeter search — so there
are few. For more, add a search in the category `fietsonderdelen` to
`schedule.json` (a night slot with `pages: 2` is ~2 requests per search per
night); that is more requests to Marktplaats, so weigh it first.

**Modellen** (view) is the list of all models: your own (also without
listings), the reference models and the recognised ones, with *te koop*,
*gekoppeld* (180 days, gone ones included), *snel verkocht*, the median of
the fast sales, the median asking price and the lowest price for sale. A
search field, click a column to sort, drawn 200 rows at a time as you
scroll, and a field to **add a new model**. Click a model to see its bikes.

Views: **Te beoordelen** (no mark, no bid, not bought, not reserved — mark a
bike and it leaves this view, so you work down the list), **Favorieten**,
**Mijn biedingen** (with bids on bikes that are gone below), **Mijn flips**
(your own bikes from `/flips`: stage, bought for, what's in it, target price,
profit — expected at the middle of the target for a running one; editing is
on `/flips`), **Alle** (without the ones you put away), **Weggezet**,
**Modellen**, **Onderdelen** (above) and **Patronen** (views and saves of road
bikes, see below). Filters: search (title, specs, place, your
note), order (newest, best flip, best waardescore, best upgrade, nearest,
cheapest), frame size (default your size ± 2 cm, with *maat onbekend* on),
maximum price, maximum distance, *gereserveerd*, *alleen nieuw*. The page
remembers your view and filters (per browser).

Keys: **j**/**↓** next, **k**/**↑** previous, **f** favourite, **w** not worth
it, **1**-**6** put away with a reason, **u** put back (the bike under the cursor;
if that has no mark — in Te beoordelen a marked bike leaves the list at once —
it undoes your last marking and puts that bike back), **b** enter a bid,
**n** note, **space** description, **o** open on Marktplaats, **c**
controleer, **d** dossier for Claude (below *Plus the waardescore*), **m**
another model, **Esc** out of a field. The reasons to put a bike away are *niet
waard*, *gereserveerd*, *niet doorverkoopbaar*, *te hoge vraagprijs*,
*slechte staat* and *geen racefiets* (`marks.BIKE_REASONS`), stored in
`listing_mark` like the computers' marks, so you can look back later at
which bikes you dismissed and why. As there, a bike you put away comes back
when its price drops below the price at that moment — except *geen
racefiets*: a frame or an e-bike doesn't become a road bike by getting
cheaper.

Fast on purpose: the heavy part (comparables, upgrade scores) is computed
once per round and kept by the server; the page gets the bikes as JSON and
draws 40 cards at a time, more as you scroll; a click sends back only that
one bike. Measured on a test database with 2000 bikes (Chromium): the page
loads in about half a second, putting a bike away takes ~150 ms. With models
(01-10-2026): 2000 bikes, page ~1,2 s on the first load (the computation,
0,8 s) and a model correction 80-110 ms; 14.000 bikes, the computation ~5,6
s once per round and a correction 110-150 ms.
