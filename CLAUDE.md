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
python -m unittest discover -s tests -t tests    # 851 tests, moet groen zijn
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
- **`db.import_legacy()` heeft padargumenten met standaardwaarden** die naar
  het werkpad wijzen. Geef ze alle drie expliciet mee; laat je er een weg, dan
  leest hij stilzwijgend het echte bestand uit de repo in plaats van dat wat
  je bedoelde. Dat is bij het schrijven van de tests al een keer gebeurd.

## Bestanden

| Bestand | Wat |
| --- | --- |
| `racefiets_jev.py` | het hele script: crawlen, scoren, rapporteren |
| `koopjes.py` + `schedule.json` | automatische rondes: `schedule.json` beschrijft zoekopdrachten en tijdsloten, `koopjes.py run <slot>` draait er één (lock, log, `overzicht.html`), en elke ronde krijgt een regel in `logs/rondes.jsonl` (Laatste rondes in het overzicht, laatste 3 in `koopjes.py status`); `koopjes.py schedule` geeft de inplan-commando's |
| `computers.py` + `computer_scoring.json` | fietscomputers: herkent het model in de titel tegen `reference_bike_computers.csv`, functiescore met de gewichten die de eigenaar koos, upgrade t.o.v. de eigen Roam v1 en flipmarge (per uitvoering als die er genoeg heeft: `title_variant()`, ook voor de horloges). `classify_title()` deelt elke titel in (computer, accessoire, onderdeel, defect, gevraagd); los van dealscore en waardescore. `python computers.py` toont de score per model |
| `dashboard.py` | de dashboards per markt (`markets.py`): `dashboard.html` (fietscomputers: Flips / Upgrades / Favorieten / Mijn flips / Alle computers / Marktprijzen / Vinted / Patronen / Uitgefilterd) en `dashboard_horloges.html` (sporthorloges: zonder Upgrades en Vinted), uit `koopjes.db`. `koopjes.py` bouwt beide na elke ronde; `--markt sporthorloges`/`alle` met de hand. Leest alleen, behalve `--serve`: dat toont beide live (`/` en `/horloges`) plus `/fiets` (`bike_comps.py`), en schrijft de eigen aan- en verkopen, met hun markt, de markeringen favoriet/weg en notities (`marks.py`) en de keuzes op `/fiets`, en heeft per advertentie de knop controleer (`recheck.py`). Favoriet/weg, notitie en meenemen/niet gaan zonder herladen (JSON, `live_update()`); de knoppen zijn geen `<form>` per advertentie (duizenden formulieren maakten de pagina traag), en `LiveCache` onthoudt het zware deel tot een ronde de database verandert |
| `markets.py` | de markten naast elkaar: categorieën, referentiebestand, bestandsnaam, welke tabbladen, indeling van titels zonder model. `trade_market()` zegt bij welke markt een eigen aankoop hoort (migratie 10, `trade.market`) |
| `vinted.py` | Vinted-exports (een CSV die de eigenaar zelf maakt) inlezen in `koopjes.db` (tabellen `vinted_listing`/`vinted_price`, migratie 8) en naast Marktplaats zetten: tab Vinted in het dashboard, `python vinted.py` in de console. Haalt zelf niets op bij Vinted; Vinted-prijzen zijn nooit vergelijkingsprijs voor Marktplaats |
| `marks.py` | eigen markeringen per advertentie: favoriet, of weg (niet waard, gereserveerd) — tabel `listing_mark`, migratie 12 — en een eigen notitie bij elke advertentie, los van de markering — tabel `listing_note`, migratie 15 (de kolom `listing_mark.note` van migratie 13 is sindsdien leeg en ongebruikt). Gezet via `python dashboard.py --serve`; weg haalt een advertentie uit Flips/Upgrades/Zonder prijs tot de prijs onder die van het wegzetten zakt. Nooit invloed op vergelijkingsprijzen |
| `bike_comps.py` | de vergelijkingslijst voor de taxatie van de eigen fiets: elke advertentie uit racefietsen (laatste 180 dagen, ook verdwenen) met de modelfamilie uit `mijn_fiets.md` ("defy") in de tekst, behalve als het materiaal zeker niet klopt (aluminium via referentiemodel, tekst of kenmerken; onbekend blijft erin). Per advertentie meenemen of niet op `/fiets` (tabel `comp_choice`, migratie 16). **Alleen wat meegenomen is telt mee** in de taxatie (`valuation.select_comps(chosen=...)`), in `valuation.py`, `upgrade.py`, het rapport en het overzicht; de ladder geldt niet meer voor de eigen fiets |
| `recheck.py` | de knop controleer in `dashboard.py --serve`: haalt één advertentiepagina op (één verzoek per klik, nooit twee tegelijk, minstens 1,5 s ertussen) en legt vast wat erop staat: gereserveerd, biedingen (zelfde regels als de ronde: `racefiets_jev.apply_bid_info()`), prijs, of verdwenen (410). Laat `last_seen` staan; schrijft `listing.checked_at` en `bid_high` (migratie 14). Nooit bieden of reageren |
| `trades.py` | Mijn flips: de eigen aan- en verkopen (tabel `trade`, migratie 7) en de voortgang daarvan. Invoeren via `python dashboard.py --serve` (lokaal, 127.0.0.1, met token); nooit een vergelijkingsprijs |
| `patterns.py` | lange-termijnpatronen voor de tab Patronen: verkoopsnelheid per model, gemeten afdingfactor (snel verdwenen ÷ mediaan vraag, vanaf n=20), flips achteraf, prijs per maand, nieuw per weekdag. Verdwenen ≠ verkocht; alleen lezen |
| `sleepers.py` | slapers: advertenties waarvan titel en tekst niets over de fiets zeggen (geen merk, weinig tekst, haast, bieden zonder bod). Alleen uit de zoekresultaten; eigen tab in het rapport, los van dealscore en waardescore |
| `report.py` | rapportpanelen (fase 6): Biedpaneel, Upgrade, Mijn fiets, plus de waardescore-kolom; alleen lezen uit `koopjes.db` |
| `report_template.html` | HTML-sjabloon van het rapport (`string.Template`), wordt runtime ingelezen |
| `db.py` | SQLite-schema, migraties, import van de oude bestanden, CSV-export; sinds fase 1b aangesloten op het script (`--db`/`--no-db`) |
| `valuation.py` | waarderingsmotor (fase 3): E1/E2/E3 op de comps in `koopjes.db`, schrijft naar `valuation` + `valuation_evidence`. Leest `mijn_fiets.md` |
| `tests/` | stdlib-unittests; `helpers.py` heeft `make_listing()` en een `FakeSession` |
| `PLAN_FIETSWAARDE.md` | actief werkplan, gefaseerd |
| `mijn_fiets.md` | intake van de eigen fiets (brondocument voor de taxatie) |
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
