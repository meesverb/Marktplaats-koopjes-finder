# De eigen fiets — taxatie, kwaliteitsscore en upgrades

[← README](../README.md) · [alle naslag](README.md)

Wat de fiets uit `mijn_fiets.md` waard is (`valuation.py`, `/fiets`), hoe goed een fiets is los van de prijs (`scoring.py`), welke betere fiets daarvoor te koop staat (`upgrade.py`) en de upgradetest (`/upgrade`).

## `valuation.py` — what is my own bike worth?

The first thing that reads `koopjes.db` rather than writing to it. It values
the bike described in `mijn_fiets.md` against the listings the crawler has
collected, and writes the result to the `valuation` / `valuation_evidence`
tables (PLAN_FIETSWAARDE.md fase 3).

```bash
python racefiets_jev.py --query "giant defy" --pages 0 --sort newest --reference-file reference_bikes.csv   # collect comps first
python valuation.py --db koopjes.db
```

Three estimators, mixed into one band:

- **E1 — comparable listings.** For your own bike: exactly the listings you
  took along on the page `/fiets` (see below), with their asking price; five
  or more is a hard number, fewer is `indicatief`. Nothing taken along is no
  valuation. For anything else (and in the tests), a ladder with decreasing
  confidence: same
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
valuation, not a guess — take some along on `/fiets` first (exit code 2, and
the nightly round logs it as an outcome, not an error). The 10-15% negotiation
margin, the bundle factor and the share of an upgrade that a buyer of a
complete bike pays for are heuristics, not measurements, and each is printed
as its own line so it is clear what it contributed.

## Which listings your bike is compared with — `/fiets` (`bike_comps.py`)

"Giant Defy" is a model line, not a model: since 2009 Giant has sold
aluminium (Aluxx, Defy 0-5), entry-level carbon (Composite), Advanced,
Advanced Pro, Advanced SL and, from 2015, disc-brake bikes under that name,
and most sellers just write "Giant Defy carbon". No rule on title words tells
those apart as well as you do by looking, so you decide per listing.

```bash
python dashboard.py --serve        # then open http://127.0.0.1:8765/fiets
```

The page lists every listing of the last 180 days with the model family
from `mijn_fiets.md` ("defy") in its text, or found by a search with that word
in it ("giant defy", "giant defy composite"), including the ones that have
disappeared (sold or withdrawn — "weg sinds 12 sep, 9 dagen online"). The
search counts because the search results only carry the first 200
characters of a description, and Marktplaats finds Defys that never say
"defy" ("Giant racefiets maat L"); such a row says *gevonden door de
zoekopdracht*. Every category is in except parts and accessories
(`fietsonderdelen`, `fietsaccessoires-*`): a Defy under *heren
sportfietsen* or *omafietsen* says so ("in dames omafietsen"). Every frame
material is in too, since 29-09-2026: the material is shown, not used to
filter — from the reference model (`reference_bikes.csv`: Defy 0-5 and Aluxx
are aluminium, Composite and Advanced carbon), from the text, or *volgens de
verkoper* when only the seller's attributes say it (those can be wrong: a
Defy with "COMPOSITE" on its chainstay was listed as aluminium). A listing
that says nothing about its material is marked *materiaal onbekend*. Both
nightly Defy searches run with `category: alle` for this (see
`--category`). Per listing: **✓ meenemen** or **✗ niet**; clicking the chosen
button again puts it back to "te beoordelen". The page opens on **Te
beoordelen** (new or not looked at yet), so a chosen listing drops out of
view and you work down the list; the filter shows the others.

Only what you take along counts, with its asking price. A bid listing that
already has bids is shown with its highest bid but doesn't count (its price
is still going up); a "bieden vanaf" (MIN_BID) price does. At the top the
valuation of your bike with its original wheels (scenario B, as the report's
Mijn fiets tab computes it), n and confidence, updated with every click
without reloading; "Hoe dit bedrag ontstaat" shows the evidence lines. Until
you have taken along at least one listing with an asking price there is no
valuation, and the upgrade-finder uses `verkoopprijs_handmatig` from
`mijn_fiets.md`; below five it is `indicatief` and that manual price still
wins. The choices go into `koopjes.db`, table `comp_choice` (migration 16);
`valuation.py`, `upgrade.py`, the report's Mijn fiets and Upgrade tabs and
the overview all use them.

## `scoring.py` — how good is a bike, regardless of price?

The **quality score** from PLAN_FIETSWAARDE.md fase 4, and not to be confused
with the dealscore ([rapport.md](rapport.md)): that one says whether a price is good, this one says
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

Four keys in `scoring_config.json` belong to the upgrade test below and are
off by default, so without a saved rule everything scores as before:
`drivetrain.age_decay_per_year` / `age_decay_max` (age counts on the
drivetrain too: "Ultegra" is a 10-speed in 2010 and a 12-speed in 2022, and
the year is what a listing usually does say), `wheels.eigen_wielen` (a fixed
score for your own wheels; without it the CSC set scores as branded carbon,
because CSC is in the wheel-brand list), and `upgrade.marge` /
`upgrade.onbekend` (the margin, and whether an unknown part scores the fixed
neutral number or the same as your own bike). The rule you save on
`/upgrade` overrides the file for everything that scores bikes.

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

## `upgrade.py` — which better bike can I buy for that?

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
  it costs to get into a bid (see `RUIMTE` under "Bidding listings" in [zoeken.md](zoeken.md)). The asking price stays
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
counts as an upgrade; default: the margin of your rule on `/upgrade`, else 5),
`--query`, `--window-days`, `--limit`, `--config` for the scoring weights
(with your own file the saved rule is not applied), `--show-rejected`. With
the default config it uses the rule you saved on `/upgrade` and prints
"Jouw regel van /upgrade (opgeslagen …)".

With `component_price` still empty there are no observations of what a loose
wheelset sells for, so the two budgets come out equal and the output says so
rather than guessing a number. It also bids on nothing and contacts no seller:
that is out of scope, by design.

## The upgrade test — `/upgrade` (`upgrade_test.py`)

You decide what an upgrade is, and the score follows you instead of the
other way round. Open `http://127.0.0.1:8765/upgrade` in
`python dashboard.py --serve` ("Upgrade" in the bar at the top):

- **Test** — one bike at a time (photos, price, specs, description): "is
  this an upgrade of your bike — regardless of price and size?" Yes, no or
  unsure (keys `j`, `n`, `t`; `s` skips, `u` undoes). The rule's verdict only
  shows after you answer, with per part why, so it doesn't steer you (tick
  the box to see it first). The order spreads over the whole score range, so
  the bikes the score rates low come by too. Answers are stored in
  `koopjes.db` (`upgrade_label`, migration 22) and stay when a bike is sold.
- **Uitslag** — how many of your answers the rule gets right, and the bikes
  where you and the rule disagree, with the difference per part. Unsure
  doesn't count.
- **Jouw regel** — every knob of the quality score in one place: weights,
  margin, what "unknown" counts as, material and age, groupset levels,
  brakes, wheels (including a score for your own wheels), extras. Every
  change is recalculated at once on your answers and on the bikes for sale
  now; nothing is stored until **Opslaan**. **Zoek** tries weights (steps of
  0.1, then 0.05 around the best), the margin and a few options (unknown =
  like your bike, age on the drivetrain, a steeper frame age, your own wheels
  as unbranded carbon) and proposes the rule that gets most of your answers
  right; on a tie, the one that changes least. It needs at least 10 answers
  with 3 yes and 3 no, and says how far to trust it. **Terug naar de
  standaard** removes your rule.
- **Uitdraai** — every bike with its score per part, the difference with
  your bike, total, gain, whether it's better than yours and whether it's an
  upgrade on `/racefietsen` (size and budget too); sort, filter (for sale,
  judged, disagree, better, upgrade), change an answer per row, and
  **Alles als CSV** for Excel (semicolons, decimal commas).

A saved rule is kept in `setting` (`upgrade_regel`) and used by
`/racefietsen`, the report, the overview and `upgrade.py`;
`scoring_config.json` stays the default. "Better than your bike" on this
page is the quality question alone (gain above the margin); the upgrade
verdict on `/racefietsen` also needs the size and the budget.

```bash
python upgrade_test.py                  # how the rule does on your answers, in the console
python upgrade_test.py uitdraai         # every bike as CSV: lijsten/upgrade_uitdraai.csv (--uit for another path)
python upgrade_test.py zoek             # the rule that fits your answers best (stores nothing)
```
