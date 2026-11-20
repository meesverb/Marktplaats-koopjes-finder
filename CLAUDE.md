# Marktplaats koopjes finder — werkinstructies

Een Marktplaats-scraper die advertenties zoekt, in een eigen SQLite-database
bewaart, vergelijkt met zelf onderzochte referentieprijzen en laat zien wat de
moeite waard is (racefietsen, fietscomputers, sporthorloges, de eigen fiets,
flips). Eén gebruiker, lokaal draaiend, geen server buiten 127.0.0.1.

Wat het voor de eigenaar doet staat in `README.md`; alles per onderwerp in
`docs/`; welk bestand wat doet in `docs/architectuur.md`.

## Voor je begint

1. `git pull` — er werken soms meerdere sessies tegelijk aan deze repo.
2. Zoek uit waar je opdracht bij hoort:
   - opschonen of verbeteren van de code of de documentatie:
     **`VERBETERPLAN.md`** — pak **één stap**, vink hem af, noteer wat bleef
     liggen;
   - een opdracht van de eigenaar die al is uitgeschreven: `opdrachten/`;
   - iets nieuws: lees in `PLAN_FIETSWAARDE.md` §3 (keuzes van de eigenaar)
     en §12 (wat er al gebouwd is en wat bleef liggen), en `NEXT_STEPS.md`
     voor de ideeën die er nog liggen.
3. Draai de tests, vóór én na je wijziging:

```bash
python -m unittest discover -s tests -t tests    # 1082 tests, ~15 s, moet groen zijn
```

4. Raakt je wijziging het crawlen, draai dan één echte pagina (één verzoek):

```bash
python racefiets_jev.py --query luidsprekers --pages 1 --open-browser never
```

   Doe dat vanuit een lege map buiten de repo: het schrijft `koopjes.db`, een
   rapport en `seen_listings.json` in de werkmap.
5. Raakt je wijziging een live pagina, start dan `python dashboard.py --serve
   --no-browser` en open de pagina echt; de tests renderen HTML maar klikken
   nergens op.

Werkt er iets niet zoals de README of `docs/` beschrijft, meld dat dan — ga
niet raden.

## Harde regels

- **Begin bij een verse `main`, eindig op `main`.** Sessies krijgen vaak een
  eigen branch (`claude/...`) en moeten daarheen pushen; dat is prima. Vertak
  van de actuele `main`, fetch opnieuw vlak voor je merget, en zeg aan het
  eind naar welke branch je gepusht hebt. Blijft werk op een losse branch
  staan, dan bouwt de volgende sessie op verouderde code.
- **Commitbericht** begint met `Fase N:` (een fase uit `PLAN_FIETSWAARDE.md`)
  of `Stap X0:` (een stap uit `VERBETERPLAN.md`) als het daarbij hoort.
- **Houd de tests groen.** Faalt er een test die jij niet hebt aangeraakt,
  zoek dat dan uit in plaats van de test aan te passen. Een test weghalen,
  overslaan of uitzetten om groen te worden is nooit de oplossing.
- **Breek geen bestaande CLI-vlaggen of bestandsformaten.** Alles wat in
  `README.md` en `docs/` staat moet blijven werken. Verandert het gedrag,
  werk dan de pagina in `docs/` bij in dezelfde commit.
- **Geen nieuwe dependencies** zonder goede reden. `requirements.txt` bevat
  alleen `requests`; `sqlite3`, `json` en `unittest` zitten in de stdlib.
- **Blijf beleefd tegen Marktplaats.** Respecteer `--delay`, geen parallelle
  verzoeken, voer de crawl-frequentie niet op. Wat nu losse
  advertentiepagina's ophaalt doet dat één tegelijk via `recheck.py` en met
  een budget per ronde (`year_budget`, `views_budget`); houd dat patroon aan.
- **Nooit automatisch bieden of reageren op advertenties.** Er is geld en een
  externe partij mee gemoeid; de eigenaar doet dat zelf.
- **Verzin geen marktfeiten.** Modeljaren, groepsetgeneraties en nieuwprijzen
  zijn precies waar een taalmodel overtuigend naast zit. Zoek het op en noteer
  de bron, of laat het veld leeg. Een verzonnen nieuwprijs vervuilt de
  taxatie voorgoed.
- **Persoonlijke data hoort niet in git**: `koopjes.db` (+ `-wal`/`-shm`),
  `seen_listings.json`, `*_history.csv`, rapporten, dashboards, `logs/`,
  `lijsten/`, `flip_fotos/`, `sheets.json`.

## Conventies in deze codebase

- **Nederlandse teksten voor de gebruiker, Engelse identifiers in de code.**
  Console-uitvoer en pagina's zijn Nederlands; de kolomkoppen van de
  hoofdtabel zijn historisch Engels. De onderwerpspagina's in `docs/` zijn
  (nog) Engels, de rest van de documentatie Nederlands.
- Commentaar legt uit *waarom*, niet *wat*. Vooral bij de eigenaardigheden van
  Marktplaats — die zijn niet af te leiden uit de code. Een meting hoort een
  datum te hebben ("gemeten 28-09-2026").
- **Schrijf een hulpfunctie niet opnieuw.** Een tijd uit de database lezen:
  `util.parse_time()` / `util.parse_time_utc()`; tonen: `util.local_time()`; een dag: `util.parse_day()`. Een bedrag: `util.euro()` (ook met centen of plusteken).
  De database openen om alleen te lezen: `db.connect_readonly()`; om te
  schrijven (migreert ook): `db.connect()`.
- **Een pagina die alleen toont, opent de database alleen-lezen.** Zo kan een
  fout in een weergave nooit iets wegschrijven.
- Stdlib-`unittest`, geen pytest. `tests/helpers.py` heeft `make_listing()`
  en een `FakeSession`; tests raken het netwerk nooit.

## Valkuilen

- **`.gitignore` sluit `*.csv` uit**, maar de referentiebestanden
  (`reference_*.csv`, `marktonderzoek_subcategorieen.csv`) zijn bewust met
  `git add -f` toegevoegd omdat er echt onderzoek in zit. Houd dat zo.
- **Het rapport-sjabloon staat in `report_template.html`** en is een
  `string.Template` (`$naam`/`${naam}`). Accolades in CSS/JS zijn daar gewoon
  enkel; het teken om op te letten is `$` zelf — schrijf `$$` voor een
  letterlijke.
- **De CSS en JavaScript van de live pagina's staan in `static/`**, de HTML
  als f-strings in de Python-module (`pages.py`, `racebikes.py`,
  `upgrade_test.py`, `flips_page.py`, ...). `pages.static()` leest een
  bestand bij het starten en zet het letterlijk in de pagina, zodat elke
  pagina één bestand blijft. Controleer JavaScript met `node --check` (doet
  GitHub Actions ook) en open de pagina in een browser.
- **Vier scores, niet vermengen.** `Listing.deal_score` (0-100: is de *prijs*
  goed), de slaperscore (`sleepers.py`), de kwaliteitsscore (`scoring.py`:
  hoe goed is de *fiets*) en de waardescore (`geschatte waarde / gevraagde
  prijs`). Ze heten anders omdat ze iets anders meten.
- **Bij een MIN_BID-advertentie is de prijs uit de zoekresultaten de
  vraagprijs**, niet het minimumbod — dat staat alleen op de advertentiepagina
  en ligt er vaak flink onder. Overschrijf de vraagprijs er niet mee. Er staat
  een test op.
- **Verdwenen is niet verkocht.** Een advertentie kan ingetrokken zijn, en
  alleen een volledige crawl markeert iets als verdwenen. "Snel verkocht"
  (`racebikes.sold_fast()`, `computers.is_fast_sold()`) is de beste
  benadering; schrijf nergens "verkocht voor" bij een verdwenen advertentie.
- **Marktplaats kan zijn paginastructuur wijzigen.** Breekt het parsen, geef
  dan een duidelijke foutmelding in plaats van stil door te gaan.
- **Een migratie die een test terugdraait, maakt tabellen, geen kolommen.**
  Een paar tests zetten de database terug naar een oudere versie
  (`tests/helpers.roll_back()`: `DROP TABLE` van alles wat de migraties vanaf
  die versie met `CREATE TABLE` aanmaakten); een `ALTER TABLE ... ADD COLUMN`
  op `listing` laat zich zo niet terugdraaien en de migratie loopt dan vast.
  Daarom staan plek en promotie in `listing_place`, niet in `listing`.
- **`db.connect_readonly()` migreert niet.** Een lezer kan een database van
  vóór de laatste migratie treffen en moet zelf tegen een ontbrekende tabel of
  kolom kunnen (`sqlite3.Error` opvangen, of `db._has_table()`).
- **`koopjes.db` staat in WAL-modus** (`db._use_wal()`, 02-10-2026): lezers
  blokkeren geen schrijver meer. `koopjes.db-wal`/`-shm` horen erbij. Lees in
  een klik niet alle advertenties in om er één te vinden
  (`racebikes.find_listing()` doet één fiets).
- **`db.import_legacy()` heeft padargumenten met standaardwaarden** die naar
  het werkpad wijzen. Geef ze alle drie expliciet mee; laat je er een weg, dan
  leest hij stilzwijgend het echte bestand uit de repo in plaats van dat wat
  je bedoelde. Dat is bij het schrijven van de tests al een keer gebeurd.
- **Imports staan bovenaan en lopen in lagen** (`util`/`db`/`crawl` onderop,
  pagina's en commando's bovenop; zie `docs/architectuur.md`). Alleen
  `dashboard.main` en `watches.main` importeren binnen de functie, omdat wat
  ze bouwen zelf op hen bouwt. Importeer geen laag die hoger ligt; draai na
  een nieuwe import `python <module>.py --help`, niet alleen de tests.
- **De live server onthoudt het zware rekenwerk** (`server.LiveCache`) tot
  een ronde de database verandert. Een actie die iets wijzigt moet de cache
  bijwerken (`live_update()`, `racebikes.refresh()`), anders ziet de eigenaar
  zijn klik pas na de volgende ronde.

## Kaart van de code

De lange versie, met tabellen, migraties en ingangen per bestand:
**`docs/architectuur.md`**. Werk die bij in dezelfde commit als de code.

| Gebied | Bestanden | Naslag |
| --- | --- | --- |
| Crawlen, scoren, rapport | `racefiets_jev.py` (het commando, alle vlaggen), `crawl.py` (`Listing`, ophalen, parsen, biedingen, specs), `dealscore.py`, `console.py`, `report.py` + `report_template.html` (het rapport en zijn panelen), `sleepers.py` (slapers) | `docs/zoeken.md`, `docs/rapport.md` |
| Rondes | `koopjes.py` + `schedule.json` (tijdsloten, overzicht, logboek), `launcher.py` (knoppen op `/start`) | `docs/rondes.md` |
| Database, gedeeld | `db.py` (schema, migraties, alle queries), `util.py` (tijd, euro) | `docs/database.md` |
| Live server | `static/` (CSS en JavaScript van de pagina's), `server.py` (`--serve`: routes, knoppen, `LiveCache`), `pages.py` (paden, balk bovenaan, gedeelde CSS/JS, formulieren), `dashboard.py` (de dashboards per markt), `start_page.py`, `bike_page.py` (`/fiets`), `flips_page.py` (`/flips`) | `docs/dashboards.md` |
| Markten | `markets.py`, `computers.py` + `computer_scoring.json`, `watches.py`, `vinted.py`, `patterns.py` | `docs/dashboards.md` |
| Per advertentie | `marks.py` (favoriet/weg/notitie), `own_bids.py`, `distance.py`, `views.py`, `recheck.py` (controleer), `trades.py` (Mijn flips) | `docs/dashboards.md` |
| Racefietsen | `racebikes.py` (`/racefietsen`), `bike_identity.py` (welk model), `spares.py` (onderdelen), `dossier.py` | `docs/racefietsen.md` |
| Eigen fiets | `valuation.py`, `bike_comps.py` (`/fiets`), `scoring.py` + `scoring_config.json`, `upgrade.py`, `upgrade_test.py` (`/upgrade`) | `docs/eigen-fiets.md` |
| Flips | `flips.py` + `flips_import/`, `flips_sheets.py` + `flips_sheets.gs` | `docs/flips.md`, `SHEETS.md` |
| Referentiedata | `reference_*.csv`, `check_hifi_brand.py`, `check_reference_overlaps.py`, `reference_overview.py`, `catalog_tools/` | `docs/referentiedata.md` |
| Marktonderzoek | `MARKTONDERZOEK.md`, `marktonderzoek_subcategorieen.csv`, `marktonderzoek/` | — |
| Tests | `tests/` (één bestand per module, `helpers.py`, `fixtures/`) | — |

`catalog_tools/` en `marktonderzoek/` zijn losse meetscripts: draai ze vanuit
een lege map buiten de repo, ze schrijven een cache in de werkmap.

## Documenten

| Document | Wat |
| --- | --- |
| `README.md` | wat het doet en hoe je het elke dag gebruikt (kort) |
| `docs/` | naslag per onderwerp; `docs/README.md` is de inhoudsopgave |
| `VERBETERPLAN.md` | opschonen en verbeteren in kleine stappen, met een logboek |
| `PLAN_FIETSWAARDE.md` | het productplan; alle fases af, §12 is het logboek |
| `NEXT_STEPS.md` | stand van zaken, wat we leerden over Marktplaats, losse ideeën |
| `opdrachten/` | uitgeschreven opdrachten van de eigenaar, met zijn keuzes |
| `mijn_fiets.md` | intake van de eigen fiets: brondocument voor taxatie en upgrades (het script leest dit bestand) |
| `fiets_master.md`, `fiets_kaart.md` | alles over de eigen fiets (onderdelen, maten, wat past); lees `fiets_master.md` bij elke vraag over wat erop past, en werk de kaart mee bij |
| `fietser_kaart.md` | de eigenaar als fietser: maten, uitrusting, voorkeuren |
| `taxatie_2026-09-22.md` | de eerste handmatige taxatie, met bewijsregels |
| `bikepacking_uitrusting.xlsx` | bikepackingtassen voor de eigen fiets, met bron per regel |
| `SHEETS.md` | `/flips` koppelen aan een Google Sheet |
