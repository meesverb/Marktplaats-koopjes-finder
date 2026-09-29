# Volgende stappen

Notities voor een vervolgsessie — waar we nu staan en wat er nog gepland is.
De code, `reference_prices.csv` en de git-geschiedenis (commit messages)
bevatten de volledige context; dit bestand is alleen een korte routewijzer
zodat een nieuwe sessie niet bij nul hoeft te beginnen.

## Laatste ronde (27-09-2026)

Op echte data gecontroleerd en bijgewerkt; details per stap onderaan §12 van
`PLAN_FIETSWAARDE.md`. Kort: `verkoopprijs_handmatig` = 390 (fietsdeel van
scenario B); MIN_BID-vraagprijzen tellen mee in de taxatie; een crawl die
bijna compleet was noteert gemiste advertenties in plaats van de sweep over te
slaan; framemateriaal/remtype uit de Marktplaats-kenmerken; `--detail-lookup`
haalt de volledige omschrijving op voor kanshebbers binnen budget; het
Biedpaneel waardeert op vergelijkbare fietsen. Open: bouwjaar in de segmenten,
en per segment de prijzen van snel verdwenen advertenties zodra de sweep een
paar weken data heeft.

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
- Fietsen staan sinds fase 7 in eigen bestanden: `reference_bikes.csv`
  (Defy-familie + upgradedoelen) en `reference_bike_accessories.csv`
  (fietscomputers, powermeters), elk met een `source_url` per rij. Gebruik
  ze met `--reference-file`; zie README → "Bikes have their own reference
  files".
- `reference_bike_catalog.csv` is iets anders: een catalogus met één rij per
  merk/model/modeljaar (Giant, Trek, Cube, Sensa en via bikezona.com ook
  andere merken), met specs, nieuwprijs en bron. Geen referentiebestand: met
  `--reference-file` waarschuwt het script en herkent het niets. Alleen de
  merkkolom wordt gelezen (slapers, lijst niet-herkende advertenties); specs
  en nieuwprijzen gebruikt de taxatie nog niet. Zie README → "Bike
  catalogue". Opgebouwd met `catalog_tools/`.
- Hulpscripts: `check_hifi_brand.py` (merken-index opzoeken),
  `check_reference_overlaps.py` (patroon-conflicten checken),
  `reference_overview.py` (doorbladerbaar overzicht van de database).
- HTML-rapport heeft filtertabs: Alles / Nieuw / Koopjes / Beter dan
  referentie / Prijsverlaging / Topdeals / Bieden / Vrij te bieden.

## Taxatie: wat er nu al kan

`valuation.py` taxeert de fiets uit `mijn_fiets.md` op de advertenties in
`koopjes.db` (fase 3). Om er echt iets uit te krijgen moet die database eerst
comps bevatten:

```bash
python racefiets_jev.py --query "giant defy" --pages 0
python valuation.py --db koopjes.db
```

Zonder vergelijkbare advertenties komt er met opzet géén bedrag uit. Wat er
nog ontbreekt om de taxatie compleet te maken staat bij fase 3 in §12 van het
plan: verdwijn-historie voor de gemeten E2-factor, en componentprijzen voor E3
en voor het verschil tussen scenario A en B.

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
- Op een `MIN_BID`-advertentie kan al **boven de vraagprijs** geboden zijn
  (29-09-2026: Suunto Vertical 2, vraagprijs €290, vier biedingen tot €350).
  Dat staat alleen op de advertentiepagina; de zoekresultaten zeggen €290.
- Of een advertentie **gereserveerd** is, staat in de zoekresultaten
  (`reserved`) én op de advertentiepagina (`isReserved`). Een **verdwenen**
  advertentie geeft op zijn eigen URL 410 (29-09-2026).
- Het dashboard is zo oud als de laatste ronde die de advertentie zag;
  overdag is dat voor alles buiten de nieuwste 2 pagina's de nachtronde. De
  knop **controleer** in `dashboard.py --serve` (`recheck.py`, sinds
  29-09-2026) haalt één advertentie op verzoek opnieuw op. Bewust niet
  automatisch per ronde: met ~190 horlogeflips zou dat ~190 verzoeken per
  ronde extra zijn. Blijkt de knop te vaak nodig, dan is een tussenweg alleen
  de nieuwe flips natrekken voordat het dashboard erover opent.

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
4. **Fietsen-referenties uitbreiden.** Fase 7 is gedaan: fietsen staan in
   `reference_bikes.csv` (Defy-familie + upgradedoelen), niet in
   `reference_prices.csv`. Uitbreiden met modellen die vaak voorbijkomen
   helpt de eerste trede van de Biedpaneel-waarde. Let op wat de taxatie van
   22-09 opleverde: verkopers schrijven zelden "Composite", maar "Defy
   Advanced" of "Defy carbon".
5. **"(elektronisch)" bij een groepset die pas een zin later Di2 noemt.** De
   tag eist nu dat Di2/eTap/AXS in dezelfde zinsnede staat als de
   groepsetnaam én van hetzelfde merk is, zodat "Shimano 105, Di2-upgrade
   mogelijk" geen elektronische 105 meer oplevert. Daarmee mist hij wel een
   advertentie die de groepset en de Di2 in losse zinnen noemt, en
   "Di2-upgrade uitgevoerd" (wél elektronisch) is nog steeds niet te
   onderscheiden van "Di2-upgrade mogelijk". Dat is te beslissen met de ~50
   echte advertentieteksten die fase 2 in `tests/fixtures/` verzamelt — niet
   met meer giswerk over hoe verkopers het opschrijven.
6. **Nog te verifiëren aan een echte advertentie**: of Marktplaats'
   `currentMinimumBid` op een advertentie waar al geboden is écht onder het
   hoogste bod kan liggen, of dat het dan simpelweg het eerstvolgende
   toegestane bod is. De code gaat van het eerste uit (`resolve_bid_price`
   pakt het hoogste bod, `format_bid_info` toont het minimum ernaast). Kijk
   één keer op een lopende bied-advertentie met biedingen en noteer het hier
   — niet gokken, dit soort details staat nergens gedocumenteerd.
7. **Vinted naast Marktplaats** (`vinted.py`, tab Vinted, sinds 28-09-2026).
   De eigenaar maakt zelf een export van een Vinted-zoekopdracht; het script
   haalt niets op. Nog niet gemeten, dus nu aannames: de afdingfactor op
   Vinted (er wordt gerekend met de vraagprijs, zonder bod) en de verzending
   uit het buitenland (€4,50 is NL; de export zegt niet uit welk land). Een
   advertentie die uit een latere export wegvalt is níet als verkocht
   gemarkeerd; wie verkoopsnelheid op Vinted wil meten, moet eerst weten of
   twee exports dezelfde zoekopdracht volledig dekken.
8. **Sporthorloges als tweede markt** (sinds 28-09-2026, compleet zoals de
   fietscomputers): zoekopdracht `sporthorloges` ("garmin" in sporthorloges,
   smartwatches en activity-trackers) in de nacht- en overdagronde, sinds
   29-09-2026 ook `polar`, `suunto` en `coros` (alleen 's nachts),
   `dashboard_horloges.html` (Flips, Mijn flips, Alle horloges,
   Marktprijzen, Patronen, Uitgefilterd), live op `/horloges` met
   `dashboard.py --serve`, eigen aankopen per markt (migratie 10). 81
   Garmin-modellen (1263 van 1707 titels herkend) en 50 van Polar, Suunto en
   Coros (192 van 327). Waar je na een paar weken
   naar kijkt, en wat nog open ligt:
   - **De afdingfactor.** 0,875 is voor horloges niet gemeten; de tab
     Patronen van het horlogedashboard meet hem vanaf 20 snel verdwenen
     advertenties. Wijkt hij af, dan hoort er een eigen factor per markt bij
     (nu delen beide markten `computer_scoring.json`).
   - **Varianten in één rij** (5/5S, Solar, Sapphire, 43/47/51 mm, MARQ-edities).
     Sinds 29-09-2026 rekent een flip eerst met dezelfde uitvoering zoals de
     titel die noemt (`computers.title_variant()`), vanaf 3 advertenties;
     anders met het hele model. Zie je nog valse flips bij één model, kijk
     dan of de titels een variantwoord hebben dat er nog niet in staat
     (`VARIANT_WORDS`). Mijn flips en de modelrij in Marktprijzen rekenen nog
     per model: een eigen aankoop heeft geen titel, alleen een model.
   - **Geen bron gevonden** voor Tactix (7, 8, Delta), Quatix, Approach
     S12/S42/S70, Descent Mk3/G1 en Vivomove HR/Style: die staan als
     "horloge, model onbekend" in Alle horloges.
   - **Biedopvragingen voor alle horloges** (`"bid_lookup": "fast"`, op
     verzoek van de eigenaar: biedadvertenties zijn belangrijk): 's nachts
     ~370 extra verzoeken, overdag ~15 per ronde. Het bod blijft staan tot
     de volgende opvraging (migratie 11). Loopt de nachtronde daardoor te
     lang uit, dan is de volgende stap een bod dat minder dan N uur oud is
     niet opnieuw op te halen (`bids_checked_at` staat er al voor).
   - **Geen bron opgezocht** voor oudere Polar (M400, V800, M600, A360,
     RC3), Suunto (Core, Traverse, Ambit 1/2) en de Coros Apex Pro; de
     Polar Loop staat er bewust niet in (de Loop van 2025 en de Loop 2 van
     2015 heten op Marktplaats allebei "Loop gen 2"). Die staan als
     "horloge, model onbekend".
   - **Smartwatches** (Apple, Samsung, Fitbit, Huawei) zijn een andere markt
     en worden niet gevolgd (de eigenaar, 29-09-2026: eerst alleen de
     sporthorloges). Gemeten op 28-09-2026 in dezelfde drie categorieën:
     Apple Watch ~4875 advertenties (net onder de grens van ~5000 per
     zoekopdracht, dus per categorie splitsen), Samsung Galaxy Watch ~2750,
     Fitbit ~445, Huawei ~295. Wahoo Rival (10) en TomTom (29) zijn te klein.
