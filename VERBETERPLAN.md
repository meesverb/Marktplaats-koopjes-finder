# Verbeterplan — de code en de documentatie beter maken, in kleine stappen

Geschreven op 16-11-2026 na een doorlichting van de hele repo, op verzoek van
de eigenaar ("haal alle dubbele en niet gebruikte code eruit, en maak een plan
in kleine behapbare stukjes"). Dit plan gaat over **hoe de code in elkaar
zit**, niet over nieuwe functies; die staan in `NEXT_STEPS.md` en in §12 van
`PLAN_FIETSWAARDE.md`.

## Zo werk je hiermee

- Pak **één stap** per sessie. Elke stap is zo gesneden dat hij in één keer af
  kan en de tests daarna groen zijn.
- Geen enkele stap verandert wat de eigenaar ziet of typt, tenzij het er
  uitdrukkelijk bij staat (dan eerst vragen). Vlaggen, bestandsformaten en
  pagina's blijven werken.
- Vink de stap af, zet de datum erbij en noteer in één of twee regels wat je
  liet liggen. Commitbericht: `Stap B2: ...`.
- De volgorde binnen een groep is de aanbevolen volgorde. Groep B kan altijd;
  C1 hoort vóór C2 en C3.
- De regels uit `CLAUDE.md` gelden onverkort (tests groen, beleefd tegen
  Marktplaats, geen nieuwe dependencies, geen verzonnen marktfeiten).

## Stand op 16-11-2026 (gemeten)

| Wat | Getal |
| --- | --- |
| Python in de hoofdmap | 33 modules, ~26.600 regels; 1082 tests in 12 s, groen |
| Grootste modules | `dashboard.py` 4.500, `racefiets_jev.py` 3.700, `racebikes.py` 2.140, `db.py` 1.930, `upgrade_test.py` 1.570 regels |
| CSS en JavaScript als tekst in Python | ruim 1.700 regels (`racebikes.JS` 599, `upgrade_test.JS` 409, `dashboard.JS` 254, ...) |
| Langste functies | `dossier.build` 247, `koopjes.render_overview` 199, `racefiets_jev.parse_args` 198, `valuation.value_subject` 196, `racefiets_jev.collect_listings` 182 regels |
| Imports | een kring: `racefiets_jev` ↔ `report` ↔ `upgrade` ↔ `upgrade_test` ↔ `dashboard` ↔ `racebikes` ↔ `koopjes`; 14 modules importeren daarom binnen een functie |
| Automatische controle | geen: geen linter, geen CI; de tests draaien alleen als een sessie ze start |

Hoe gemeten: `vulture` en `pyflakes` (alleen in de sessie geïnstalleerd, niet
in `requirements.txt`), `pylint --enable=duplicate-code`, en drie eigen
scriptjes (ongebruikte namen per module, functies met dezelfde inhoud,
herhaalde blokken van vijf regels). De uitkomst: **de code was al netjes op
het niveau van functies** — weinig echt dode code — en de winst zit in
structuur: een paar reusachtige bestanden, een kring van imports en
JavaScript waar geen gereedschap naar kijkt.

## Logboek

### 16-11-2026 — doorlichting, opschoning, nieuwe documentatie

**Dode code weg** (nergens meer aangeroepen, ook niet in tests of documentatie):
`computers.KINDS_EXCLUDED`, `dashboard.COMPUTER_CATEGORY`, `dashboard.VIEW_TABS`,
`db.delete_own_bid()`, `flips.Task.shop_key`, `trades.Progress.has_any`,
`vinted.NEW_CONDITIONS`. Drie oude namen die alleen een test nog gebruikte
zijn weg en de tests gebruiken de echte naam: `flip_margin_eur` (→
`profit_eur`), `Dashboard.computers` (→ `items`), `unknown_computers` (→
`unknown_items`). `computers.match_model()` werd alleen door tests gebruikt en
staat nu als hulpfunctie in `tests/test_computers.py`. Ongebruikte imports weg
uit vier testbestanden en uit `catalog_tools/` en `marktonderzoek/`.

**Dubbele code samengevoegd:**

- 24 kopieën van "open de database alleen-lezen"
  (`sqlite3.connect(Path(...).as_uri() + "?mode=ro", uri=True)`) in 15
  modules → `db.connect_readonly()`.
- 8 kopieën van "lees een ISO-tijd" (`_time`, `_parse_time`, `_when`) →
  `util.parse_time()` en `util.parse_time_utc()`.
- 3 kopieën van "€1.250" → `util.euro()`.
- 4 kopieën van "stuur een antwoord" in de server →
  `DashboardHandler._send_bytes()`.
- Het verkocht-formulier werd twee keer gelezen (Mijn flips en `/flips`) →
  `dashboard.parse_sale()`.
- `upgrade.py` bouwde een fiets twee keer op dezelfde manier op → de tweede
  plek gebruikt `prepare_candidate()`.

**Gat gedicht:** `dashboard_horloges.html` stond niet in `.gitignore`
(`dashboard.html` wel).

**Documentatie:** de README van 2.039 regels is per onderwerp verdeeld over
negen pagina's in `docs/` — letterlijk, alleen de verwijzingen tussen de
pagina's zijn aangepast (gecontroleerd: geen regel verloren). De nieuwe
`README.md` is een korte Nederlandse ingang. De bestandentabel uit `CLAUDE.md`
staat nu uitgebreid in `docs/architectuur.md`; `CLAUDE.md` zelf heeft de
regels, de valkuilen en een compacte kaart.

**Gecontroleerd:** de 1074 bestaande tests groen voor en na, plus acht nieuwe
voor `util.py` en `db.connect_readonly()` (`tests/test_util.py`); één echte pagina
zoekresultaten opgehaald (`--query luidsprekers --pages 1`); alle live
pagina's (`/start`, `/`, `/horloges`, `/racefietsen`, `/flips`, `/fiets`,
`/upgrade`) gaven 200 op een verse database. Niet in een browser bekeken en
niet op de echte `koopjes.db` van de eigenaar gedraaid.

**Bewust laten staan** (wel gevonden, niet weggehaald — zie de stappen):
`db.export_csv()`, `valuation.fetch_component_prices()` en
`valuation.load_owned_items()` (alleen tests gebruiken ze, maar het zijn
afgesproken onderdelen uit het productplan: B4), de zes `db.*_TABLES`
(alleen voor tests: B6), en de kleinere herhalingen onder B1-B3.

---

## A. Vangnet eerst

Zonder vangnet is elke latere stap een gok. Deze drie zijn klein en maken de
rest veiliger.

- [x] **A1 — Een test die elke route van de server opvraagt.**
  *Waarom:* de tests renderen losse stukken HTML; of `/start`, `/racefietsen`
  enz. op een verse en op een gevulde database een 200 geven is op 16-11 met
  de hand gecontroleerd.
  *Wat:* één test in `tests/test_dashboard.py` die de server op een vrije
  poort start met een tijdelijke database en elke GET-route opvraagt
  (`/start`, `/`, `/horloges`, `/racefietsen`, `/fiets`, `/upgrade`,
  `/flips`, een onbekend pad → 404, `/bestanden/koopjes.db` → 404).
  *Klaar als:* de test faalt wanneer je in een van de `render()`-functies een
  fout zet.
  *Gedaan 20-11-2026:* `LiveServerTest.test_every_page_answers` vraagt de zeven pagina's en drie 404's op; gecontroleerd dat hij faalt als `racebikes.render` een fout gooit.

- [x] **A2 — Een test die ongebruikte imports en namen vindt, zonder nieuwe
  dependency.**
  *Waarom:* `pyflakes` vond op 16-11 een twintigtal ongebruikte imports; die
  komen vanzelf terug.
  *Wat:* `tests/test_hygiene.py` met `ast` uit de stdlib: (1) elke module
  compileert, (2) geen import in een module die nergens in die module
  gebruikt wordt (met een uitzonderingslijstje voor `helpers.mp`, dat alleen
  voor het pad geïmporteerd wordt). Niet meer dan dat: "ongebruikte functie"
  geeft te veel vals alarm (de server roept `do_GET` nooit zelf aan).
  *Klaar als:* een bewust toegevoegde `import os` de test laat falen.
  *Gedaan 20-11-2026:* `tests/test_hygiene.py`: alles compileert, geen ongebruikte import (`# noqa` op de regel laat er een staan); gecontroleerd met een losse `import os`.

- [x] **A3 — De tests vanzelf laten draaien op GitHub.** *Eerst vragen aan de
  eigenaar:* dit voegt een bestand `.github/workflows/tests.yml` toe en
  gebruikt GitHub Actions.
  *Wat:* bij elke push `pip install -r requirements.txt` en de testopdracht
  uit `CLAUDE.md`. De tests raken het netwerk niet, dus er is geen geheim
  nodig.
  *Klaar als:* een push met een kapotte test een rood kruisje geeft.
  *Gedaan 20-11-2026:* `.github/workflows/tests.yml`: Python 3.13, `pip install -r requirements.txt`, de testopdracht; bij elke push en pull request. Of hij op GitHub groen wordt, zie je na de eerste push onder Actions.

## B. Kleine opruimstappen (elk een uur of minder)

- [x] **B1 — Eén manier om een bedrag te schrijven.**
  *Bevinding:* `report.euro()` en `vinted._euro()` schrijven "€1250",
  `util.euro()` en `dashboard.euro()` schrijven "€1.250"; `dashboard.euro()`
  zet bij een negatief bedrag een minteken vóór het euroteken, `util.euro()`
  niet ("€-5"); `recheck._euro()` zegt "geen prijs" in plaats van "—";
  `flips.euro()` en `dashboard.flip_money()` schrijven centen.
  *Wat:* `util.euro(amount, cents=False, none="—")` met het minteken van
  `dashboard.euro()`, en de zes varianten daarop laten rusten.
  *Let op:* dit verandert wat er op het scherm staat ("€1250" wordt
  "€1.250" in het rapport en de Vinted-tab). Klein, maar zichtbaar: noem het
  in de commit en pas de tests aan die op de oude tekst controleren.
  *Gedaan 20-11-2026:* `util.euro(amount, cents=False, sign=False, none='—')` vervangt `dashboard.euro/signed_euro/flip_money/flip_signed`, `flips.euro`, `report.euro`, `vinted._euro` (en zijn `cents`-lambda) en `recheck._euro`. **Zichtbaar:** in het rapport en de Vinted-tab staat nu "€1.250" i.p.v. "€1250", en in de console "−€5" i.p.v. "€-5". Geen test controleerde op de oude tekst. Bedragen die in een f-string zelf opgemaakt worden (`f'€{x:.0f}'`, tientallen plekken) zijn niet aangeraakt.

- [x] **B2 — Eén manier om een tijdstip te tonen.**
  *Bevinding:* `dashboard.local_time()`, `koopjes.local_time()`,
  `dossier._local()` en `vinted._local()` doen hetzelfde met kleine
  verschillen (met of zonder jaar); `dashboard.nl_date()` en
  `trades` lezen allebei een datum uit de eerste tien tekens.
  *Wat:* `util.local_time(iso, year=True)` en `util.parse_day()`; de vier
  plekken erop aansluiten.
  *Gedaan 20-11-2026:* `util.local_time(value, fmt)` vervangt `dashboard.local_time`, `koopjes.local_time`, `vinted._local` en het rekenwerk in `dossier._local`; `util.parse_day()` vervangt `trades._date` en `flips._date` en zit onder `dashboard.nl_date`. Verschil: een onleesbare tijd toont nu de tekst zelf i.p.v. "?" in het overzicht.

- [x] **B3 — Eén plek die een rij uit `listing` omzet naar een `Listing`.**
  *Bevinding:* `dashboard.py` (r. 490), `racebikes._listing()`,
  `recheck.py` (r. 201) en `upgrade.py` (r. 917) bouwen elk zelf een
  `mp.Listing` uit een databaserij, met elk een eigen `SELECT`-kolomlijst;
  `spares.py` heeft een vijfde `SELECT`. Een nieuwe kolom moet nu op vijf
  plekken bij.
  *Wat:* `racefiets_jev.listing_from_row(row)` plus één constante met de
  kolommen; de vier plekken erop aansluiten, één per commit.
  *Klaar als:* `grep "mp.Listing(" *.py` nog één treffer buiten de tests
  geeft.
  *Gedaan 20-11-2026:* `racefiets_jev.listing_from_row(row, site_specs, places)` (kolommen die de SELECT mist blijven leeg; met de biedkolommen erbij ook `apply_stored_bids()`) vervangt `racebikes._listing()` en de kopieën in `dashboard.load_active_listings()` en `upgrade.fetch_candidate_listings()`; `dossier`, `spares` en `upgrade_test` roepen hem direct aan. `racebikes._listing()` deed `apply_stored_bids()` ook nog eens zelf over. `recheck.py` bouwt zijn Listing uit de advertentiepagina, niet uit een rij: daar hoort hij niet bij. De drie SELECT-kolomlijsten zijn gebleven (ze verschillen bewust: dashboard vangt een database van vóór migratie 11/14 op).

- [x] **B4 — Beslissen over drie functies die alleen een test aanroept.**
  *Eerst vragen aan de eigenaar; dit zijn keuzes, geen opruimwerk.*
  - `valuation.fetch_component_prices()`: de lezer voor E3 (som der delen).
    `valuation.main()` maakt de wielset aan als `Component(label=...)`
    zónder prijzen, dus **E3 telt nu nooit mee**. Aansluiten (dan moet er
    iets de tabel `component_price` vullen) of E3 uit de uitleg halen.
  - `db.export_csv()`: de database terugschrijven naar een referentie-CSV
    (fase 1a). Niets roept het aan. Een commando ervan maken
    (`python db.py export ...`) of weghalen met zijn tests.
  - `valuation.load_owned_items()`: één test gebruikt het om een upsert te
    controleren.
  Ook hier: `views.Latest.views_delta` wordt uitgerekend maar nergens
  getoond, `valuation.CompCandidate.is_bid` wordt gezet maar nooit gelezen,
  en de kolom `listing_mark.note` is leeg sinds migratie 15.
  *Gedaan 20-11-2026:* De eigenaar zei "bouw dit allemaal, met zo min mogelijk code"; mijn keuzes, terug te draaien uit git: **weg** `db.export_csv()` (+ `_format_price`, zes tests: niets riep hem aan, `reference_overview.py` en `check_reference_overlaps.py` lezen de CSV zelf), `valuation.fetch_component_prices()` (en zijn test: niets vult `component_price`, dus aansluiten veranderde niets), `valuation.load_owned_items()` (de test leest de tabel nu zelf), `views.Latest.views_delta`, `CompCandidate.is_bid`. **Blijft:** E3 in `value_subject()` — hij telt niet mee zolang `component_price` leeg is en zegt dat in de bewijsregels (`docs/eigen-fiets.md` zei dat al). De kolom `listing_mark.note` blijft: een kolom laat zich niet terugdraaien (valkuil in CLAUDE.md).

- [x] **B5 — De gedeelde opstart van `valuation.py`, `upgrade.py` en
  `scoring.py`.**
  *Bevinding:* alle drie hebben dezelfde `--db`/`--mijn-fiets`-vlaggen en
  hetzelfde blok "bestand niet gevonden → fout: ..., return 1"; `upgrade.py`
  en `valuation.py` hebben ook hetzelfde SQL-stukje voor `--query` (via
  `listing_query`).
  *Wat:* één functie die de intake inleest en de foutmelding geeft, en één
  voor het queryfilter; de teksten van de meldingen blijven gelijk.
  *Gedaan 20-11-2026:* `valuation.read_owner_bike(path)` geeft (tekst, fiets) of een foutmelding; de drie `main()`'s gebruiken hem, met dezelfde meldingen als voorheen. Het SQL-stukje voor `--query` (twee regels) en de twee argparse-regels zijn gebleven: een functie ervoor is niet korter.

- [x] **B6 — De zes `db.*_TABLES` worden één tabel per migratie.**
  *Bevinding:* `FLIP_TABLES`, `PLACE_TABLES`, `MODEL_TABLES`, `RULE_TABLES`,
  `OFFER_TABLES`, `LABEL_TABLES` bestaan alleen zodat drie tests een database
  kunnen terugzetten, en elke test telt ze zelf op.
  *Wat:* `db.TABLES_BY_MIGRATION = {17: (...), 18: (...), ...}` en in
  `tests/helpers.py` één `roll_back_to(conn, version)`; de drie tests
  gebruiken die. Werk de valkuil in `CLAUDE.md` bij.
  *Gedaan 20-11-2026:* Korter dan gepland: de migraties zijn SQL-tekst, dus `tests/helpers.roll_back(conn, versie)` leest de `CREATE TABLE`-namen er zelf uit. De zes tuples zijn weg uit `db.py`; een nieuwe migratie hoeft nergens meer bij. Valkuil in CLAUDE.md bijgewerkt. (`opdrachten/` noemt de tuples nog: dat zijn afgeronde opdrachten, niet bijgewerkt.)

- [x] **B7 — De twee `load_...`-lussen in `racebikes.py`.**
  *Bevinding:* `load_listings()` en `load_pool()` lopen allebei over dezelfde
  rijen met hetzelfde filter op `last_seen`.
  *Wat:* een kleine generator `_recent_rows(rows, since)`.
  *Gedaan 20-11-2026:* `racebikes._recent(read, rows, days)` geeft de nieuwste waarneming en de (rij, Listing)-paren binnen het venster; `load_listings()` en `load_pool()` zijn er twee korte functies op geworden.

## C. Structuur (elk een eigen sessie, in deze volgorde)

- [x] **C1 — De kring van imports doorknippen.**
  *Bevinding:* bijna alles importeert `racefiets_jev` voor de dataclass
  `Listing` en een paar leesfuncties, en `racefiets_jev` importeert zelf
  `report`, `upgrade` en `computers`. Daardoor staan er imports binnen
  functies in 14 modules en kan een onschuldige import bovenaan een module de
  boel bij het starten laten vastlopen.
  *Wat, in drie commits:*
  1. **C1a** `Listing` en wat er direct bij hoort (de dataclass, de
     constanten van prijstypes, `spec_text()`, `category_from_url()`) naar
     een nieuw bestand `listing.py` dat niets uit de repo importeert.
     `racefiets_jev` importeert ze daaruit en blijft ze onder dezelfde naam
     aanbieden (`mp.Listing` blijft werken), dus geen andere module hoeft
     mee.
  2. **C1b** de modules die alleen `Listing` nodig hebben (`marks`,
     `distance`, `views`, `spares`, `bike_comps`, ...) stap voor stap
     omzetten naar `import listing`.
  3. **C1c** kijken welke imports-binnen-functies daarna naar boven kunnen.
  *Klaar als:* `python -c "import <module>"` voor elke module werkt in elke
  volgorde, en het aantal imports binnen functies is gedaald (nu 14 modules).
  *Gedaan 20-11-2026:* Anders dan gepland: op topniveau bleek er al geen kring te zijn; hij liep alleen via 28 imports binnen functies, en `Listing` naar `listing.py` verplaatsen haalde daar geen enkele van weg. Daarom (C1a) de opgeslagen upgraderegel van `upgrade_test.py` naar `upgrade.py` (`upgrade` en `report` hingen daardoor niet meer onder `upgrade_test` → `dashboard`), en (C1b) elke import binnen een functie die zonder kring naar boven kon, naar boven: nog 7 in 5 modules (was 28 in 14). Over: `racefiets_jev → report/upgrade` (het rapport, C3), `racebikes/upgrade_test → dashboard` (de gedeelde paginaschil, C2), `watches/koopjes → dashboard` (hun commando bouwt het dashboard: zo hoort het).

- [x] **C2 — `dashboard.py` (4.500 regels) per pagina opdelen.**
  *Bevinding:* één bestand bevat de twee dashboards, de startpagina, de
  pagina `/fiets`, de hele pagina `/flips` (HTML, CSS, JavaScript én de
  acties), de cache en de webserver.
  *Wat, één pagina per commit, steeds alleen verplaatsen:*
  1. **C2a** `/flips` → `flips_page.py` (`FLIPS_CSS`, `FLIPS_JS`, de
     `flip_action_*`-functies, het renderen).
  2. **C2b** `/fiets` → bij `bike_comps.py` of een eigen `bike_page.py`.
  3. **C2c** de startpagina en `/bestanden/` → `start_page.py`.
  4. **C2d** `DashboardHandler` krijgt een tabel `{pad: functie}` in plaats
     van de lange `if`-ketens in `do_GET`/`do_POST`.
  *Let op:* `koopjes.py`, `racebikes.py`, `upgrade_test.py` en `watches.py`
  gebruiken namen uit `dashboard`; laat die namen daar bestaan (opnieuw
  aanbieden) tot alles om is.
  *Klaar als:* `dashboard.py` onder de 2.000 regels zit en test A1 groen is.
  *Gedaan 20-11-2026:* `dashboard.py` van 4.500 naar 1.566 regels, alles letterlijk verplaatst (een script dat definities verhuist en elke verwijzing bijwerkt): `pages.py` (paden, balk bovenaan, gedeelde CSS/JS, formulieren — zonder dit importeerden pagina's en dashboard elkaar), `flips_page.py`, `bike_page.py`, `start_page.py`, en verder dan gepland `server.py` (de webserver, `LiveCache`, de acties): `dashboard.py` is nu alleen de dashboards per markt; `python dashboard.py --serve` werkt als voorheen. C2d: `do_POST` leest het formulier één keer en kiest uit een routetabel (was zeven keer hetzelfde blok); `do_GET` is zo gelaten — 55 leesbare regels, een tabel was niet korter. Gecontroleerd: alle pagina's geven op een verse database exact dezelfde bytes als op 16-11.

- [x] **C3 — `racefiets_jev.py` (3.700 regels) in lagen.**
  *Wat, één laag per commit:* ophalen en parsen van zoekpagina's
  (`collect_listings` en wat erbij hoort) → `crawl.py`; de dealscore →
  `dealscore.py`; de console-tabellen → `console.py`; het HTML-rapport
  (`render_html`) → naar `report.py`. `racefiets_jev.py` blijft het
  commando met alle vlaggen (`parse_args`, `main`, `run_for_query`) en blijft
  de oude namen aanbieden.
  *Na C1.* *Klaar als:* elke vlag uit `docs/zoeken.md` nog werkt (de
  bestaande tests in `test_crawl.py`, `test_parsing.py`, `test_report.py`
  dekken dat) en één echte pagina nog te halen is.
  *Gedaan 20-11-2026:* `racefiets_jev.py` van 3.700 naar 1.420 regels: `crawl.py` (Marktplaats lezen, 1.800), `dealscore.py`, `console.py`, en het HTML-rapport naar `report.py`. Geen oude namen opnieuw aangeboden: elke verwijzing (`mp.detect_groupset` enz., ook `patch.object(mp, ...)` in de tests) wijst nu naar de nieuwe module. Daarmee is de laatste kring weg: `report` en `upgrade` hangen niet meer onder `racefiets_jev`, dat ze nu bovenaan importeert. Gecontroleerd: tests, elke `--help`, één echte pagina `luidsprekers`.

- [x] **C4 — CSS en JavaScript uit de Python-strings naar eigen bestanden.**
  *Bevinding:* ruim 1.700 regels, waarvan ruim 1.400 JavaScript. Geen editor
  kleurt het, geen gereedschap controleert het, en een tikfout zie je pas in
  de browser. Het rapport doet het al goed: `report_template.html`.
  *Wat, één pagina per commit:* `static/racefietsen.js` + `.css`,
  `static/upgrade.js` + `.css`, `static/dashboard.js` + `.css`,
  `static/flips.js` + `.css`. De module leest het bestand bij het starten in
  en zet het in de pagina zoals nu (dus het geschreven `dashboard.html`
  blijft één los bestand).
  *Let op:* de strings bevatten soms plekken die Python invult; zoek per
  bestand eerst uit hoe (`.replace()`, f-string, `%`).
  *Klaar als:* `node --check static/*.js` slaagt (alleen om te controleren,
  geen dependency van het programma) en de pagina's er in de browser
  hetzelfde uitzien.
  *Gedaan 20-11-2026:* Dertien strings (1.809 regels, waarvan 1.430 JavaScript) staan nu in `static/` (`pagina.css/js`, `live.js`, `balk.css`, `racefietsen.css/js`, `upgrade.css/js`, `flips.css/js`, `fiets.js`, `start.js`, `overzicht.css`); `pages.static()` leest ze bij het starten. Er werd niets in ingevuld, dus de pagina's zijn byte voor byte gelijk gebleven (gecontroleerd: alle zeven live pagina's en `dashboard.html` op een verse database). `node --check` slaagt op alle bestanden en draait nu ook in GitHub Actions.

- [ ] **C5 — De langste functies opknippen.**
  `dossier.build` (247 regels), `koopjes.render_overview` (199),
  `valuation.value_subject` (196), `racefiets_jev.collect_listings` (182),
  `racefiets_jev.run_for_query` (169). Eén functie per sessie; alleen
  opknippen in benoemde stukken, geen gedrag veranderen.

- [ ] **C6 — `db.py` (1.930 regels): migraties en queries uit elkaar.**
  *Wat:* de lijst `MIGRATIONS` met het schema naar `db_schema.py`; `db.py`
  houdt `connect()`, `connect_readonly()` en de queries, en biedt de oude
  namen aan. *Lage prioriteit:* het bestand is groot maar eenduidig.

## D. Documentatie

- [ ] **D1 — Eén logboek, één lijst met ideeën.**
  *Bevinding:* wat er gebouwd is staat op drie plekken: §12 van
  `PLAN_FIETSWAARDE.md` (regels van duizenden tekens), `NEXT_STEPS.md` (400
  regels, deels dezelfde gebeurtenissen) en `opdrachten/weekend.md`. Het
  blokje "Lees dit eerst" bovenaan het plan noemt nog 87 tests en een branch
  die niet meer bestaat.
  *Wat:* `LOGBOEK.md` (per datum, kort: wat, waarom, wat bleef liggen) en
  `NEXT_STEPS.md` terug naar wat de naam zegt: de open ideeën en "wat we
  leerden over Marktplaats". Het plan zelf blijft zoals het is, met bovenaan
  één regel dat alle fases af zijn.
  *Let op:* alleen verplaatsen en inkorten; de metingen (aantallen, datums)
  niet weggooien.

- [ ] **D2 — De pagina's in `docs/` vertalen en inkorten, één per sessie.**
  *Bevinding:* ze zijn Engels (zo is de README gegroeid), de rest is
  Nederlands; en ze vertellen de geschiedenis mee ("since 02-10-2026 ...").
  *Wat per pagina:* naar het Nederlands, de geschiedenis naar het logboek
  (D1), en bovenaan een kort "zo gebruik je het". Volgorde naar gebruik:
  `rondes.md`, `racefietsen.md`, `dashboards.md` (de langste: 546 regels,
  eerst splitsen in computers/horloges en "wat alle pagina's delen"),
  `flips.md`, `eigen-fiets.md`, `rapport.md`, `zoeken.md`,
  `referentiedata.md`, `database.md`.
  *Let op:* geen getal of vlag veranderen zonder het in de code na te gaan.

- [ ] **D3 — `docs/architectuur.md` naast de code leggen.**
  *Bevinding:* de tekst komt uit de oude tabel in `CLAUDE.md` en is op 16-11
  niet regel voor regel nagelopen.
  *Wat:* per bestand controleren of de genoemde functies, tabellen en
  migratienummers nog bestaan (`grep`), en de alinea's van `dashboard.py` en
  `racebikes.py` opknippen in leesbare punten.

- [ ] **D4 — De hoofdmap opruimen.** *Eerst vragen aan de eigenaar.*
  *Bevinding:* ruim 60 bestanden in de hoofdmap, code en documenten door elkaar.
  *Mogelijk:* de documenten over de eigen fiets naar `fiets/`. Dat raakt
  `--mijn-fiets` (standaard `mijn_fiets.md`), `SERVED_FILES` in
  `dashboard.py` (`taxatie_*.md`) en verwijzingen in `opdrachten/`; daarom
  een eigen stap en niet zomaar.

## E. Later, als het zin heeft

- [ ] **E1 — De oude bestanden naast de database.** Een ronde schrijft nog
  steeds `seen_listings.json`, `bargains_log.csv` en
  `reference_price_history.csv` náást `koopjes.db`. Uitzoeken wat ze nog
  leest; daarna met de eigenaar beslissen of ze kunnen vervallen. Raakt
  vlaggen uit `docs/zoeken.md` (`--history-file`, `--log-file`,
  `--price-history-file`), dus niet zonder overleg.
- [ ] **E2 — Vastleggen welke Python-versie nodig is.** Op 16-11 getest met
  3.13; welke versie de eigenaar draait en wat de ondergrens is staat
  nergens.
- [ ] **E3 — `catalog_tools/` en `marktonderzoek/`.** Losse meetscripts in
  een compacte stijl, zonder tests. Ze hebben hun werk gedaan; laten zoals ze
  zijn tenzij er opnieuw gemeten moet worden.

## Niet doen

- Geen framework, geen build-stap, geen database-server: het programma is
  bewust één map met Python en SQLite.
- Geen herschrijving in één keer. Elke stap hierboven verplaatst of voegt
  samen; gedrag verandert alleen waar het erbij staat.
- Geen test weghalen om een stap passend te maken.
