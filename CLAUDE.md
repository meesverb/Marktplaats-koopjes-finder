# Marktplaats koopjes finder — werkinstructies

Marktplaats-scraper die advertenties zoekt, vergelijkt met een eigen
referentiedatabase en koopjes markeert. Eén gebruiker, lokaal draaiend, geen
server.

## Voor je begint

1. `git pull` — er werken soms meerdere sessies tegelijk aan deze repo.
2. Lees **`PLAN_FIETSWAARDE.md`**. Dat is het actieve werkplan (taxatie eigen
   fiets + upgrade-finder + overstap naar SQLite). Het blokje bovenaan zegt
   wat er al bestaat.
3. Pak **één fase**, niet meer. Vink hem af in §12 van het plan en noteer wat
   je voor de volgende hebt laten liggen.
4. Draai de tests, vóór én na je wijziging.

```bash
python -m unittest discover -s tests -t tests    # 1072 tests, moet groen zijn
python racefiets_jev.py --query luidsprekers --pages 1 --open-browser never
```

Werkt er iets niet zoals de README beschrijft, meld dat dan — ga niet raden.

## Harde regels

- **Begin bij een verse `main`, eindig op `main`.** Sessies krijgen vaak een
  eigen branch toegewezen (`claude/...`) en moeten daarheen pushen; dat is
  prima. Waar het om gaat: vertak van de actuele `main`, en zeg aan het eind
  expliciet naar welke branch je gepusht hebt, zodat het in `main` gemerged
  kan worden. Blijft werk op een losse branch staan, dan bouwt de volgende
  fase op verouderde code.
- Commitbericht begint met `Fase N:` als het bij een fase uit het plan hoort.
- **Houd de tests groen.** Faalt er een test die jij niet hebt aangeraakt,
  zoek dat dan uit in plaats van de test aan te passen. Een test weghalen,
  overslaan of uitzetten om groen te worden is nooit de oplossing.
- **Breek geen bestaande CLI-vlaggen of bestandsformaten.** Alles wat in de
  README staat moet blijven werken. Verandert het gedrag, werk dan de README
  bij in dezelfde commit.
- **Geen nieuwe dependencies** zonder goede reden. `requirements.txt` bevat
  alleen `requests`; `sqlite3`, `json` en `unittest` zitten in de stdlib.
- **Blijf beleefd tegen Marktplaats.** Respecteer `--delay`, geen parallelle
  verzoeken, voer de crawl-frequentie niet op.
- **Nooit automatisch bieden of reageren op advertenties.** Er is geld en een
  externe partij mee gemoeid; de eigenaar doet dat zelf.
- **Verzin geen marktfeiten.** Modeljaren, groepsetgeneraties en nieuwprijzen
  zijn precies waar een taalmodel overtuigend naast zit. Zoek het op en noteer
  de bron, of laat het veld leeg. Een verzonnen nieuwprijs vervuilt de
  taxatie voorgoed.

## Conventies in deze codebase

- **Nederlandse teksten voor de gebruiker, Engelse identifiers in de code.**
  Zo staat het er nu; houd dat aan.
- Commentaar legt uit *waarom*, niet *wat*. Vooral bij de eigenaardigheden van
  Marktplaats — die zijn niet af te leiden uit de code.
- Console-uitvoer is Nederlands; de kolomkoppen van de hoofdtabel zijn
  historisch Engels.

## Valkuilen

- **`.gitignore` sluit `*.csv` uit**, maar `reference_prices.csv` is bewust
  met `git add -f` toegevoegd omdat er echt onderzoek in zit. Houd dat zo.
  Persoonlijke data (`seen_listings.json`, `*_history.csv`, `koopjes.db`)
  hoort níet in git.
- **Het rapport-sjabloon staat in `report_template.html`** en is een
  `string.Template` (`$naam`/`${naam}`), niet meer een `.format()`-string in
  het script. Accolades in CSS/JS zijn daar dus gewoon enkel; het teken om op
  te letten is nu `$` zelf — schrijf `$$` voor een letterlijke.
- **Twee verschillende scores, niet vermengen.** `Listing.deal_score` (0-100,
  uit % van mediaan / 2e-hands gemiddelde / nieuwprijs) bestaat al. De
  `waardescore` uit het plan (`geschatte waarde / gevraagde prijs`) is iets
  anders en moet ook echt anders heten.
- **Bij een MIN_BID-advertentie is de prijs uit de zoekresultaten de
  vraagprijs**, niet het minimumbod — dat staat alleen op de advertentiepagina
  en ligt er vaak flink onder. Overschrijf de vraagprijs er niet mee. Er staat
  een test op.
- **Marktplaats kan zijn paginastructuur wijzigen.** Breekt het parsen, geef
  dan een duidelijke foutmelding in plaats van stil door te gaan.
- **Een migratie die een test terugdraait, maakt tabellen, geen kolommen.**
  Een paar tests zetten de database terug naar een oudere versie met `DROP
  TABLE` (zie `db.FLIP_TABLES`, `db.PLACE_TABLES`); een `ALTER TABLE ... ADD
  COLUMN` op `listing` laat zich zo niet terugdraaien en de migratie loopt
  dan vast. Daarom staan plek en promotie in `listing_place`, niet in
  `listing`.
- **`koopjes.db` staat in WAL-modus** (`db._use_wal()`, 02-10-2026): lezers
  blokkeren geen schrijver meer ("database is locked" bij wegzetten op
  `/racefietsen`). `koopjes.db-wal`/`-shm` horen erbij en staan in
  `.gitignore`. Lees in een klik niet alle advertenties in om er één te
  vinden (`racebikes.find_listing()` doet één fiets).
- **`db.import_legacy()` heeft padargumenten met standaardwaarden** die naar
  het werkpad wijzen. Geef ze alle drie expliciet mee; laat je er een weg, dan
  leest hij stilzwijgend het echte bestand uit de repo in plaats van dat wat
  je bedoelde. Dat is bij het schrijven van de tests al een keer gebeurd.

## Bestanden

| Bestand | Wat |
| --- | --- |
| `racefiets_jev.py` | het hele script: crawlen, scoren, rapporteren |
| `koopjes.py` + `schedule.json` | automatische rondes: `schedule.json` beschrijft zoekopdrachten en tijdsloten, `koopjes.py run <slot>` draait er één (lock, log, bouwjaren opzoeken tot `year_budget` (max 20), weergaven/likes meten tot `views_budget`, `overzicht.html`), en elke ronde krijgt een regel in `logs/rondes.jsonl` (Laatste rondes in het overzicht, laatste 3 in `koopjes.py status`); `koopjes.py schedule` geeft de inplan-commando's |
| `computers.py` + `computer_scoring.json` | fietscomputers: herkent het model in de titel tegen `reference_bike_computers.csv`, functiescore met de gewichten die de eigenaar koos, upgrade t.o.v. de eigen Roam v1 en flipmarge (per uitvoering als die er genoeg heeft: `title_variant()`, ook voor de horloges; vanaf 3 snel verkochte — ≤ 7 dagen weg of gereserveerd en weg, `is_fast_sold()` — hun mediaan zonder afdingfactor, zoals op /racefietsen, ook in `market_resale()`). `classify_title()` deelt elke titel in (computer, accessoire, onderdeel, defect, gevraagd); los van dealscore en waardescore. `python computers.py` toont de score per model |
| `dashboard.py` | de dashboards per markt (`markets.py`): `dashboard.html` (fietscomputers: Flips / Upgrades / Te beoordelen / Favorieten / Mijn biedingen / Mijn flips / Alle computers / Weggezet / Marktprijzen / Vinted / Patronen / Uitgefilterd; Te beoordelen en Weggezet zijn knoppen die Alle met een filter openen, `VIEW_TABS`) en `dashboard_horloges.html` (sporthorloges: zonder Upgrades en Vinted), uit `koopjes.db`. `koopjes.py` bouwt beide na elke ronde; `--markt sporthorloges`/`alle` met de hand. Leest alleen, behalve `--serve`: één adres voor alles (`/start`, met een balk bovenaan elke live pagina; de rapporten, het overzicht en `lijsten/` via `/bestanden/`, alleen die patronen: `SERVED_FILES`), toont beide live (`/` en `/horloges`) plus `/racefietsen` (`racebikes.py`), `/fiets` (`bike_comps.py`), `/upgrade` (`upgrade_test.py`) en `/flips`, en schrijft de eigen aan- en verkopen, met hun markt, de markeringen favoriet/weg en notities (`marks.py`), eigen biedingen (`own_bids.py`), de postcode voor de afstand (`distance.py`) en de keuzes op `/fiets`, en heeft per advertentie de knop controleer (`recheck.py`). Favoriet/weg, notitie en meenemen/niet gaan zonder herladen (JSON, `live_update()`); de knoppen zijn geen `<form>` per advertentie (duizenden formulieren maakten de pagina traag), `LiveCache` onthoudt het zware deel tot een ronde de database verandert (één opbouw tegelijk per pagina; `keep_warm()` rekent na het starten en na elke ronde alvast vooruit), en live komt de tab Alle pas van de server als je hem opent (`LAZY_PANELS`, `/paneel`; het geschreven bestand heeft alles) |
| `flips.py` + `flips_import/` | de flippagina `/flips` in `dashboard.py --serve`: elke flip (fiets, spullen, en de trades uit Mijn flips) als kaart met fase en dagen in die fase, klussenlijst (onderdeel: geschat → echte prijs → gedaan; klus; reis met OV-korting vol/40%/gratis), winkelmandje per winkel, aanbiedingen per onderdeel (link plakken met prijs, "kies deze" zet winkel/link/schatting; tabel `flip_offer`, migratie 21; `clean_url()` haalt volgcodes weg), doelprijs + marktcheck, specs en concept-advertentietekst, foto's (`flip_fotos/`, niet in git), biedingen van kopers; bovenaan verdiend, netto na investeringen (gereedschap, `flip_task.trade_id` NULL of `investment`), wat erin zit. Migratie 17 (`flip`, `trade_stage`, `flip_task`, `flip_bid`, `flip_photo`); `trade.market` `fietsen`/`spullen` hoort bij geen dashboard. `python flips.py import <json>` leest een lijst in, `python flips.py bijwerken <json>` werkt bestaande regels bij (winkel, link, prijs) en voegt aanbiedingen toe |
| `flips_sheets.py` + `flips_sheets.gs` + `SHEETS.md` | /flips en een Google Sheet in twee richtingen via een Apps Script-webapp (geen extra dependency); laatste wijziging wint; tabblad Aanbiedingen alleen-lezen. Sleutel en URL in `sheets.json` (niet in git) |
| `launcher.py` | de knoppen onder Rondes op `/start`: `python koopjes.py run <slot>` als los achtergrondproces, nooit twee tegelijk (het slot van koopjes.py) en een wachttijd per slot sinds de vorige ronde (30 min, 6 uur bij `pages: 0`), zodat een knop de crawl-frequentie niet opvoert |
| `markets.py` | de markten naast elkaar: categorieën, referentiebestand, bestandsnaam, welke tabbladen, indeling van titels zonder model. `trade_market()` zegt bij welke markt een eigen aankoop hoort (migratie 10, `trade.market`) |
| `vinted.py` | Vinted-exports (een CSV die de eigenaar zelf maakt) inlezen in `koopjes.db` (tabellen `vinted_listing`/`vinted_price`, migratie 8) en naast Marktplaats zetten: tab Vinted in het dashboard, `python vinted.py` in de console. Haalt zelf niets op bij Vinted; Vinted-prijzen zijn nooit vergelijkingsprijs voor Marktplaats |
| `marks.py` | eigen markeringen per advertentie: favoriet, of weg (niet waard, gereserveerd) — tabel `listing_mark`, migratie 12 — en een eigen notitie bij elke advertentie, los van de markering — tabel `listing_note`, migratie 15 (de kolom `listing_mark.note` van migratie 13 is sindsdien leeg en ongebruikt). Gezet via `python dashboard.py --serve`; weg haalt een advertentie uit Flips/Upgrades/Zonder prijs tot de prijs onder die van het wegzetten zakt. Nooit invloed op vergelijkingsprijzen |
| `racebikes.py` | `/racefietsen` in `dashboard.py --serve`: alle racefietsen uit `koopjes.db` (actief = gezien binnen 8 dagen) als kaarten met 3 foto's, specs, beschrijving, flip (verkoopschatting uit de fietsen van hetzelfde model: mediaan van ≥ 3 snel verkochte — ≤ 7 dagen weg of gereserveerd en weg, `sold_fast()` — anders vraagprijzen × 0,875; zonder kosten), upgrade t.o.v. `mijn_fiets.md` en waardescore; weergaven Te beoordelen / Favorieten / Mijn biedingen / Mijn flips (de fietsen van /flips, `own_flips_html()`) / Alle / Weggezet / Modellen (de lijst met alle modellen, zoeken, sorteren, nieuw model) / Onderdelen (`spares.py`) / Patronen, filters en sneltoetsen. Op de kaart klopt / ander model / bouwjaar / ontkoppelen (`POST /racefietsen/model`, tabellen `bike_model`/`bike_link`, migratie 19); na 3 dezelfde correcties een voorstel voor een regel bovenaan Modellen (`rules_json()`, `POST /racefietsen/regel`, tabel `bike_rule`, migratie 20; "nee" wordt onthouden). `refresh()` rekent alleen de geraakte fietsen opnieuw in de gecachte `Base` (met `Base.lock`), de rest bij de volgende ronde. Het zware deel rekent één keer per ronde (`LiveCache.racebikes`), de pagina krijgt JSON (`bikes`, `models`, `rules`) en tekent zelf; de vergelijkingslijst per fiets komt pas bij openklappen (`GET /racefietsen/vergelijk`, `COMPS_PATH`: hij was 2/3 van de pagina). `python racebikes.py jaar N` (koopjes.py, `year_budget`): de advertentiepagina van hooguit 20 goedkope fietsen zonder bouwjaar (≥ 15% onder de schatting), nooit twee keer, voor de volledige omschrijving, en framehoogte/materiaal/rem uit de Kenmerken zoals een ronde (`plan_years()`, `lookup_years()`, `recheck.save_page_specs()`). Weg-redenen `marks.BIKE_REASONS`; "geen racefiets" komt niet terug bij een lagere prijs |
| `spares.py` | reserves voor het flippen: losse fietsonderdelen die de rondes al tegenkomen (geen eigen zoekopdracht: keuze van de eigenaar), per soort (`KINDS`: cassette, ketting, zadel, pedalen, ...) herkend op de titel; hele fietsen (buiten fietsonderdelen) en gezocht-advertenties tellen niet. De gekozen soorten in `setting` (`reserve_soorten`). Weergave Onderdelen op `/racefietsen` (`POST /racefietsen/reserves`; favoriet/weg/bod via de gewone acties) |
| `dossier.py` | de knop dossier op `/racefietsen` (sneltoets d) en `python dossier.py <id> [--ophalen] [--uit pad]`: alles over één racefiets als Markdown om aan Claude te geven, met de vragen bovenaan (goede deal, wat vernieuwen, analyse van de vergelijkingen). Haalt de pagina op zoals controleer (`recheck_listing(details=True)`: bewaart ook wat een ronde bewaart bij een opgehaalde pagina — omschrijving, en framehoogte/materiaal/rem uit de Kenmerken, `recheck.save_page_specs()`), plus alle foto's, de overige Kenmerken en verkoper (alleen in het dossier, zonder namen); een vraagprijs alleen als die zeker is (`asking_from_row()`: een ronde schrijft `price_type` vaak niet weg); de vergelijkingsfietsen als CSV (trede van de schatting plus de rest van model en familie, hooguit 300: eerst de snel verkochte, dan elke groep naar verhouding en gelijkmatig over de prijzen, `pick_rows()`). Rekent niets nieuws: schatting en oordeel zijn die van `racebikes.py` |
| `bike_identity.py` | welke fiets is het: `identify()` = `recognize()` (wat de advertentie zegt) + `resolve()` (koppeling of regel erop, zonder de tekst opnieuw te lezen). Het model (`Identity.name`) is de eigen koppeling, anders een toegepaste regel, anders het referentiemodel uit `reference_bikes.csv` (tenzij de titel preciezer is: "Trek Domane SL6" tegen het vangnet "Trek Domane"), anders merk + model + uitvoering uit de titel (modelnamen per merk uit `reference_bike_catalog.csv` of het woord na het merk; uitvoering `variant_of()`: "SL6", "Advanced 2"). Sleutels `exact`/`coarse` via `model_key()` (zonder spaties en haakjes). Bouwjaar (eigen jaar gaat voor) en tijdperk (rem, elektronisch, versnellingen — zonder jaartallen). `comparables()`: minstens 5 per trede (model ±2 jaar → model → familie ±2 → familie tijdperk → opbouw ±2 → onzeker), anders nog eens met 3 "(weinig)"; zonder model geen schatting. `Pool.replace()` verplaatst één fiets. `NOT_A_FAMILY` houdt gewone woorden ("maat", "cross") buiten de modelnamen |
| `distance.py` | afstand hemelsbreed tot de eigen postcode: plek per advertentie uit de zoekresultaten (`listing_place`, migratie 18), de postcode geplaatst met één zoekverzoek mét postcode (de afstanden terugrekenen), opgeslagen in `setting`. Schuifje + kolom Afstand op alle live pagina's; telt nergens in een score |
| `own_bids.py` | de biedingen die de eigenaar zelf op Marktplaats deed (tabel `own_bid`, migratie 18): elk bod bewaard, status van het laatste (open/overboden/afgewezen/geaccepteerd/ingetrokken); geaccepteerd zet hem meteen op `/flips`. Tab Mijn biedingen op elke pagina, tegel op `/start`. Het script biedt nooit zelf |
| `views.py` | weergaven en likes (bewaard) van de advertentiepagina (`stats`), tabel `listing_stats`: meeliften op biedopvraging/controleer, gericht (eigen advertenties, favorieten, biedingen) en een vaste steekproef van 1 op 10 nieuwe op 1, 3 en 7 dagen, hooguit `views_budget` per ronde (`schedule.json`). Analyse in Patronen; verloop van je eigen advertentie op `/flips`. `python views.py plan/meet N` |
| `bike_comps.py` | de vergelijkingslijst voor de taxatie van de eigen fiets: elke advertentie (laatste 180 dagen, ook verdwenen) met de modelfamilie uit `mijn_fiets.md` ("defy") in de tekst of gevonden door een zoekopdracht met dat woord (`giant-defy`, `giant-defy-composite`, beide `category: alle`), uit elke categorie behalve onderdelen en accessoires, en van elk materiaal: het materiaal staat erbij (model, tekst of "volgens de verkoper"), de eigenaar kiest. Per advertentie meenemen of niet op `/fiets` (tabel `comp_choice`, migratie 16). **Alleen wat meegenomen is telt mee** in de taxatie (`valuation.select_comps(chosen=...)`), in `valuation.py`, `upgrade.py`, het rapport en het overzicht; de ladder geldt niet meer voor de eigen fiets |
| `recheck.py` | de knop controleer in `dashboard.py --serve`: haalt één advertentiepagina op (één verzoek per klik, nooit twee tegelijk, minstens 1,5 s ertussen) en legt vast wat erop staat: gereserveerd, biedingen (zelfde regels als de ronde: `racefiets_jev.apply_bid_info()`), prijs, of verdwenen (410). Laat `last_seen` staan; schrijft `listing.checked_at` en `bid_high` (migratie 14). Nooit bieden of reageren |
| `trades.py` | Mijn flips: de eigen aan- en verkopen (tabel `trade`, migratie 7) en de voortgang daarvan. Invoeren via `python dashboard.py --serve` (lokaal, 127.0.0.1, met token); nooit een vergelijkingsprijs |
| `patterns.py` | lange-termijnpatronen voor de tab Patronen: verkoopsnelheid per model, gemeten afdingfactor (snel verdwenen ÷ mediaan vraag, vanaf n=20), flips achteraf, prijs per maand, nieuw per weekdag. Verdwenen ≠ verkocht; alleen lezen |
| `sleepers.py` | slapers: advertenties waarvan titel en tekst niets over de fiets zeggen (geen merk, weinig tekst, haast, bieden zonder bod). Alleen uit de zoekresultaten; eigen tab in het rapport, los van dealscore en waardescore |
| `report.py` | rapportpanelen (fase 6): Biedpaneel, Upgrade, Mijn fiets, plus de waardescore-kolom; alleen lezen uit `koopjes.db` |
| `report_template.html` | HTML-sjabloon van het rapport (`string.Template`), wordt runtime ingelezen |
| `db.py` | SQLite-schema, migraties, import van de oude bestanden, CSV-export; sinds fase 1b aangesloten op het script (`--db`/`--no-db`) |
| `scoring.py` + `scoring_config.json` | kwaliteitsscore van een fiets los van de prijs (fase 4, §7): vijf dimensies met redenen, gewichten in de JSON. Niet `deal_score` en niet de waardescore. Knoppen van de upgradetest, standaard uit: leeftijd op de aandrijving, `wheels.eigen_wielen`, `fill_unknown()` (onbekend = gelijk aan de eigen fiets), `upgrade.marge`/`upgrade.onbekend` |
| `upgrade_test.py` | de upgradetest (`/upgrade` in `dashboard.py --serve`, `opdrachten/upgradetest.md`): de eigenaar zegt per fiets of hij een upgrade is (los van prijs en maat; tabel `upgrade_label`, migratie 22), ziet hoeveel de regel goed heeft, past de regel aan of laat `search()` hem zoeken, en slaat hem op in `setting` (`upgrade_regel`). Opgeslagen werkt hij overal (`apply_saved_rule()` in `report.load_owner_context()` en `upgrade.py`; LiveCache rekent alleen het upgradeoordeel opnieuw, `racebikes.rescore()`). Uitdraai van alle fietsen als CSV: `python upgrade_test.py uitdraai` |
| `valuation.py` | waarderingsmotor (fase 3): E1/E2/E3 op de comps in `koopjes.db`, schrijft naar `valuation` + `valuation_evidence`. Leest `mijn_fiets.md` |
| `tests/` | stdlib-unittests; `helpers.py` heeft `make_listing()` en een `FakeSession` |
| `PLAN_FIETSWAARDE.md` | actief werkplan, gefaseerd |
| `opdrachten/` | uitgeschreven opdrachten van de eigenaar (`fietsmodellen.md`, `goedkoopste_onderdelen.md`) en de werklijst van het weekend (`weekend.md`, met zijn keuzes en een logboek) |
| `taxatie_2026-09-22.md` | de eerste handmatige taxatie van de eigen fiets, met bewijsregels (voorloper van fase 3) |
| `mijn_fiets.md` | intake van de eigen fiets (brondocument voor de taxatie) |
| `fiets_master.md` | masterdocument van de eigen fiets: onderdelen, maten en standaarden, onderhoud, uitgewerkte "past X?"-vragen, meetlijst. Elke regel met status (eigenaar / bron / onbekend); lees het bij elke vraag over wat er op de fiets past |
| `bikepacking_uitrusting.xlsx` | bikepackingtassen voor de eigen fiets: prijs, gewicht, bron per regel, "Past?" als formule op de maten in het tabblad Mijn fiets, totalen in Mijn set. Prijzen zijn momentopnamen met winkel en datum |
| `NEXT_STEPS.md` | stand van zaken en losse eindjes |
| `reference_prices.csv` | handmatig onderzochte modellen (43, alleen luidsprekers) |
| `reference_bikes.csv`, `reference_bike_accessories.csv` | fase 7: fietsen resp. fietscomputers/powermeters, met `kind`/`brand`/`source_url`. Ook met `git add -f` toegevoegd. Accessoires niet in het fietsbestand zetten — zie README |
| `reference_bike_computers.csv` | één rij per fietscomputermodel: specs, navigatie (rerouting, kaarten, planning op het apparaat), training, ondersteuning, met bron. Vaste woorden per kolom (zie README); leeg = niet nagezocht. De volgorde is de matchvolgorde. Ook met `git add -f` toegevoegd |
| `reference_bike_catalog.csv` | catalogus: één rij per merk/model/modeljaar met specs, nieuwprijs, `market` (NL of ES) en bron-URL. Geen patronen — wordt niet tegen titels gematcht. Ook met `git add -f` toegevoegd |
| `reference_sport_watches.csv` | sporthorloges: 81 Garmin-, 18 Polar-, 19 Suunto- en 13 Coros-modellen, één rij per model, zelfde vorm als `reference_bike_computers.csv` (patroon, matchvolgorde), te lezen met `computers.load_catalog(pad)`. Europrijs alleen uit een bron met euro's, dollarprijs apart en nooit omgerekend. Zonder bron geen rij (Tactix, Quatix, Approach S12/S42/S70, Polar M400/V800 staan er daarom niet in). Smartwatches (Apple, Samsung, ...) horen er niet in: andere markt. Ook met `git add -f` toegevoegd |
| `watches.py` | sporthorloges: de categorieën (sporthorloges, smartwatches, activity-trackers), de gevolgde merken (`BRAND_RE`: Garmin, Polar, Suunto, Coros) en `classify_unknown()` voor titels zonder bekend model (horloge met onbekend model, bandje, ander merk, geen horloge). `python watches.py` toont de markt en de flips in de console. Zoekopdracht `sporthorloges` ("garmin") in de nacht- en overdagronde, `polar`/`suunto`/`coros` alleen 's nachts, alle met biedopvragingen (`bid_lookup` fast; het bod blijft bewaard, migratie 11) |
| `catalog_tools/` | de scripts die `reference_bike_catalog.csv` opbouwen (Wayback, merksites, bikezona). Draai ze vanuit een lege scratch-map, niet vanuit de repo — ze schrijven een cache in de werkmap |
| `check_hifi_brand.py`, `check_reference_overlaps.py`, `reference_overview.py` | hulpscripts bij het onderhouden van die database |
| `MARKTONDERZOEK.md` + `marktonderzoek_subcategorieen.csv` | welke Marktplaats-categorieën als volgende markt passen (gemeten 28/29-09-2026): aanbod, instroom, verzendbaarheid, prijzen en merkvelden van alle 1.720 subcategorieën. De CSV is met `git add -f` toegevoegd |
| `marktonderzoek/` | de meetscripts daarvan; draai ze vanuit een lege map, zoals `catalog_tools/` |
