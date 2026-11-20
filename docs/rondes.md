# Automatische rondes — `koopjes.py` en `schedule.json`

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
python koopjes.py status            # klopt schedule.json, wanneer draaide elke zoekopdracht
python koopjes.py run overdag       # één ronde, precies zoals de planner hem start
python koopjes.py schedule          # regels voor de Taakplanner (Windows) / cron, paden ingevuld
python koopjes.py lists             # lijsten/beste_koopjes.txt en lijsten/zonder_referentie.txt
python koopjes.py dashboard         # dashboard.html en dashboard_horloges.html opnieuw, zonder ronde
```

Plak eenmalig wat `schedule` print in een opdrachtprompt (Windows) of
`crontab -e` (macOS/Linux), en de rondes draaien vanzelf. Een ronde starten
kan ook met de knoppen onder *Rondes* op `/start` (zie
[live.md](live.md)).

`schedule.json` beschrijft elke zoekopdracht (een query met filters) en de
tijdsloten waarin ze draaien. Het is de enige plek om ze te veranderen.

## Wat een ronde doet

1. **Een slot nemen.** Begint een ronde terwijl er nog een loopt, dan wordt
   hij overgeslagen: Marktplaats krijgt nooit twee crawls tegelijk.
2. **De zoekopdrachten in de watchlist-tabel zetten** (zie "Watchlists" in
   [zoeken.md](zoeken.md)), zodat `schedule.json` de enige bron blijft.
3. **`racefiets_jev.py` draaien**, één keer voor alle zoekopdrachten van het
   slot, met de `pages`, `sort` en `bid_lookup` van het slot — en nog een keer
   met `--no-html` voor de zoekopdrachten met `"report": false` (zie onder).
   Een zoekopdracht met een eigen `"bid_lookup"` gaat voor die van het slot
   (de sporthorloges hebben `"fast"`, ook overdag; zie
   [horloges.md](horloges.md)) en draait dan in een eigen aanroep.
4. **Opzoeken met een budget.** Met `"year_budget"`: `racebikes.py jaar
   <budget>` — hooguit zoveel advertentiepagina's om het bouwjaar te vinden
   van racefietsen die goedkoop lijken maar hun jaar niet noemen (zie
   [racefietsen.md](racefietsen.md)). Met `"views_budget"`: `views.py meet
   <budget>` — hooguit zoveel pagina's om weergaven en likes te meten (zie
   "Weergaven en likes" in [live.md](live.md)). Met `"valuation":
   true`: `valuation.py`, zodat de taxatiegeschiedenis vanzelf groeit.
5. **`overzicht.html` opnieuw**: per zoekopdracht de laatste run, hoeveel
   advertenties nieuw / beter dan je referentie / topdeal / goedkoper dan
   eerder zijn, de nieuwe die het bekijken waard zijn, de nieuwe **slapers**
   van deze run met hun eerste foto (zie "Slapers" in
   [rapport.md](rapport.md)), een link naar elk rapport, de laatste taxatie
   van je eigen fiets en het schema.
6. **`dashboard.html` en `dashboard_horloges.html` opnieuw**: alle
   fietscomputers resp. sporthorloges op Marktplaats (zie
   [fietscomputers.md](fietscomputers.md) en [horloges.md](horloges.md)). Het overzicht linkt naar beide, en elk
   dashboard naar het andere. Een nieuwe flip komt in het logboek ("Nieuwe
   flip: …" of "Nieuwe flip (horloges): …") en opent, in een slot met
   `"open_browser": "auto"`, het dashboard waar hij op staat.

Na elke ronde worden twee tekstlijsten in `lijsten/` herschreven, bedoeld om
in een gesprek te plakken:

- `beste_koopjes.txt`: per zoekopdracht de upgradekandidaten en de hoogste
  dealscores, elk met URL en de redenen achter de score. Lopende biedingen
  staan er niet in: hun prijs is alleen het bod tot nu toe.
- `zonder_referentie.txt`: complete racefietsen van de laatste 14 dagen die
  geen rij in `reference_bikes.csv` herkent, gegroepeerd op merk en eerste
  modelwoord, vaakste eerst — de gaten in het referentiebestand.

## Logboeken

- Alles wat een ronde print gaat naar `logs/koopjes.log`. Relatieve paden in
  `schedule.json` gaan uit van dat bestand, dus het maakt niet uit vanuit
  welke map de planner de ronde start.
- Elke ronde, hoe hij ook afloopt, laat één regel achter in
  `logs/rondes.jsonl` (slot, starttijd, `ok`/`fout`/`overgeslagen`, aantal
  nieuwe advertenties; een ander pad via `"rounds"` onder `files`). Het
  overzicht toont de laatste 12 onder **Laatste rondes**, `python koopjes.py
  status` de laatste 3: zo zie je of de geplande rondes echt draaiden en
  Marktplaats bereikten.

## De tijdsloten

Het meegeleverde `schedule.json` volgt een meting aan Marktplaats zelf
(september 2026, categorie racefietsen): 400-500 nieuwe advertenties per dag,
vrij gelijkmatig verdeeld over 09:00-22:00 met 25-30 per uur, weinig 's nachts.

| Slot | Wanneer | Wat |
| --- | --- | --- |
| `overdag` | 08:30, 13:30, 19:30 | racefietsen (elke maat en prijs sinds 30-09-2026; `/racefietsen` filtert), nieuwste eerst, 8 pagina's — tussen twee runs komen er 150-180 bij, 8 pagina's laat ruimte. Met de categorie ingesteld geeft "racefiets" de hele categorie (12780 resultaten met de query, 12780 zonder, 23-09-2026), dus ook een advertentie die alleen "fiets" of "Cannondale CAAD10" heet |
| `nacht` | 03:00 | volledige crawls van "giant defy", "giant defy composite" (beide in elke categorie, zie `/fiets` in [eigen-fiets.md](eigen-fiets.md)) en "ultegra 6700" (vergelijkingsmateriaal voor je eigen fiets, en volledig, zodat verkochte advertenties meetellen), de zoekopdrachten powermeter en fietscomputer, alle Garmin-, Polar-, Suunto- en Coros-horloges (`sporthorloges`, `polar`, `suunto`, `coros`: ~71 pagina's, plus een biedopvraging voor elk van de ~370 "bieden"-advertenties zonder prijs), daarna `valuation.py` |
| `computers` | 10:00, 14:00, 18:00, 22:00 | alleen de nieuwste fietscomputers en Garmin-horloges, 2 pagina's elk (3 verzoeken per zoekopdracht, 6 per ronde), zodat een goedkope flip niet op de nacht wacht. Polar, Suunto en Coros alleen 's nachts: met ~5 nieuwe per dag zou 2 pagina's elke ronde dezelfde advertenties en biedingen ophalen. Horloges: ~115 nieuwe op een maandag tot 20:45 (28-09-2026), dus 2 pagina's per 4 uur volstaat. De hele categorie fietscomputers krijgt ~100-120 nieuwe per dag, ongeveer een kwart een computer met bekend model (gemeten 28-09-2026: om 18:40 vulde "Vandaag" 3-4 pagina's nieuwste eerst, "Gisteren" ongeveer 4) — ruimte genoeg, ook voor de ~7 betaalde "Dagtoppers" die Marktplaats bovenaan pagina 1 zet, welke sortering ook. Voor de fietscomputers kostte `bid_lookup` `fast` 17 extra opvragingen per ronde, dus het slot heeft `none`: een biedende fietscomputer staat overdag onder "Zonder prijs — bied maximaal", en de nachtronde vult het lopende bod in. De Garmin-horloges hebben hun eigen `"bid_lookup": "fast"` (~15 opvragingen per ronde). Een opgevraagd bod blijft in de database tot de volgende opvraging (migratie 11). Omdat het slot ondiep is, markeert het nooit iets als verdwenen: dat doet de nachtronde |
| `week` | zondag 05:00 | elke racefiets, volledig, zonder biedopvragingen: met `"split": true` draait de zoekopdracht in delen die elk onder Marktplaats' ~5000 blijven (zie `--split` in [zoeken.md](zoeken.md)). ~250 verzoeken van 100 advertenties, bewust langzaam (minstens 4 s ertussen, elke 40 een minuut pauze), ~30 minuten |
| `defy` | met de hand (`python koopjes.py run defy`) | elke Giant Defy in één keer — `giant-defy` en `giant-defy-composite`, volledig, in elke categorie, met biedopvragingen (~7 pagina's, een paar minuten) — daarna `valuation.py` en beide dashboards. Voor `/fiets` nu in plaats van na de nachtronde, die elke nacht hetzelfde doet. `schedule` laat hem weg, `status` toont "handmatig" |
| `horloges` | met de hand (`python koopjes.py run horloges`) | alle sporthorloges in één keer — `sporthorloges`, `polar`, `suunto` en `coros`, volledig, met biedopvragingen (~71 pagina's plus ~400 opvragingen, 15-20 minuten) — daarna beide dashboards; `dashboard_horloges.html` opent bij een nieuwe flip. `schedule` laat hem weg, `status` toont "handmatig" |

## `schedule.json` aanpassen

Verander de filters van een zoekopdracht (een `max_price` voor je budget
bijvoorbeeld) en de tijden; `python koopjes.py status` zegt meteen of er iets
niet klopt.

- **Zoekopdrachten** nemen dezelfde filters als een watchlist, plus
  `"report": false` voor een zoekopdracht die alleen in de database hoeft. De
  fietscomputers hebben dat: vroeger 17 merken met 17 losse rapporten
  (`racefiets_report_garmin-edge.html`, …); nu staat alles op het dashboard en
  worden die bestanden niet meer geschreven (oude mogen weg).
- **Slots** nemen `searches`, `pages` (0 = alles), `sort`, `bid_lookup`,
  `times` (`"HH:MM"` of `"zo HH:MM"`, Nederlandse dagafkortingen),
  `valuation`, `open_browser` en een `note` (die wordt genegeerd), plus:
  - `views_budget` (0-200, standaard 0): advertentiepagina's die de ronde mag
    ophalen om weergaven en likes te meten. Meegeleverd: 40 's nachts, 15 per
    `overdag`-ronde, 10 per `computers`-ronde, ~125 verzoeken per dag.
  - `year_budget` (0-20, standaard 0): advertentiepagina's om het bouwjaar
    van goedkope racefietsen te vinden. Meegeleverd: 20 in `overdag` en
    `nacht`, hooguit ~80 verzoeken per dag, minder zodra de goedkope gedaan
    zijn.
- **`open_browser` `auto`**: `overzicht.html` opent als een zoekopdracht *met*
  rapport nieuwe advertenties vond, en `dashboard.html` als de ronde een
  nieuwe **flip** vond — een fietscomputer die deze ronde voor het eerst
  gezien is, onder zijn verwachte verkoopprijs na verzending, niet door jou
  gekocht en niet gereserveerd. Het logboek noemt hem (`Nieuwe flip: €25
  winst — Garmin Edge 530 voor €90 — https://...`). Een nieuwe advertentie in
  een zoekopdracht zonder rapport opent niets: in de categorie
  fietscomputers is dat meestal een e-bike-display.

## Waren de pagina's genoeg?

Een ondiepe ronde, nieuwste eerst, ziet zelf wanneer zijn pagina's niet
genoeg waren: waren de onderste 5 advertenties van zijn laatste pagina
allemaal nieuw, dan is de vorige ronde niet gehaald en staan er misschien
nieuwe voorbij die pagina. Alleen advertenties die door de filters van de
zoekopdracht komen tellen: een buiten de prijs- of maatgrenzen komt nooit in
de geschiedenis en zou elke keer nieuw lijken. Het logboek zegt dan `let op:
de onderste 5 advertenties op pagina 2 waren allemaal nieuw` — verhoog
`pages`, of draai het slot vaker. (De onderste 5 en niet de hele pagina,
omdat pagina 1 met de Dagtoppers begint, en die zijn meestal oud.)
