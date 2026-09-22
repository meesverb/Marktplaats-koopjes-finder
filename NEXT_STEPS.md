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
- `reference_prices.csv` bevat 43 luidsprekermodellen (onderzocht per
  prijssegment €0-25 t/m €75-100 nog bezig) en 5 fietsmodellen.
- Hulpscripts: `check_hifi_brand.py` (merken-index opzoeken),
  `check_reference_overlaps.py` (patroon-conflicten checken),
  `reference_overview.py` (doorbladerbaar overzicht van de database).
- HTML-rapport heeft filtertabs: Alles / Nieuw / Koopjes / Beter dan
  referentie / Prijsverlaging.

## Actief plan

`PLAN_FIETSWAARDE.md` is het uitgewerkte werkplan voor de eerstvolgende
uitbreiding: taxatie van de eigen fiets (Giant Defy 2012) + een upgrade-finder
die laat zien welke betere fiets daarvoor te koop staat, biedadvertenties
meegerekend. Dat plan neemt de twee punten hieronder in zich op (de deal-score
wordt de kwaliteits- + dealscore uit §7, de bied-focus wordt het Bieden-paneel
uit §8) en beschrijft de overstap van losse CSV's naar SQLite. Begin daar.

## Gevraagde vervolgstappen (nog niet gebouwd)

1. **Score per deal.** Nu heb je losse signalen (% van mediaan, "beter dan
   referentie" ja/nee, prijsdaling ja/nee, 2e-hands gemiddelde). Idee: één
   samengestelde score per advertentie die deze signalen combineert tot een
   enkel getal/label, zodat je in één oogopslag ziet wat de beste deal is
   zonder zelf de losse kolommen te wegen. Nog te beslissen: welke
   signalen wegen hoe zwaar, en hoe dat overzichtelijk tonen (kolom? sortering
   standaard op score?).

2. **Focus op bied-advertenties (FAST_BID/MIN_BID).** Het script haalt al
   het minimumbod/huidige bod op voor FAST_BID-advertenties (zie
   `enrich_fast_bid_listings` / `--no-bid-lookup`). Gevraagd: dit
   prominenter maken — bijv. een apart overzicht/filter van "nog vrij te
   bieden" advertenties, met wat het minimumbod is en hoe dat zich
   verhoudt tot de mediaan/referentieprijs.

## Losse eindjes uit eerdere gesprekken

- Luidsprekers-onderzoek is gedaan t/m €100 (segmenten €0-25, €25-55,
  €55-75 volledig; €75-100 crawl was klaar maar nog niet allemaal
  opgezocht). Verder omhoog (>€100) nog niet gestart.
- Fietsen-kant van `reference_prices.csv` heeft nog maar 5 modellen
  (alleen top-segment) — dezelfde prijssegment-aanpak zou daar ook waarde
  toevoegen, was nog niet opgepakt.
