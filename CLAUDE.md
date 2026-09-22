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
python -m unittest discover -s tests -t tests    # 135 tests, moet groen zijn
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
- **`HTML_TEMPLATE` is een `.format()`-string** met verdubbelde accolades
  `{{ }}`. Er JavaScript met object-literals in schrijven is foutgevoelig.
  Fase 6 van het plan haalt hem daarom uit het script.
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
| `db.py` | SQLite-schema, migraties, import van de oude bestanden, CSV-export; sinds fase 1b aangesloten op het script (`--db`/`--no-db`) |
| `tests/` | stdlib-unittests; `helpers.py` heeft `make_listing()` en een `FakeSession` |
| `PLAN_FIETSWAARDE.md` | actief werkplan, gefaseerd |
| `mijn_fiets.md` | intake van de eigen fiets (brondocument voor de taxatie) |
| `NEXT_STEPS.md` | stand van zaken en losse eindjes |
| `reference_prices.csv` | handmatig onderzochte modellen (43, alleen luidsprekers) |
| `check_hifi_brand.py`, `check_reference_overlaps.py`, `reference_overview.py` | hulpscripts bij het onderhouden van die database |
