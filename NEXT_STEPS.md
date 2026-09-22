# Volgende stappen

Notities voor een vervolgsessie — waar we nu staan en wat er nog gepland is.
De code, `reference_prices.csv` en de git-geschiedenis (commit messages)
bevatten de volledige context; dit bestand is alleen een korte routewijzer
zodat een nieuwe sessie niet bij nul hoeft te beginnen.

## Waar we nu staan

- `racefiets_jev.py`: generieke Marktplaats-scraper (elke `--query`), met
  fiets-specifieke features (framemaat, groupset-herkenning) en een
  referentiedatabase-systeem (`reference_prices.csv`) dat advertenties
  herkent en vergelijkt met bekende modellen — nieuwprijs, specs, of het
  beter is dan een baseline, en een zelf-groeiende "2e-hands gemiddeld"
  prijs uit eigen crawl-historie.
- **Dealscore**: elke advertentie krijgt één getal van 0-100 dat alle
  prijssignalen combineert (% van mediaan, % van 2e-hands gemiddelde, % van
  nieuwprijs, plus bonussen voor prijsdaling en beter-dan-referentie).
  Console en HTML zijn erop gesorteerd, er is een `Topdeals`-tab, en bij
  elke score staat welke signalen erin zaten. Zie README → "Dealscore" voor
  de weging en wat de score expliciet *niet* zegt.
- **Bied-advertenties**: aantal biedingen en het echte minimumbod worden
  opgehaald (`--bid-lookup fast|all|none`), advertenties waar nog niemand op
  geboden heeft krijgen een `VRIJ TE BIEDEN`-badge en eigen filtertab, en
  elke run print een `BIED-OVERZICHT`. `--bids-only` beperkt het rapport tot
  bied-advertenties, `--min-score` tot een minimale dealscore.
- `reference_prices.csv` bevat 43 modellen, allemaal luidsprekers
  (onderzocht per prijssegment €0-25 t/m €75-100 nog bezig). Let op: een
  eerdere versie van dit bestand claimde dat er ook 5 fietsmodellen in
  stonden — dat klopt niet, er staat geen enkele fiets in.
- Hulpscripts: `check_hifi_brand.py` (merken-index opzoeken),
  `check_reference_overlaps.py` (patroon-conflicten checken),
  `reference_overview.py` (doorbladerbaar overzicht van de database).
- HTML-rapport heeft filtertabs: Alles / Nieuw / Koopjes / Beter dan
  referentie / Prijsverlaging / Topdeals / Bieden / Vrij te bieden.

## Actief plan

`PLAN_FIETSWAARDE.md` is het uitgewerkte werkplan voor de eerstvolgende
uitbreiding: taxatie van de eigen fiets (Giant Defy 2012) + een upgrade-finder
die laat zien welke betere fiets daarvoor te koop staat, biedadvertenties
meegerekend, plus de overstap van losse CSV's naar SQLite. Begin daar, en pak
één fase per sessie.

Let op bij het lezen van dat plan: het is geschreven toen de dealscore en het
bied-overzicht nog niet bestonden. Die zijn er inmiddels (zie hierboven), dus
fase 4, 5 en 7 bouwen daarop voort in plaats van ze te maken. Het plan zelf is
daarop bijgewerkt; deze noot staat er voor het geval je een oudere kopie leest.

## Wat we onderweg leerden over Marktplaats

- Bij een `MIN_BID`-advertentie is de prijs uit de zoekresultaten de
  **vraagprijs**, niet het minimumbod. Het bod dat Marktplaats echt accepteert
  staat alleen op de advertentiepagina zelf en ligt er vaak flink onder
  (gezien: vraagprijs €200 / minimumbod €120, vraagprijs €47,50 /
  minimumbod €35). Daarom blijft de vraagprijs de prijs waarop gefilterd en
  gescoord wordt — anders lijken bied-advertenties goedkoper dan
  vaste-prijs-advertenties puur omdat er geboden mag worden — en staat het
  minimumbod apart in de `Bod`-kolom.
- Soms zet Marktplaats het minimumbod één cent onder de vraagprijs (€174,99
  op een advertentie van €175). Dat is geen korting, dus die wordt niet als
  zodanig getoond (`MEANINGFUL_MINIMUM_BID_RATIO`).

## Mogelijke vervolgstappen

1. **Score kalibreren op echte data.** De weging en de "best/worst"-ratio's
   (`SCORE_*_RANGE` bovenin het scoreblok) zijn met de hand gekozen op wat
   redelijk voelt, niet afgeleid uit verkoopdata. Als `bargains_log.csv` en
   `reference_price_history.csv` eenmaal flink gevuld zijn, valt na te gaan
   of de dingen die je echt gekocht (of achteraf gemist) hebt ook hoog
   scoorden, en de getallen daarop bij te stellen.
2. **Notificatie op topdeals.** Nu gaat het belletje alleen af bij een nieuwe
   match die `better_than_baseline` is (`notify_better_matches`). Een score-
   drempel zou een logischer trigger zijn, want die werkt ook voor modellen
   die niet in `reference_prices.csv` staan.
3. **Luidsprekers >€100.** Onderzoek is gedaan t/m €100 (segmenten €0-25,
   €25-55, €55-75 volledig; €75-100 crawl was klaar maar nog niet allemaal
   opgezocht). Verder omhoog nog niet gestart.
4. **Fietsen-referenties.** `reference_prices.csv` bevat nog geen enkel
   fietsmodel — dezelfde prijssegment-aanpak als bij luidsprekers zou daar
   ook waarde toevoegen. Dit is fase 7 van `PLAN_FIETSWAARDE.md` (op `main`).
   Neem daarbij mee wat de taxatie van 22-09 opleverde: verkopers schrijven
   nooit "Composite", maar "Defy Advanced" of "Defy carbon" — daar moeten de
   patronen op passen.
5. **Kleinigheid**: de HTML-titel is nog hardcoded "Racefiets koopjes", ook
   bij `--query luidsprekers`.
