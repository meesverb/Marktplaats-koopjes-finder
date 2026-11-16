# Automatische rondes — `koopjes.py` en `schedule.json`

[← README](../README.md) · [alle naslag](README.md)

Hoe de zoekopdrachten vanzelf draaien: tijdsloten, wat een ronde doet, het overzicht en de logboeken.

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
2. writes the searches into the watchlist table (see "Watchlists" in [zoeken.md](zoeken.md)), so
   `schedule.json` stays the one place to change them;
3. runs `racefiets_jev.py` once for all the slot's searches, with the slot's
   `pages`, `sort` and `bid_lookup` — and once more, with `--no-html`, for
   the searches marked `"report": false` (see below). A search can have its
   own `"bid_lookup"`, which goes before the slot's (the sport watches use
   `"fast"`, also by day, see "Sport watches" in [dashboards.md](dashboards.md)); it then runs in a call of its own;
4. with a `"year_budget"`, runs `racebikes.py jaar <budget>`: at most that
   many listing pages to find the year of road bikes that look cheap but
   don't say their year (see [racefietsen.md](racefietsen.md)); with a `"views_budget"`,
   runs `views.py meet <budget>`: at most that many listing pages to measure
   views and saves (see "Views and saves" in [dashboards.md](dashboards.md));
   with `"valuation": true`, runs `valuation.py`, so the valuation history
   builds up by itself;
5. rebuilds **`overzicht.html`**: per search the latest run, how many listings
   are new / better than your reference / top deals / cheaper than before, the
   new listings most worth a look, this run's new **slapers** with their first
   photo (see "Slapers" in [rapport.md](rapport.md)), a link to each full report, the latest
   valuation of your own bike, and the schedule;
6. rebuilds **`dashboard.html`**, one page with every bike computer on
   Marktplaats (see [dashboards.md](dashboards.md)), and **`dashboard_horloges.html`**,
   the same for Garmin sport watches (see "Sport watches" in [dashboards.md](dashboards.md)). `overzicht.html`
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

Every round, whatever its outcome, also leaves one line in
`logs/rondes.jsonl` (slot, start time, `ok`/`fout`/`overgeslagen`, number of
new listings; another path via `"rounds"` under `files`). `overzicht.html`
shows the last 12 under **Laatste rondes** and `python koopjes.py status` the
last 3, so you can see whether the scheduled rounds actually ran and reached
Marktplaats.

The shipped `schedule.json` follows a measurement of Marktplaats itself
(September 2026, category racefietsen): 400-500 new listings a day, spread
fairly evenly over 09:00-22:00 at 25-30 an hour, few at night. So:

| Slot | When | What |
| --- | --- | --- |
| `overdag` | 08:30, 13:30, 19:30 | racefietsen (every size and price since 30-09-2026; `/racefietsen` filters), newest first, 8 pages — 150-180 arrive between two runs, 8 pages leaves room. With the category set, "racefiets" returns the whole category (12780 results with the query, 12780 without, 23-09-2026), so a listing titled just "fiets" or "Cannondale CAAD10" is in there too |
| `nacht` | 03:00 | complete crawls of "giant defy", "giant defy composite" (both in every category, see `/fiets` in [eigen-fiets.md](eigen-fiets.md)) and "ultegra 6700" (comps for your own bike, and complete, so sold listings are counted), the powermeter and bike computer searches, all Garmin, Polar, Suunto and Coros watches (`sporthorloges`, `polar`, `suunto`, `coros`: ~71 pages, plus a bid lookup for each of the ~370 "bieden" listings without a price), then `valuation.py` |
| `computers` | 10:00, 14:00, 18:00, 22:00 | the newest bike computers and Garmin watches only, 2 pages each (3 requests per search, 6 a round), so a cheap flip doesn't wait for the night. Polar, Suunto and Coros only run at night: with ~5 new listings a day, 2 pages would fetch the same listings and bids every round. Watches: ~115 new on a Monday until 20:45 (28-09-2026), so 2 pages every 4 hours is enough there too. The whole category gets about 100-120 new listings a day, roughly a quarter of them a computer with a known model (measured 28-09-2026: at 18:40 "Vandaag" filled 3-4 pages newest first, "Gisteren" about 4), so 2 pages every 4 hours leaves room — also for the ~7 paid "Dagtoppers" Marktplaats puts on top of page 1 whatever the sort. For the bike computers `bid_lookup` `fast` cost 17 bid lookups a round on top of that, so the slot has `none`: a bidding bike computer shows under "Zonder prijs — bied maximaal" by day, and the night round fills in the running bid. The Garmin watches override that with their own `"bid_lookup": "fast"` (~15 lookups a round). A looked-up bid stays in the database until the next lookup (migration 11), so a round without lookups no longer wipes it. Being shallow, it never marks anything as gone: that stays with the night round |
| `week` | Sunday 05:00 | every racefiets, complete, without bid lookups: with `"split": true` the search runs in parts that each stay under Marktplaats' ~5000 (see `--split` in [zoeken.md](zoeken.md)). ~250 requests of 100 listings, deliberately slow (at least 4 s apart, a minute's break every 40), ~30 minutes |
| `defy` | by hand (`python koopjes.py run defy`) | every Giant Defy at once — the `giant-defy` and `giant-defy-composite` searches, complete, in every category, with bid lookups (~7 pages, a few minutes) — then `valuation.py` and both dashboards. For `/fiets` now rather than after the night round, which does the same every night. `koopjes.py schedule` leaves it out, `status` shows it as "handmatig" |
| `horloges` | by hand (`python koopjes.py run horloges`) | all sport watches at once — the `sporthorloges`, `polar`, `suunto` and `coros` searches, complete, with bid lookups (~71 pages plus ~400 lookups, 15-20 minutes) — then both dashboards; `dashboard_horloges.html` opens if there's a new flip. The night round does the same every night; this slot is for looking now. `koopjes.py schedule` leaves it out, `status` shows it as "handmatig" |

Change the searches' filters (a `max_price` for your budget, say) and the
times in `schedule.json`; `python koopjes.py status` tells you straight away
if something in it is wrong. Searches accept the same filters as a watchlist,
plus `"report": false` for a search whose listings only need to be in the
database — the bike computer search has it: it used to query 17 brands,
which gave 17 separate reports (`racefiets_report_garmin-edge.html`, …); now
everything is on the dashboard, and those files are no longer written (old
ones can be deleted). Slots take `searches`, `pages` (0 = everything), `sort`, `bid_lookup`,
`times` (`"HH:MM"` or `"zo HH:MM"`, Dutch day abbreviations), `valuation`,
`views_budget` (0-200, default 0: listing pages the round may fetch to
measure views and saves; the shipped schedule has 40 at night, 15 per
`overdag` round and 10 per `computers` round, ~125 requests a day),
`year_budget` (0-20, default 0: listing pages the round may fetch to find
the year of cheap road bikes; the shipped schedule has 20 in `overdag` and
`nacht`, at most ~80 requests a day, fewer once the cheap ones are done) and
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
