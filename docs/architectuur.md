# Architectuur — welk bestand doet wat

[← README](../README.md) · [alle naslag](README.md)

Per bestand wat het doet, welke tabellen en migraties erbij horen en welke functies de ingang zijn. Dit is de lange versie van de kaart in `CLAUDE.md`; werk hem bij in dezelfde commit als de code.

## Het geheel in één beeld

```
Marktplaats ──► racefiets_jev.py ──► koopjes.db ──► dashboard.py --serve ──► browser (127.0.0.1)
  (zoekpagina's,    (crawlen, filteren,   (db.py:          /start  /  /horloges  /racefietsen
   advertentie-      scoren, rapport)      SQLite, WAL)     /fiets  /upgrade  /flips
   pagina's)              ▲                    ▲
                          │                    └── valuation.py, upgrade.py, vinted.py, flips_sheets.py
                   koopjes.py run <slot>           (lezen en schrijven hun eigen tabellen)
                   (schedule.json: wat, wanneer)
```

- **Twee plekken praten met Marktplaats**: `racefiets_jev.py` (de zoekpagina's van een ronde, plus de biedopvragingen en `--detail-lookup`) en `recheck.py` (één advertentiepagina per keer: de knop controleer, het dossier, en de opzoekingen met een budget van `views.py meet`, `racebikes.py jaar` en de postcode van `distance.py`). Nergens parallel, altijd met een pauze ertussen.
- **Wat alleen toont, kan niets veranderen**: pagina's lezen `koopjes.db` via `db.connect_readonly()`; alleen een ronde en een actie van de eigenaar openen hem met `db.connect()`.
- **De server schrijft alleen wat de eigenaar zelf invoert**: markeringen, notities, biedingen, aan- en verkopen, keuzes op `/fiets`, oordelen op `/upgrade`, alles op `/flips`.
- **Geen framework, geen build**: de HTML, CSS en JavaScript van de live pagina's staan als tekst in de Python-modules (`dashboard.py`, `racebikes.py`, `upgrade_test.py`, het overzicht in `koopjes.py`); alleen het rapport heeft een los sjabloon (`report_template.html`).
- **Imports lopen in een kring** (`racefiets_jev` ↔ `report` ↔ `upgrade` ↔ `upgrade_test` ↔ `dashboard` ↔ `racebikes` ↔ `koopjes`); dat werkt omdat een deel binnen functies importeert. Zie stap C1 in `VERBETERPLAN.md` voordat je een nieuwe import bovenaan een module zet.

## Crawlen en het rapport per zoekopdracht

Naslag: [zoeken.md](zoeken.md), [rapport.md](rapport.md), [rondes.md](rondes.md).

### `racefiets_jev.py`

Het hele script: crawlen, scoren, rapporteren.

### `report.py`

Rapportpanelen (fase 6): Biedpaneel, Upgrade, Mijn fiets, plus de waardescore-kolom; alleen lezen uit `koopjes.db`.

### `report_template.html`

HTML-sjabloon van het rapport (`string.Template`), wordt runtime ingelezen.

### `sleepers.py`

Slapers: advertenties waarvan titel en tekst niets over de fiets zeggen (geen merk, weinig tekst, haast, bieden zonder bod). Alleen uit de zoekresultaten; eigen tab in het rapport, los van dealscore en waardescore.

### `koopjes.py` + `schedule.json`

Automatische rondes: `schedule.json` beschrijft zoekopdrachten en tijdsloten, `koopjes.py run <slot>` draait er één (lock, log, bouwjaren opzoeken tot `year_budget` (max 20), weergaven/likes meten tot `views_budget`, `overzicht.html`), en elke ronde krijgt een regel in `logs/rondes.jsonl` (Laatste rondes in het overzicht, laatste 3 in `koopjes.py status`); `koopjes.py schedule` geeft de inplan-commando's.

### `launcher.py`

De knoppen onder Rondes op `/start`: `python koopjes.py run <slot>` als los achtergrondproces, nooit twee tegelijk (het slot van koopjes.py) en een wachttijd per slot sinds de vorige ronde (30 min, 6 uur bij `pages: 0`), zodat een knop de crawl-frequentie niet opvoert.

## Database en gedeelde hulpfuncties

Naslag: [database.md](database.md).

### `db.py`

SQLite-schema, migraties, import van de oude bestanden, CSV-export; sinds fase 1b aangesloten op het script (`--db`/`--no-db`). `connect()` opent en migreert (schrijven); `connect_readonly()` opent alleen-lezen zonder te migreren — elke pagina die alleen toont gebruikt die.

### `util.py`

Wat meer dan één module hetzelfde nodig had: `parse_time()` / `parse_time_utc()` (een ISO-tijd uit de database, zonder of mét gegarandeerde tijdzone), `parse_day()` (de lokale dag), `local_time()` (een tijd op de eigen klok) en `euro()` ("€1.250", "−€5"; `cents=True` "€11,95" voor /flips, `sign=True` "+€25", `none=` de tekst zonder bedrag) — elk bedrag op een pagina gaat hierdoor. Hangt van geen andere module af.

## De live server en de dashboards

Naslag: [dashboards.md](dashboards.md).

### `dashboard.py`

De dashboards per markt (`markets.py`): `dashboard.html` (fietscomputers: Flips / Upgrades / Te beoordelen / Favorieten / Mijn biedingen / Mijn flips / Alle computers / Weggezet / Marktprijzen / Vinted / Patronen / Uitgefilterd; Te beoordelen en Weggezet zijn knoppen die Alle met een filter openen, `view_tab_labels()`) en `dashboard_horloges.html` (sporthorloges: zonder Upgrades en Vinted), uit `koopjes.db`. `koopjes.py` bouwt beide na elke ronde; `--markt sporthorloges`/`alle` met de hand. Dezelfde pagina's live op `/` en `/horloges` via `server.py`. Favoriet/weg en notitie gaan zonder herladen (JSON, `live_update()`); de knoppen zijn geen `<form>` per advertentie (duizenden formulieren maakten de pagina traag), en live komt de tab Alle pas van de server als je hem opent (`LAZY_PANELS`, `/paneel`; het geschreven bestand heeft alles). `python dashboard.py --serve` start de server.

### `server.py`

De live server van `dashboard.py --serve`: één adres (127.0.0.1, met token) voor alles. `DashboardHandler` heeft de routes (GET per pagina; POST leest het formulier één keer en kiest de actie uit een tabel), `ACTIONS` de knoppen van de dashboards (gekocht, favoriet/weg, notitie, controleer, bieden, postcode, Mijn flips), en `LiveCache` onthoudt het zware deel tot een ronde de database verandert (één opbouw tegelijk per pagina; `keep_warm()` rekent na het starten en na elke ronde alvast vooruit). Schrijft alleen wat de eigenaar invoert: aan- en verkopen met hun markt, markeringen en notities (`marks.py`), eigen biedingen (`own_bids.py`), de postcode (`distance.py`), de keuzes op `/fiets`.

### `pages.py`

De gedeelde bouwstenen van elke live pagina: de paden (`START_PATH`, `RACEBIKES_PATH`, ...), de balk bovenaan (`site_nav()`), de gedeelde CSS en JavaScript, `act()` (een knop zonder `<form>`), tabellen en tegels, en het lezen van formulieren (`FormError`, `parse_euro()`, `parse_day()`). Importeert geen pagina, zodat de pagina's elkaar niet in een kring nodig hebben.

### `start_page.py`, `bike_page.py`, `flips_page.py`

De pagina's `/start` (met `/bestanden/`: de rapporten, het overzicht en `lijsten/`, alleen de patronen in `SERVED_FILES`, en de knoppen per ronde via `launcher.py`), `/fiets` (de vergelijkingslijst van `bike_comps.py`, meenemen of niet) en `/flips` (de HTML en de acties `FLIP_ACTIONS`; het rekenwerk staat in `flips.py`).

### `markets.py`

De markten naast elkaar: categorieën, referentiebestand, bestandsnaam, welke tabbladen, indeling van titels zonder model. `trade_market()` zegt bij welke markt een eigen aankoop hoort (migratie 10, `trade.market`).

### `computers.py` + `computer_scoring.json`

Fietscomputers: herkent het model in de titel tegen `reference_bike_computers.csv`, functiescore met de gewichten die de eigenaar koos, upgrade t.o.v. de eigen Roam v1 en flipmarge (per uitvoering als die er genoeg heeft: `title_variant()`, ook voor de horloges; vanaf 3 snel verkochte — ≤ 7 dagen weg of gereserveerd en weg, `is_fast_sold()` — hun mediaan zonder afdingfactor, zoals op /racefietsen, ook in `market_resale()`). `classify_title()` deelt elke titel in (computer, accessoire, onderdeel, defect, gevraagd); los van dealscore en waardescore. `python computers.py` toont de score per model.

### `watches.py`

Sporthorloges: de categorieën (sporthorloges, smartwatches, activity-trackers), de gevolgde merken (`BRAND_RE`: Garmin, Polar, Suunto, Coros) en `classify_unknown()` voor titels zonder bekend model (horloge met onbekend model, bandje, ander merk, geen horloge). `python watches.py` toont de markt en de flips in de console. Zoekopdracht `sporthorloges` ("garmin") in de nacht- en overdagronde, `polar`/`suunto`/`coros` alleen 's nachts, alle met biedopvragingen (`bid_lookup` fast; het bod blijft bewaard, migratie 11).

### `vinted.py`

Vinted-exports (een CSV die de eigenaar zelf maakt) inlezen in `koopjes.db` (tabellen `vinted_listing`/`vinted_price`, migratie 8) en naast Marktplaats zetten: tab Vinted in het dashboard, `python vinted.py` in de console. Haalt zelf niets op bij Vinted; Vinted-prijzen zijn nooit vergelijkingsprijs voor Marktplaats.

### `patterns.py`

Lange-termijnpatronen voor de tab Patronen: verkoopsnelheid per model, gemeten afdingfactor (snel verdwenen ÷ mediaan vraag, vanaf n=20), flips achteraf, prijs per maand, nieuw per weekdag. Verdwenen ≠ verkocht; alleen lezen.

### `marks.py`

Eigen markeringen per advertentie: favoriet, of weg (niet waard, gereserveerd) — tabel `listing_mark`, migratie 12 — en een eigen notitie bij elke advertentie, los van de markering — tabel `listing_note`, migratie 15 (de kolom `listing_mark.note` van migratie 13 is sindsdien leeg en ongebruikt). Gezet via `python dashboard.py --serve`; weg haalt een advertentie uit Flips/Upgrades/Zonder prijs tot de prijs onder die van het wegzetten zakt. Nooit invloed op vergelijkingsprijzen.

### `own_bids.py`

De biedingen die de eigenaar zelf op Marktplaats deed (tabel `own_bid`, migratie 18): elk bod bewaard, status van het laatste (open/overboden/afgewezen/geaccepteerd/ingetrokken); geaccepteerd zet hem meteen op `/flips`. Tab Mijn biedingen op elke pagina, tegel op `/start`. Het script biedt nooit zelf.

### `distance.py`

Afstand hemelsbreed tot de eigen postcode: plek per advertentie uit de zoekresultaten (`listing_place`, migratie 18), de postcode geplaatst met één zoekverzoek mét postcode (de afstanden terugrekenen), opgeslagen in `setting`. Schuifje + kolom Afstand op alle live pagina's; telt nergens in een score.

### `views.py`

Weergaven en likes (bewaard) van de advertentiepagina (`stats`), tabel `listing_stats`: meeliften op biedopvraging/controleer, gericht (eigen advertenties, favorieten, biedingen) en een vaste steekproef van 1 op 10 nieuwe op 1, 3 en 7 dagen, hooguit `views_budget` per ronde (`schedule.json`). Analyse in Patronen; verloop van je eigen advertentie op `/flips`. `python views.py plan/meet N`.

### `recheck.py`

De knop controleer in `dashboard.py --serve`: haalt één advertentiepagina op (één verzoek per klik, nooit twee tegelijk, minstens 1,5 s ertussen) en legt vast wat erop staat: gereserveerd, biedingen (zelfde regels als de ronde: `racefiets_jev.apply_bid_info()`), prijs, of verdwenen (410). Laat `last_seen` staan; schrijft `listing.checked_at` en `bid_high` (migratie 14). Nooit bieden of reageren.

### `trades.py`

Mijn flips: de eigen aan- en verkopen (tabel `trade`, migratie 7) en de voortgang daarvan. Invoeren via `python dashboard.py --serve` (lokaal, 127.0.0.1, met token); nooit een vergelijkingsprijs.

## Racefietsen

Naslag: [racefietsen.md](racefietsen.md).

### `racebikes.py`

`/racefietsen` in `dashboard.py --serve`: alle racefietsen uit `koopjes.db` (actief = gezien binnen 8 dagen) als kaarten met 3 foto's, specs, beschrijving, flip (verkoopschatting uit de fietsen van hetzelfde model: mediaan van ≥ 3 snel verkochte — ≤ 7 dagen weg of gereserveerd en weg, `sold_fast()` — anders vraagprijzen × 0,875; zonder kosten), upgrade t.o.v. `mijn_fiets.md` en waardescore; weergaven Te beoordelen / Favorieten / Mijn biedingen / Mijn flips (de fietsen van /flips, `own_flips_html()`) / Alle / Weggezet / Modellen (de lijst met alle modellen, zoeken, sorteren, nieuw model) / Onderdelen (`spares.py`) / Patronen, filters en sneltoetsen. Op de kaart klopt / ander model / bouwjaar / ontkoppelen (`POST /racefietsen/model`, tabellen `bike_model`/`bike_link`, migratie 19); na 3 dezelfde correcties een voorstel voor een regel bovenaan Modellen (`rules_json()`, `POST /racefietsen/regel`, tabel `bike_rule`, migratie 20; "nee" wordt onthouden). `refresh()` rekent alleen de geraakte fietsen opnieuw in de gecachte `Base` (met `Base.lock`), de rest bij de volgende ronde. Het zware deel rekent één keer per ronde (`LiveCache.racebikes`), de pagina krijgt JSON (`bikes`, `models`, `rules`) en tekent zelf; de vergelijkingslijst per fiets komt pas bij openklappen (`GET /racefietsen/vergelijk`, `COMPS_PATH`: hij was 2/3 van de pagina). `python racebikes.py jaar N` (koopjes.py, `year_budget`): de advertentiepagina van hooguit 20 goedkope fietsen zonder bouwjaar (≥ 15% onder de schatting), nooit twee keer, voor de volledige omschrijving, en framehoogte/materiaal/rem uit de Kenmerken zoals een ronde (`plan_years()`, `lookup_years()`, `recheck.save_page_specs()`). Weg-redenen `marks.BIKE_REASONS`; "geen racefiets" komt niet terug bij een lagere prijs.

### `bike_identity.py`

Welke fiets is het: `identify()` = `recognize()` (wat de advertentie zegt) + `resolve()` (koppeling of regel erop, zonder de tekst opnieuw te lezen). Het model (`Identity.name`) is de eigen koppeling, anders een toegepaste regel, anders het referentiemodel uit `reference_bikes.csv` (tenzij de titel preciezer is: "Trek Domane SL6" tegen het vangnet "Trek Domane"), anders merk + model + uitvoering uit de titel (modelnamen per merk uit `reference_bike_catalog.csv` of het woord na het merk; uitvoering `variant_of()`: "SL6", "Advanced 2"). Sleutels `exact`/`coarse` via `model_key()` (zonder spaties en haakjes). Bouwjaar (eigen jaar gaat voor) en tijdperk (rem, elektronisch, versnellingen — zonder jaartallen). `comparables()`: minstens 5 per trede (model ±2 jaar → model → familie ±2 → familie tijdperk → opbouw ±2 → onzeker), anders nog eens met 3 "(weinig)"; zonder model geen schatting. `Pool.replace()` verplaatst één fiets. `NOT_A_FAMILY` houdt gewone woorden ("maat", "cross") buiten de modelnamen.

### `spares.py`

Reserves voor het flippen: losse fietsonderdelen die de rondes al tegenkomen (geen eigen zoekopdracht: keuze van de eigenaar), per soort (`KINDS`: cassette, ketting, zadel, pedalen, ...) herkend op de titel; hele fietsen (buiten fietsonderdelen) en gezocht-advertenties tellen niet. De gekozen soorten in `setting` (`reserve_soorten`). Weergave Onderdelen op `/racefietsen` (`POST /racefietsen/reserves`; favoriet/weg/bod via de gewone acties).

### `dossier.py`

De knop dossier op `/racefietsen` (sneltoets d) en `python dossier.py <id> [--ophalen] [--uit pad]`: alles over één racefiets als Markdown om aan Claude te geven, met de vragen bovenaan (goede deal, wat vernieuwen, analyse van de vergelijkingen). Haalt de pagina op zoals controleer (`recheck_listing(details=True)`: bewaart ook wat een ronde bewaart bij een opgehaalde pagina — omschrijving, en framehoogte/materiaal/rem uit de Kenmerken, `recheck.save_page_specs()`), plus alle foto's, de overige Kenmerken en verkoper (alleen in het dossier, zonder namen); een vraagprijs alleen als die zeker is (`asking_from_row()`: een ronde schrijft `price_type` vaak niet weg); de vergelijkingsfietsen als CSV (trede van de schatting plus de rest van model en familie, hooguit 300: eerst de snel verkochte, dan elke groep naar verhouding en gelijkmatig over de prijzen, `pick_rows()`). Rekent niets nieuws: schatting en oordeel zijn die van `racebikes.py`.

## De eigen fiets: taxatie, kwaliteitsscore, upgrades

Naslag: [eigen-fiets.md](eigen-fiets.md).

### `valuation.py`

Waarderingsmotor (fase 3): E1/E2/E3 op de comps in `koopjes.db`, schrijft naar `valuation` + `valuation_evidence`. Leest `mijn_fiets.md`.

### `bike_comps.py`

De vergelijkingslijst voor de taxatie van de eigen fiets: elke advertentie (laatste 180 dagen, ook verdwenen) met de modelfamilie uit `mijn_fiets.md` ("defy") in de tekst of gevonden door een zoekopdracht met dat woord (`giant-defy`, `giant-defy-composite`, beide `category: alle`), uit elke categorie behalve onderdelen en accessoires, en van elk materiaal: het materiaal staat erbij (model, tekst of "volgens de verkoper"), de eigenaar kiest. Per advertentie meenemen of niet op `/fiets` (tabel `comp_choice`, migratie 16). **Alleen wat meegenomen is telt mee** in de taxatie (`valuation.select_comps(chosen=...)`), in `valuation.py`, `upgrade.py`, het rapport en het overzicht; de ladder geldt niet meer voor de eigen fiets.

### `scoring.py` + `scoring_config.json`

Kwaliteitsscore van een fiets los van de prijs (fase 4, §7): vijf dimensies met redenen, gewichten in de JSON. Niet `deal_score` en niet de waardescore. Knoppen van de upgradetest, standaard uit: leeftijd op de aandrijving, `wheels.eigen_wielen`, `fill_unknown()` (onbekend = gelijk aan de eigen fiets), `upgrade.marge`/`upgrade.onbekend`.

### `upgrade.py`

De upgrade-finder en de biedlogica (fase 5): de maatpoort (buiten de maat valt af, maat onbekend blijft met een vlag), het budget per kandidaat (velrem: de eigen wielset verhuist mee en telt in de score; schijfrem: hij wordt verkocht en telt in het budget), de effectieve prijs (vraagprijs × onderhandelingsfactor, of wat het kost om een biedadvertentie binnen te komen) en de speelruimte (`geschatte waarde − instapprijs`). `prepare_candidate()` / `finish_candidate()` scoren één advertentie tegen de eigen fiets; de upgradetest en `/racefietsen` gebruiken dezelfde. `python upgrade.py --db koopjes.db`. Rangschikt en legt uit; biedt nooit.

### `upgrade_test.py`

De upgradetest (`/upgrade` in `dashboard.py --serve`, `opdrachten/upgradetest.md`): de eigenaar zegt per fiets of hij een upgrade is (los van prijs en maat; tabel `upgrade_label`, migratie 22), ziet hoeveel de regel goed heeft, past de regel aan of laat `search()` hem zoeken, en slaat hem op in `setting` (`upgrade_regel`). Opgeslagen werkt hij overal (`apply_saved_rule()` in `report.load_owner_context()` en `upgrade.py`; LiveCache rekent alleen het upgradeoordeel opnieuw, `racebikes.rescore()`). Uitdraai van alle fietsen als CSV: `python upgrade_test.py uitdraai`.

## Flips

Naslag: [flips.md](flips.md) en [SHEETS.md](../SHEETS.md).

### `flips.py` + `flips_import/`

De flippagina `/flips` in `dashboard.py --serve`: elke flip (fiets, spullen, en de trades uit Mijn flips) als kaart met fase en dagen in die fase, klussenlijst (onderdeel: geschat → echte prijs → gedaan; klus; reis met OV-korting vol/40%/gratis), winkelmandje per winkel, aanbiedingen per onderdeel (link plakken met prijs, "kies deze" zet winkel/link/schatting; tabel `flip_offer`, migratie 21; `clean_url()` haalt volgcodes weg), doelprijs + marktcheck, specs en concept-advertentietekst, foto's (`flip_fotos/`, niet in git), biedingen van kopers; bovenaan verdiend, netto na investeringen (gereedschap, `flip_task.trade_id` NULL of `investment`), wat erin zit. Migratie 17 (`flip`, `trade_stage`, `flip_task`, `flip_bid`, `flip_photo`); `trade.market` `fietsen`/`spullen` hoort bij geen dashboard. `python flips.py import <json>` leest een lijst in, `python flips.py bijwerken <json>` werkt bestaande regels bij (winkel, link, prijs) en voegt aanbiedingen toe.

### `flips_sheets.py` + `flips_sheets.gs` + `SHEETS.md`

/flips en een Google Sheet in twee richtingen via een Apps Script-webapp (geen extra dependency); laatste wijziging wint; tabblad Aanbiedingen alleen-lezen. Sleutel en URL in `sheets.json` (niet in git).

## Referentiedata en de scripts eromheen

Naslag: [referentiedata.md](referentiedata.md).

### `reference_prices.csv`

Handmatig onderzochte modellen (43, alleen luidsprekers).

### `reference_bikes.csv`, `reference_bike_accessories.csv`

Fase 7: fietsen resp. fietscomputers/powermeters, met `kind`/`brand`/`source_url`. Ook met `git add -f` toegevoegd. Accessoires niet in het fietsbestand zetten — zie README.

### `reference_bike_computers.csv`

Één rij per fietscomputermodel: specs, navigatie (rerouting, kaarten, planning op het apparaat), training, ondersteuning, met bron. Vaste woorden per kolom (zie README); leeg = niet nagezocht. De volgorde is de matchvolgorde. Ook met `git add -f` toegevoegd.

### `reference_bike_catalog.csv`

Catalogus: één rij per merk/model/modeljaar met specs, nieuwprijs, `market` (NL of ES) en bron-URL. Geen patronen — wordt niet tegen titels gematcht. Ook met `git add -f` toegevoegd.

### `reference_sport_watches.csv`

Sporthorloges: 81 Garmin-, 18 Polar-, 19 Suunto- en 13 Coros-modellen, één rij per model, zelfde vorm als `reference_bike_computers.csv` (patroon, matchvolgorde), te lezen met `computers.load_catalog(pad)`. Europrijs alleen uit een bron met euro's, dollarprijs apart en nooit omgerekend. Zonder bron geen rij (Tactix, Quatix, Approach S12/S42/S70, Polar M400/V800 staan er daarom niet in). Smartwatches (Apple, Samsung, ...) horen er niet in: andere markt. Ook met `git add -f` toegevoegd.

### `catalog_tools/`

De scripts die `reference_bike_catalog.csv` opbouwen (Wayback, merksites, bikezona). Draai ze vanuit een lege scratch-map, niet vanuit de repo — ze schrijven een cache in de werkmap.

### `check_hifi_brand.py`, `check_reference_overlaps.py`, `reference_overview.py`

Hulpscripts bij het onderhouden van die database.

### `MARKTONDERZOEK.md` + `marktonderzoek_subcategorieen.csv`

Welke Marktplaats-categorieën als volgende markt passen (gemeten 28/29-09-2026): aanbod, instroom, verzendbaarheid, prijzen en merkvelden van alle 1.720 subcategorieën. De CSV is met `git add -f` toegevoegd.

### `marktonderzoek/`

De meetscripts daarvan; draai ze vanuit een lege map, zoals `catalog_tools/`.

## Plannen, opdrachten en de eigen fiets op papier

### `PLAN_FIETSWAARDE.md`

Het productplan (taxatie eigen fiets, upgrade-finder, SQLite): alle fases zijn af; §12 is het logboek van wat er per fase en daarbuiten gebouwd is en wat bleef liggen.

### `NEXT_STEPS.md`

Stand van zaken en losse eindjes.

### `opdrachten/`

Uitgeschreven opdrachten van de eigenaar (`fietsmodellen.md`, `goedkoopste_onderdelen.md`) en de werklijst van het weekend (`weekend.md`, met zijn keuzes en een logboek).

### `mijn_fiets.md`

Intake van de eigen fiets (brondocument voor de taxatie).

### `taxatie_2026-09-22.md`

De eerste handmatige taxatie van de eigen fiets, met bewijsregels (voorloper van fase 3).

### `fiets_master.md`

Masterdocument van de eigen fiets: onderdelen, maten en standaarden, onderhoud, uitgewerkte "past X?"-vragen, meetlijst. Elke regel met status (eigenaar / bron / onbekend); lees het bij elke vraag over wat er op de fiets past.

### `fiets_kaart.md`

Één pagina met alles over de eigen fiets voor een chat (ook buiten de repo): maten, onderdelen, wat past en niet, voorkeuren, budget. Bijwerken samen met `fiets_master.md`.

### `fietser_kaart.md`

De eigenaar als fietser: rijprofiel, wat hij al heeft, lichaamsmaten (in te vullen), voorkeuren — voor vragen over kleding, maten, uitrusting. Naast `fiets_kaart.md`.

### `bikepacking_uitrusting.xlsx`

Bikepackingtassen voor de eigen fiets: prijs, gewicht, bron per regel, "Past?" als formule op de maten in het tabblad Mijn fiets, totalen in Mijn set. Prijzen zijn momentopnamen met winkel en datum.

## Tests

### `tests/`

Stdlib-unittests; `helpers.py` heeft `make_listing()` en een `FakeSession`. Draaien: `python -m unittest discover -s tests -t tests`. Tests raken het netwerk nooit (`helpers.py` blokkeert `fetch_listing_page`).
