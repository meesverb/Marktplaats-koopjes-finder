# Logboek

Wat er per keer gebouwd is, nieuwste eerst: waarom, wat het meet en wat bleef
liggen. De metingen aan Marktplaats staan erbij met hun datum. Per fase van
het productplan staat het logboek in `PLAN_FIETSWAARDE.md` §12; voor het
opruimen van de code in `VERBETERPLAN.md`. Open ideeën en wat we over
Marktplaats leerden: `NEXT_STEPS.md`.

## Opruimen en lagen (16 en 20-11-2026)

Dode en dubbele code weg, de README per onderwerp naar `docs/`, en de code
in lagen zonder importkring (`crawl`, `pages`, `server`, `static/`, ...).
Alles per stap, met wat bleef liggen: `VERBETERPLAN.md`.

## Upgradetest (05-10-2026)

Op `/upgrade` bepaal je zelf wat een upgrade is: per fiets ja/nee/twijfel,
de uitslag (hoeveel de regel goed heeft, en waar jullie het oneens zijn),
alle knoppen van de score met meteen het effect, een zoekknop voor de regel
die het best bij je oordelen past, en de uitdraai van alle fietsen (ook als
CSV). Opgeslagen werkt de regel overal. Opdracht en logboek:
`opdrachten/upgradetest.md`.

**Te doen door jou:** een stuk of 30-50 fietsen beoordelen (meer is beter;
ook de laag gewaardeerde komen langs), dan Zoek, kijken of de voorgestelde
regel klopt met je gevoel, en opslaan.

**Voorstel, niet gebouwd — bikereviews.** Kort bekeken (05-10-2026):
- BikeRadar geeft 0-5 sterren en weegt daarin uitdrukkelijk de prijs en de
  concurrenten van dat moment mee
  ([uitleg](https://www.bikeradar.com/news/our-review-ratings-explained)):
  4 sterren voor een fiets uit 2012 en 4 voor een uit 2022 zeggen niet dat
  ze even goed zijn.
- road.cc geeft een cijfer per uitvoering: de TCR Advanced Pro 0 (2016)
  kreeg 9/10 ([review](https://road.cc/content/review/174726-giant-tcr-advanced-pro-0)),
  maar op Marktplaats staat vaker een TCR Advanced 2 of 3, waar geen review
  van is.
- Voor de Defy Composite 2012 is er geen vakreview gevonden, alleen
  gebruikersreviews met een handvol stemmen (roadbikereview.com: 4,3/5 uit 4,
  [link](https://products.roadbikereview.com/product/latest-bikes/road-bike/giant/defy-composite-2.html)).
- Een advertentie aan de juiste review koppelen is hetzelfde probleem als
  het model herkennen (uitvoering en jaar staan zelden in de titel), en
  automatisch ophalen zijn verzoeken naar andere sites.

Daarom geen cijfer in de score. Wat wel kan, met de hand en met bron: een
kolom `review` (bron, cijfer, schaal, uitvoering, datum) in
`reference_bike_catalog.csv`, getoond op de kaart als informatie ("road.cc
9/10, Pro 0 2016") — niet meegeteld. Wat de score wél beter maakt dan
reviews: de klasse van het frame (Advanced/Pro/SL staat in de modelnamen
van de catalogus) en het gewicht (`weight_kg`, waar de catalogus het heeft).

## Weekendwerk (02/03-10-2026)

De eigenaar was weg; de werklijst, zijn keuzes en een logboek per punt staan
in **`opdrachten/weekend.md`**. Alles staat op de branch
`claude/claude-fietsmodellen-stap-1-80kp1n`, niet in `main`. Gebouwd:
fietsmodellen stap 2 F (regels leren, migratie 20) en G (bouwjaar ophalen,
`year_budget`), aanbiedingen per onderdeel op /flips (migratie 21), het
prijsonderzoek voor de Cube (`flips_import/cube_prijsonderzoek.md` +
`cube_aanbiedingen.json`, nog in te lezen met `python flips.py bijwerken`),
de reservelijst Onderdelen op /racefietsen (`spares.py`), dezelfde
weergaven op elke pagina (Te beoordelen / Weggezet bij computers en
horloges, Mijn flips op /racefietsen), snel verkocht ook bij computers en
horloges, de fout "database is locked" (WAL-modus), de pagina's op de
telefoon, en daarna kleine verbeteringen: /racefietsen bouwt in 4,1 in
plaats van 6,5 s op en laadt in 0,6 in plaats van 1,7 s (de
vergelijkingslijst komt pas bij openklappen), `u` maakt in Te beoordelen de
laatste markering ongedaan, en een paar fouten (javascript:-links, oneindige
bedragen, spatie opende de verkeerde klapper). Details per commit in het
logboek van weekend.md.

**Nakijken na de eerste rondes:**
- `logs/koopjes.log`: "Bouwjaren opzoeken" — vindt het jaren, geen 403?
- Fietscomputers/horloges: hoeveel modellen hebben al 3 snel verkochte
  (Marktprijzen, kolom Snel verkocht)? Pas dan verandert de schatting.
- `flips_sheets.gs` moet één keer opnieuw in de Sheet geplakt worden voor
  het tabblad Aanbiedingen (SHEETS.md).

**Voorstellen — vragen jouw keuze, dus niet gebouwd:**
- *Meer onderdelen in de reservelijst.* Nu alleen wat de rondes al
  tegenkomen (jouw keuze), dus weinig. Eén zoekopdracht in de categorie
  fietsonderdelen in de nachtronde (1-2 pagina's, `category:
  fietsonderdelen`) zou de lijst vullen; dat zijn 1-2 verzoeken extra per
  nacht.
- *De drempel voor snel verkocht.* 3 snel verkochte (≤ 7 dagen) is
  overgenomen van /racefietsen. Bij de fietscomputers zijn er veel meer
  advertenties per model; na een maand nachtrondes is te zien of 5 beter
  past (Marktprijzen, kolom Snel verkocht, naast Patronen → gemeten
  afdingfactor).
- *Telefoon via de thuiswifi.* De pagina's passen nu op een telefoon, maar
  de server luistert alleen op 127.0.0.1. Op het thuisnetwerk luisteren
  vraagt een wachtwoord in plaats van alleen het token (iedereen op de wifi
  kan anders je biedingen en flips zien en wijzigen).
- *Alle computers sneller sorteren.* Duizenden tabelrijen opnieuw opmaken
  kost de browser 1-2 s; alleen de zichtbare rijen tekenen (zoals de kaarten
  op /racefietsen) maakt dat direct, maar verandert hoe de tabel werkt
  (zoeken met Ctrl+F vindt dan alleen wat getekend is).
- *Wegzetten ongedaan maken in Onderdelen.* De toets `u` maakt op
  /racefietsen de laatste markering ongedaan; in de weergave Onderdelen (een
  tabel, geen kaarten) moet je daarvoor naar Weggezet. Een knop "ongedaan"
  in de melding zou dat op elke pagina kunnen — een nieuwe knop, dus eerst
  vragen.

## Fietsmodellen, stap 1 klaar (01-10-2026)

Opdracht: **`opdrachten/fietsmodellen.md`**. Stap 1 (A t/m E) is gebouwd:

- `bike_identity.py`: uitvoering uit de titel (`variant_of()`), sleutels
  `exact` (model + uitvoering) en `coarse` (merk + model) via `model_key()`
  (zonder spaties en zonder wat tussen haakjes staat), nette namen
  (`pretty_name()`), de eigen koppeling in `identify(listing, link)`, de
  nieuwe trap (minstens 5, anders grover, dan nog eens met 3 "(weinig)") en
  `Pool.replace()`.
- `racebikes.py`: snel verkocht (`sold_fast()`, ≤ 7 dagen of gereserveerd en
  weg) in de pool; schatting = mediaan van ≥ 3 snel verkochte, anders
  vraagprijzen × 0,875; klopt / ander model / nieuw model / bouwjaar /
  ontkoppelen op de kaart (`POST /racefietsen/model`, `apply_model()`,
  `relink()`: alleen die ene fiets opnieuw, ~0,1 s); de weergave Modellen is
  de volledige lijst (`model_list()`, JSON `id='models'`).
- `upgrade.find_upgrades(years=...)`: een zelf ingevuld bouwjaar telt mee in
  het leeftijdsverval.

**Eigen keuze, controleer met de eigenaar:** het referentiemodel gaat níet
voor als de titel meer zegt. In `reference_bikes.csv` zijn een aantal
modellen een vangnet voor een hele lijn ("Trek Domane", "Giant Defy
(overig)"); als die altijd voorgingen, werd "Trek Domane SL6" nooit een eigen
model en klopten de voorbeelden uit de opdracht niet. Een preciezer
referentiemodel ("Giant Defy Composite 1") gaat nog wel voor
(`Identity.name`). Ook houden de familietreden (3, 4, 6) het filter op
materiaal van de oude trap: binnen "Giant Defy" zitten aluminium en carbon.

Stap 2 F (regels leren) is gebouwd op 02-10-2026: `bike_rule` (migratie
20), voorstel na 3 dezelfde correcties bovenaan Modellen, toepassen / nee
(onthouden) / weghalen. `Identity.recognized` is wat de advertentie zelf
zegt; `bike_identity.resolve()` legt koppeling of regel erop zonder de tekst
opnieuw te lezen, zodat een regel ook verdwenen fietsen in de pool raakt.
G (bouwjaar ophalen voor kanshebbers) ook: `python racebikes.py jaar N`,
in `overdag` en `nacht` via `year_budget: 20` (schedule.json). **Nakijken
na de eerste rondes:** staat er in `logs/koopjes.log` "Bouwjaren opzoeken"
met gevonden jaren, en geen 403? Vinden de meeste pagina's geen jaar, dan
is 20 per ronde zonde van de verzoeken; omlaag kan in schedule.json.

## Sneller zonder iets weg te laten (30-09-2026)

Gemeten op een zelfgemaakte database van twee maanden rondes (~36.000
advertenties, ~340.000 prijsregels; het script staat niet in git, de
aantallen komen uit `schedule.json`). Uitvoer vóór en na byte voor byte
vergeleken: dezelfde dashboards, `/racefietsen` en `/fiets`.

- Vergelijkingsprijzen één keer per opbouw (`computers.comparable_rows()`,
  `rows=`): Marktprijzen las ze bij elke paginaweergave opnieuw.
- Herkenning onthouden per tekst: `classify_title()` (per catalogus-tuple),
  `listing_category()`, `extract_specs()`, `detect_groupset()`.
- Alle computers/horloges laadt live pas bij openen (`LAZY_PANELS`,
  `/paneel`); het geschreven dashboard.html is ongewijzigd compleet.
- `racefiets_jev.apply_stored_bids()`: de biedregels bij het teruglezen uit
  de database stonden twee keer (dashboard en /racefietsen).

Niet gedaan, en waarom: sorteren in Alle (~1-2 s) en een klik op favoriet
(~0,4 s) zijn nu vooral de browser die een tabel van duizenden rijen opnieuw
opmaakt; sneller wordt dat pas met bladeren of alleen de zichtbare rijen
tekenen (zoals `/racefietsen`), en dat is een ontwerpkeuze voor de eigenaar.
`/fiets` leest de spec-tabel twee keer (~0,1 s), niet de moeite waard.

## Alle racefietsen en vergelijken op model (30-09-2026)

- De zoekopdracht `racefietsen` slaat alles op, elke maat en prijs; de ronde
  `week` haalt de hele categorie in delen (`--split`, per staat en
  prijsschijf). Eerste echte proef: 12.055 van 14.446 via de staat-delen,
  toen gaf Marktplaats een 403 na ~120 snelle verzoeken. Daarom nu minstens
  4 s ertussen, een minuut pauze per 40, en na een 403 vijf minuten wachten.
  Nog niet bewezen dat hij daarmee compleet wordt: kijk na de eerste
  zondagronde in `logs/koopjes.log` naar "in delen: … van de … gezien" en
  of er een 403 in staat.
- /racefietsen vergelijkt op merk + model + bouwjaar (`bike_identity.py`).
  Op 100 echte titels had 58 een herkend model, maar maar ~6 een bouwjaar:
  de meeste schattingen zijn dus "model + tijdperk" of "onzeker". Vaker het
  jaar weten kan met `--detail-lookup` (volledige omschrijving) — kost
  verzoeken, eerst aan de eigenaar vragen.

## Racefietspagina, afstand, eigen biedingen, weergaven/likes (29/30-09-2026)

Na een gesprek met de eigenaar (zijn keuzes staan in de docstrings van
`racebikes.py`, `distance.py`, `own_bids.py` en `views.py`, en in README):

- `/racefietsen` (`racebikes.py`): alle racefietsen als kaarten met
  sneltoetsen, flip en upgrade apart, zes weg-redenen (`marks.BIKE_REASONS`;
  "te hoge listing" van de eigenaar heet op de knop *te hoge vraagprijs*).
- Afstand hemelsbreed op alle live pagina's (`distance.py`, migratie 18):
  plek uit de zoekresultaten, postcode op de pagina, geplaatst met één
  zoekverzoek. Oudere advertenties krijgen die plek pas als een ronde ze
  weer ziet (tot die tijd *ca.*, via de plaatsnaam).
- Eigen biedingen (`own_bids.py`): geaccepteerd gaat meteen naar /flips.
- Weergaven/likes (`views.py`): `views_budget` per tijdslot, ~125 extra
  verzoeken per dag. Patronen worden pas iets na een paar weken; de
  steekproef (1 op 10) is een aanname, geen meting: blijken de groepen na
  een maand nog te klein, dan `SAMPLE_EVERY` omlaag of het budget omhoog —
  vraag dat eerst aan de eigenaar (extra verzoeken).

Open: de pagina op de telefoon (de eigenaar: later), reiskosten per fiets
(de eigenaar zoekt ze per fiets uit op /flips), en of de dagtopper-samenhang
standhoudt als je voor prijs corrigeert.

## Flippagina (29-09-2026)

`/flips` in `dashboard.py --serve` (flips.py, migratie 17) met klussenlijst,
investeringen, voorraad, foto's, biedingen en een Google Sheet in twee
richtingen (flips_sheets.py, SHEETS.md). De Cube Peloton Pro staat in
`flips_import/cube_peloton_pro.json`. Open: de pagina op de telefoon via de
thuiswifi (de server luistert nu alleen op 127.0.0.1; dan is een wachtwoord
nodig in plaats van alleen het token), de Tacx heeft nog geen aankoopprijs,
en de tab Mijn flips kan straks helemaal naar /flips verwijzen.

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

## Stand van zaken op 27-09-2026

Zo stond het er toen voor; de README en `docs/` beschrijven hoe het nu is.

### Waar we nu staan

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
  elke score staat welke signalen erin zaten. Zie `docs/rapport.md` → "Dealscore" voor
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
  ze met `--reference-file`; zie `docs/referentiedata.md` → "Bikes have their own
  reference files".
- `reference_bike_catalog.csv` is iets anders: een catalogus met één rij per
  merk/model/modeljaar (Giant, Trek, Cube, Sensa en via bikezona.com ook
  andere merken), met specs, nieuwprijs en bron. Geen referentiebestand: met
  `--reference-file` waarschuwt het script en herkent het niets. Alleen de
  merkkolom wordt gelezen (slapers, lijst niet-herkende advertenties); specs
  en nieuwprijzen gebruikt de taxatie nog niet. Zie `docs/referentiedata.md` →
  "Bike catalogue". Opgebouwd met `catalog_tools/`.
- Hulpscripts: `check_hifi_brand.py` (merken-index opzoeken),
  `check_reference_overlaps.py` (patroon-conflicten checken),
  `reference_overview.py` (doorbladerbaar overzicht van de database).
- HTML-rapport heeft filtertabs: Alles / Nieuw / Koopjes / Beter dan
  referentie / Prijsverlaging / Topdeals / Bieden / Vrij te bieden.

### Taxatie: wat er nu al kan

`valuation.py` taxeert de fiets uit `mijn_fiets.md` op de advertenties in
`koopjes.db` (fase 3) die de eigenaar zelf meenam op `/fiets` (sinds
29-09-2026; de nachtronde crawlt "giant defy" al):

```bash
python dashboard.py --serve        # http://127.0.0.1:8765/fiets: meenemen of niet
python valuation.py --db koopjes.db
```

Niets meegenomen, dan komt er met opzet géén bedrag uit. Wat er
nog ontbreekt om de taxatie compleet te maken staat bij fase 3 in §12 van het
plan: verdwijn-historie voor de gemeten E2-factor, en componentprijzen voor E3
en voor het verschil tussen scenario A en B.

### Actief plan

`PLAN_FIETSWAARDE.md` is het uitgewerkte werkplan voor de eerstvolgende
uitbreiding: taxatie van de eigen fiets (Giant Defy 2012) + een upgrade-finder
die laat zien welke betere fiets daarvoor te koop staat, biedadvertenties
meegerekend, plus de overstap van losse CSV's naar SQLite. Begin daar, en pak
één fase per sessie.

Let op bij het lezen van dat plan: het is geschreven toen de dealscore en het
bied-overzicht nog niet bestonden. Die zijn er inmiddels (zie hierboven), dus
fase 4, 5 en 7 bouwen daarop voort in plaats van ze te maken. Het plan zelf is
daarop bijgewerkt; deze noot staat er voor het geval je een oudere kopie leest.
