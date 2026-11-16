# De dashboards — fietscomputers en sporthorloges

[← README](../README.md) · [alle naslag](README.md)

`dashboard.py`: de pagina's per markt (flips, upgrades, favorieten, eigen biedingen, marktprijzen, patronen), de live server `--serve` met de startpagina, en wat alle live pagina's delen: afstand, eigen biedingen, weergaven en likes.

## Fietscomputers — the dashboard (`dashboard.py`, `computers.py`)

**`dashboard.html`** is the one page for bike computers: everything the
`fietscomputer` search found, across all its brands and earlier rounds, built
from `koopjes.db`. `koopjes.py` rebuilds it after every round;
`python dashboard.py` (or `python koopjes.py dashboard`) does it by hand.
Active means: not disappeared, and seen within 3 days of the newest listing
in the category (`dashboard` in `computer_scoring.json`). Tabs:

| Tab | What |
| --- | --- |
| **Flips** | every computer below its expected selling price, biggest profit first; reserved listings are left out (they're in Alle computers, marked "gereserveerd"), and so are listings you put away yourself (below) until their price drops. Per listing: the profit, the band around it, what it costs and what kind of price that is (fixed price / asking price, bidding possible / current bid, still rising), the expected selling price with n, and a photo. Below that: listings without a price, with the **maximum bid** at which you still break even at the low estimate |
| **Te beoordelen** | Alle computers with **Toon** set to *te beoordelen*: no mark, no bid of yours, not bought, not reserved — mark one and it leaves this view, so you work down the list, as on `/racefietsen`. A tab button, not a second table: it opens Alle computers with that filter |
| **Favorieten** | the listings you marked ★ favoriet (below), with your note and the price when you marked them if it has changed since; below that, favourites that are no longer online ("verdwenen" or "laatst gezien") |
| **Mijn biedingen** | the bids you placed yourself on Marktplaats, running ones first (see "Your own bids" below), with the listing, or "verdwenen" when it's gone |
| **Mijn flips** | what you bought and sold yourself: realised profit, what's in stock and what it should bring now, average days to sell, how far the dashboard's estimate was off, and profit per month. Entered in the live version (below) |
| **Upgrades** | computers that do more than your own, with the points they add, the **net** cost (price minus what your own computer would sell for) and what you gain or give up ("plannen op het apparaat: volledig i.p.v. beperkt", "touch i.p.v. knoppen") |
| **Alle computers** | everything, including computers whose model isn't in the file ("model onbekend": Van Rysel GPS 500, Sigma BC 509, ...) — search box (also searches your notes), brand filter, "alleen nieuw", sortable columns (Afstand too, see "Distance"), **Max €**. **Toon** hides the listings you put away (the default); set it to *te beoordelen*, *favorieten*, *weggezet* (to put one back), *met notitie* or *alles* |
| **Weggezet** | Alle computers with **Toon** set to *weggezet*: what you put away, to put one back. Like Te beoordelen a tab button; the tab Alle computers itself sets Toon back to the default |
| **Marktprijzen** | per model: how many for sale, lowest and median asking price, how many sold fast (with their median; see "Sold fast first"), expected selling price, original price, score |
| **Vinted** | once you've read in a Vinted export (below; until then the tab says how, and which database it reads): Vinted listings you could buy and sell on Marktplaats at a profit — what you pay there (asking price + buyer protection + shipping) against the Marktplaats selling price — and per model the Vinted asking prices next to Marktplaats |
| **Patronen** | long-term patterns from everything the crawl ever saw, gone listings included (`patterns.py`): per model how long listings stay online, how many are gone within 14 days, the median asking price, the last price of the quick ones, and how often the price was lowered; the **measured haggling factor** (last price of listings gone within 14 days ÷ the model's median asking price, shown from 20 such listings — then you can put it in `computer_scoring.json` instead of the assumed 0,875); whether the listings that were flips at first sight went faster than the rest; the median asking price per month; and new listings per weekday. Gone is not sold (a listing can be withdrawn), and a listing is only marked gone by a complete nightly crawl, so this needs a few weeks of `python koopjes.py run nacht`. Gone listings that were reserved when a round last saw them are counted apart ("eerst gereserveerd"): those were almost certainly sold. Only reservations a round actually saw count, so it's a lower bound. The hour of posting isn't in the search results: Marktplaats only says "Vandaag"/"Gisteren". Below all that: **Weergaven en likes** (see "Views and saves") |
| **Uitgefilterd** | holders, cases, parts, broken ones and wanted ads, each with the reason, to check that no real computer ended up there |

Photos come from the search results (stored since database migration 6); a
listing from before that shows a grey square until the next round sees it.

**One address for everything — `python dashboard.py --serve`.** The browser
opens at `http://127.0.0.1:8765/start`: the latest round, what your flips
earned, your running bids, links to every live page (racefietsen
`/racefietsen`, fietscomputers `/`, sporthorloges `/horloges`, your own bike
`/fiets`, your flips `/flips`) and to the files the
rounds write — the overview, every `racefiets_report*.html`, the lists in
`lijsten/`, the `taxatie_*.md` notes and `logs/koopjes.log` — served under
`/bestanden/` with a bar back to the start page. Nothing else in the folder is
served (not `koopjes.db`, not `sheets.json`). A link in the overview to
`dashboard.html` or `dashboard_horloges.html` opens the live version. Every
live page has the same bar at the top. The server computes the heavy part of
the dashboards and `/racefietsen` ahead: right after it starts, and again
once a round has finished (the database stayed the same for a minute), so the
first visit after a round doesn't wait the few seconds that takes.

**On a phone** (narrower than 700 px; the server only listens on 127.0.0.1,
so this is the browser on the machine itself or a narrow window): the bar at
the top folds into one button with the page's name (☰), rows of tabs and
views scroll sideways instead of wrapping over four lines, buttons and
fields are at least 40 px high, and on `/racefietsen` the filters sit behind
**Filters ▾** next to the search box (the keyboard shortcuts are hidden: no
keyboard). The sticky bar there went from more than half the screen to
about 110 px.

**Starting rounds from the start page.** Under *Rondes* every slot from
`schedule.json` has a **starten** button, with what it searches, how deep and
when it last ran. It runs exactly what the task scheduler runs,
`python koopjes.py run <slot>`, as a separate background process (it keeps
going if you stop the server); the page shows the tail of `logs/koopjes.log`
while it runs and reloads when it's done. Never two at once (the lock of
`koopjes.py`), and to stay polite to Marktplaats a slot can only start again
30 minutes after its previous round, 6 hours for a slot that fetches
everything (`pages: 0`) — scheduled rounds count too (`launcher.py`).

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
and button sends a secret chosen at start-up, and the program checks where a
request comes from, so another website can't write into your database
through your browser.

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
it. Favoriet, weg and the note work **without reloading the page**: the
listing's badges and buttons change where you clicked, a listing you put away
leaves Flips and Upgrades, and the counts on the tabs follow (a message at
the bottom says what was saved). Only **terugzetten** of a flip rebuilds the
Flips tab, since that row wasn't on the page. Gekocht and controleer still
reload, and come back on the same tab, at the same place, with the same
search. Marks go into `koopjes.db`, table `listing_mark`
(migration 12, `marks.py`), one per listing; notes into table `listing_note`
(migration 15, which moves over the notes migration 13 kept on marks). Both
are your judgement, not a market observation, so a listing you put away
still counts as a comparable. The written `dashboard.html` shows the marks
and notes but has no buttons. Vinted listings and the Uitgefilterd tab have
no marks or notes (yet).

**Why it's fast.** The live server remembers the heavy part of each page
(comparable prices, flips, patterns) between two clicks, and only computes it
again once a round, controleer, a buy or sale or a Vinted import has changed
the database. And the buttons are plain buttons, not a form per listing: with
~2800 bike computers the page used to hold ~8000 forms, and a browser took
tens of seconds to load that — on every click, since every click reloaded
the page (measured in Chromium on 29-09-2026 on a database of that size:
29 s for the bike computer page and 13 s for the watch page, now 2.2 s and
1.4 s).

Since 30-09-2026 three more things (measured on a made-up database of two
months of rounds: ~36,000 listings, ~340,000 price observations):

- **Comparable prices once per build.** The flips, the stock in Mijn flips
  and Marktprijzen use the same comparable listings; they used to read and
  recognise them separately, and Marktprijzen did so again on every page
  view. Titles, groupsets and specs that were recognised once are
  remembered (the result depends on the text alone), so a rebuild after a
  round only looks at what is new. Serving the bike computer page went from
  1.5 s to 0.2 s, its first build after a round from 5 s to 1 s, and
  writing both dashboards after a round (`koopjes.py`) from 7 s to 1.8 s —
  with exactly the same pages as output.
- **Alle computers loads when you open it.** That tab is over half of the
  page (with its own buttons on every row), and the browser read it on
  every load while you usually look at Flips. The live page now fetches it
  from the server the first time you click the tab (the address
  `/paneel?markt=...&naam=alle`); the written `dashboard.html` still has
  everything. The page loads in about 1 s instead of 2.5-3.5 s (the watch
  page: 1.3 s instead of 3.4 s). A mark or note you set while the tab is
  loading is put on it once it's there, and after controleer it comes back
  with the same search and place.
- **Typing in the search box** filters once you pause (0.15 s), instead of
  going through every row on each key.

**Checking a listing now — controleer.** The dashboard shows what the last
round saw, and that can be hours old: by day the `computers` slot only looks
at the newest 2 pages, so a listing from last week only comes by again in
the night round. A listing reserved at 11:00 stays on Flips until then. And
the bids on a listing with an asking price (`MIN_BID`, "vraagprijs, bieden
kan") are only on the listing page itself, which the watch searches don't
fetch (`bid_lookup` `fast`): a Suunto asking €290 with €350 already bid on it
counted as a flip at €290. So every listing in the live version has a
**controleer** button next to favoriet/weg. It fetches that one listing page
from Marktplaats — one request per click, never two at once, and at least
1.5 s apart like a round's `--delay` — and stores what it says (`recheck.py`):
reserved or not (a reserved one leaves Flips; one no longer reserved comes
back), the bids (count, highest, minimum — the same rules as the round's bid
lookup, so a bid above the asking price becomes the price and reads "huidig
bod, loopt nog op"), the current price, and whether the listing still exists
(Marktplaats answers 410 for one that's gone; it's then marked gone, as the
night round would have done). The message at the top says what it found, e.g.
"4 biedingen, hoogste €350, boven de vraagprijs van €290; prijs €290 → €350",
and the listing shows "gecontroleerd dd-mm-yyyy HH:MM". It never bids or
replies. If the page can't be read (no connection, or Marktplaats changed its
page structure) the message says so and nothing is stored. The check leaves
`last_seen` alone — that stays the last round, which is what "laatste ronde"
and "nieuw" go by — and stores the highest bid and the time of the check in
`listing.bid_high` and `listing.checked_at` (migration 14). The round's own
bid lookup fills `bid_high` too, and a bid above the asking price counts until
the next lookup, even when a round without lookups sees the asking price
again.

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

**Sold fast first** (since 02-10-2026, as on `/racefietsen`): when at least 3
of those listings **sold fast** — gone within 7 days of first being seen, or
reserved and then gone (`computers.is_fast_sold()`) — the selling price is the
median of *their* last asking price, without the 0,875: that is roughly what
was paid, though what was actually paid you never know. The band is their
quartiles. With fewer, it's the asking prices × 0,875 as above, and the line
under the selling price says so ("nog maar 2 snel verkocht"). The same rule
holds for both dashboards (bike computers and watches), for the stock in Mijn
flips, for Marktprijzen (column **Snel verkocht**: how many, and their median)
and for the Marktplaats selling price on the Vinted tab. Gone is not sold, and
a listing is only marked gone by a complete night round, so it takes a few
weeks of `python koopjes.py run nacht` before models have 3.

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
model; S: 1"; "4 snel verkocht" instead of n= when the fast ones set the price), and Marktprijzen lists the variants on sale per model with
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
python dashboard.py --serve        # everything live from http://127.0.0.1:8765/start (Ctrl+C to stop): dashboards, /fiets, /upgrade, /flips, reports
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

## Sport watches — `dashboard_horloges.html` (`markets.py`, `watches.py`)

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
  computers' — tabs Flips, Te beoordelen, Favorieten, Mijn biedingen, Mijn
  flips, Alle horloges, Weggezet, Marktprijzen, Patronen and Uitgefilterd — without Upgrades (there is no own watch to
  compare with), Vinted and the feature score. `koopjes.py` writes it after
  every round; `python dashboard.py --markt sporthorloges` (or `--markt alle`)
  by hand. `python dashboard.py --serve` shows it live at
  `http://127.0.0.1:8765/horloges`, with the same Gekocht/Verkocht,
  favoriet/weg and controleer buttons;
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

## The sport watch catalogue — `reference_sport_watches.csv`

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

## Distance — `distance.py`

Every live page (`/racefietsen`, `/`, `/horloges`) can show how far each
listing is from your postcode, as the crow flies, filter on it (a slider,
5-250 km, with *ook zonder plek* for listings without a place) and sort on
it (the **Afstand** column, *Dichtstbij eerst* on `/racefietsen`). Enter the
postcode on the page (`3511` or `3511AB`); it is stored in `koopjes.db`
(table `setting`, migration 18), not in a file in git. Clear the field to
remove it. Distance is not in any score.

How, without an outside service: the search results give every listing's
latitude and longitude (also without a postcode in the request; checked
29-09-2026), stored in `listing_place` from the next round on. Marktplaats
doesn't say where a postcode is, but a search *with* a postcode gives each
listing's distance to it in whole km; saving the postcode sends one search
request and finds the point those distances agree on (on 29-09-2026: 3511AB
within 0,3 km, a Groningen postcode within 0,5 km). A `distanceMeters` of 0
means unknown there (some shops) and is ignored. After that everything is
computed locally, so a new postcode applies to every listing at once.
Listings from before migration 18 get the place of other listings in the
same town until a round sees them again (shown as *ca.*); a seller who only
gave the country has no place.

## Your own bids — `own_bids.py`

Bidding happens on Marktplaats, by you; the script never bids. What you can
do on every live page is record it: **ik heb geboden** (under each listing
on the dashboards, the **b** key on `/racefietsen`) with the amount; the
date fills itself in. Every bid is kept (first €250, then €280), and the
latest one's status says where you stand: *open*, *overboden*, *afgewezen*,
*geaccepteerd* or *ingetrokken*, one click each. **Geaccepteerd** puts the
listing on `/flips` at once, stage *gekocht*, with your bid as the buying
price and, for a road bike, the flip estimate as target price (a computer or
watch goes under its own market). Accepting twice doesn't make a second
flip; setting another status afterwards leaves the flip, remove it on
`/flips` if the deal fell through. When the last bid lookup or controleer
saw a higher bid than yours, the listing says *er staat al €… op*. Stored in
`own_bid` (migration 18); the start page has a tile with your running bids.

## Views and saves — `views.py`

How many people looked at a listing and saved it ("bewaard", the heart) is
only on the listing's own page (`stats`: `viewCount`, `favoritedCount`, and
`since`, the moment it was placed), not in the search results. So every
measurement is one request, and it is done sparingly:

- **for free** where a round or controleer fetches the page anyway (bid
  lookups, `--detail-lookup`);
- **targeted**: your own ads on `/flips` that are *te koop* with a
  Marktplaats link, every 6 hours; favourites and listings with a running
  bid of yours, every 12 hours;
- **a sample**: a fixed 1 in 10 of the new listings in the three markets
  (road bikes, bike computers, sport watches), measured at 1, 3 and 7 days
  old. Fixed on the listing number, so the same listing is measured each
  time and you see how it grows.

Never more per round than the slot's `views_budget`, targeted first, with
the usual pause between requests; three failures in a row stop it. By hand:
`python views.py plan 20` shows what the next round would measure,
`python views.py meet 10` measures that many now. Stored in `listing_stats`
(one row per look, migration 18); a gone listing (410) is marked gone.

Where you see it: under every listing (*158× bekeken · 4× bewaard (+2
bewaard sinds …)*), on `/flips` for your own ad with the growth as two small
lines, and on the **Patronen** tabs: the median views and saves by age,
likes per day in the first days against the share gone within 7 days (gone
is not sold), and views per day by promotion (a *Dagtopper*, from the search
results), price, day and part of day of posting, and before/after a price
drop. Each group says its n; below 10 it is marked *te weinig*. This is
correlation, not cause: a seller who pays for a Dagtopper may also take
better photos.
