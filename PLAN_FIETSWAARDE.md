# Plan: taxatie van mijn eigen fiets + upgrade-finder

Werkplan voor uitvoerende agents. Lees dit hele document voordat je begint,
pak **één fase**, en vink hem af in de checklist onderaan.

Dit plan is geschreven na een gesprek met de eigenaar; zijn keuzes staan in
§3. Wijk daar niet van af zonder te vragen.

> **Lees dit eerst — de code is veranderd sinds dit plan geschreven werd.**
>
> Ontwikkel op **`main`** (niet op `claude/clever-dijkstra-64tu8z`; die is in
> `main` samengevoegd en wordt niet meer gebruikt).
>
> Deze dingen bestaan al en hoef je niet te bouwen:
>
> | Bestaat al | Waar |
> | --- | --- |
> | Samengestelde dealscore 0-100 per advertentie, met onderbouwing per signaal | `score_listing()`, README → "Dealscore" |
> | Bied-overzicht: biedaantal, echt minimumbod, "vrij te bieden", eigen tabs | `enrich_bid_listings()`, `print_bid_overview()`, README → "Bidding listings" |
> | Testsuite (87 tests) | `tests/`, draaien met `python -m unittest discover -s tests -t tests` |
>
> Fase 4, 5 en 7 bouwen dáárop voort in plaats van bij nul te beginnen; per
> fase staat hieronder wat dat concreet betekent. **Houd de tests groen** —
> ze zijn er speciaal voor fase 1 gezet.

---

## 1. Doel

De eigenaar rijdt een **Giant Defy uit 2012** met:

- een carbon wielset van AliExpress (nieuwprijs ca. €300),
- een Shimano Ultegra 6700 groepset (10-speed, mechanisch),
- Pirelli P Zero Race banden,
- een Wahoo Elemnt Roam (v1) als fietscomputer.

Hij wil weten:

1. **Wat levert deze fiets op** als hij hem verkoopt — met een expliciete
   onderbouwing, niet één getal uit de lucht.
2. **Welke betere fiets** hij voor dat geld terug kan kopen, biedadvertenties
   uitdrukkelijk meegerekend.
3. Dat allebei zichtbaar in het bestaande HTML-rapport, als eigen tabbladen.

## 2. Kernidee

> Eén waarderings- en scoringsmotor, twee invoeren.

"Wat is mijn fiets waard" en "is deze advertentie beter dan mijn fiets" zijn
dezelfde vraag op andere data. Bouw dus **niet** een losse taxatiemodule naast
de bestaande advertentielogica. Bouw:

```
build (frame + groepset + wielen + accessoires)
   ├── value(build)  -> (laag, midden, hoog, bewijsregels)
   └── score(build)  -> (kwaliteitsscore 0-100, per dimensie uitgesplitst)
```

Draai dat op de eigen fiets → vraagprijs en baseline-score.
Draai het op elke advertentie → taxatie en vergelijking.
Budget voor de upgrade-finder = de uitkomst van de eerste draai.

Twee scores strikt gescheiden houden, ze worden anders door elkaar gehaald:

| Score | Betekenis |
| --- | --- |
| **kwaliteitsscore** | hoe goed is de fiets (onafhankelijk van prijs) |
| **waardescore** | `geschatte waarde / gevraagde prijs` — hoe goed is de prijs |

Een dure topfiets heeft een hoge kwaliteitsscore en een matige waardescore.
Dat is geen bug.

> **Let op de naamgeving.** Dit plan noemde de tweede score oorspronkelijk
> "dealscore", maar dat woord is inmiddels bezet: `Listing.deal_score` in
> `racefiets_jev.py` is een 0-100 score uit % van de mediaan, % van het
> 2e-hands gemiddelde en % van de nieuwprijs. Dat is iets anders dan
> `geschatte waarde / gevraagde prijs`. Daarom heet die nieuwe verhouding
> hier **waardescore** (`value_score`), en blijft `deal_score` wat het nu is.
> Gebruik die twee namen consequent en vermeng ze niet in één kolom — het zijn
> twee verschillende antwoorden op "is dit een goede prijs".

## 3. Al genomen beslissingen

Deze zijn met de eigenaar afgestemd. Niet heroverwegen.

| Onderwerp | Keuze |
| --- | --- |
| Opslag | **SQLite** wordt de bron van waarheid. Bestaande CSV's worden geïmporteerd en blijven als export bestaan, zodat niets breekt. |
| Welk frame | **Giant Defy Composite 2012**, carbon, maat 56, velremmen. Vastgesteld in fase 0, zie `mijn_fiets.md`. |
| Verkoopvorm | Twee scenario's: **(A)** compleet mét carbon wielset, **(B)** compleet met de originele wielen + carbon wielset apart verkocht — de originele wielen zijn nog in bezit, dus B kan echt. Volledig strippen en alles los verkopen is **niet** gewenst. |
| "Beter" betekent | Moderner (schijfremmen, 12-speed) **én** lichter/hogere frameklasse **én** elektronisch schakelen **én** puur meer fiets per euro. Alle vier wegen mee, met instelbare gewichten. |
| Accessoires | Tellen expliciet mee. Een powermeter of fietscomputer bij een advertentie is een grote plus. Losse accessoires moeten ook als **eigen zoekopdracht** gejaagd kunnen worden. |
| Bieden | Biedadvertenties zijn eersterangs, geen bijvangst. Zie §7. |

## 4. Fase 0 — intake (data, geen code)

**Grotendeels afgerond.** De antwoorden staan in `mijn_fiets.md`; lees dat
bestand voordat je aan de taxatie begint. Samengevat: Giant Defy **Composite**
2012, **carbon**, maat **56**, Shimano **Ultegra 6700** (10-speed, mechanisch),
**velremmen**, carbon AliExpress-wielset, en de **originele wielen zijn er nog**
— dus scenario B (fiets compleet met stockwielen, carbon wielset apart) kan
doorgerekend worden.

Wat daar nog open staat (details in `mijn_fiets.md`, §Nog open) blokkeert de
taxatie niet: verkoopregio, eventuele schade, en de exacte trim. Verder bekend
en gunstig: **minder dan 10.000 km**, en cassette én ketting zijn ca. 1500 km
oud. De Wahoo Elemnt Roam gaat **niet** mee bij verkoop. Het budget voor de
volgende fiets is de **verkoopopbrengst + maximaal €250**.

Twee eerder kritieke punten zijn inmiddels beantwoord en veranderen het werk:

- **De Ultegra zat er al op bij aankoop.** Er valt dus aan de groepset niets
  terug te verdienen; de upgrade-recovery-berekening uit §6 gaat alléén over de
  wielset van €300. Dat maakt de taxatie simpeler: comps op Defy Composite
  2012, plus de wielset als aparte post.
- **De wielset is een CSC 50 mm carbon clincher** (25 mm buiten / 18 mm binnen,
  naven AS511SB/FS522SB — vrijwel zeker Novatec). Herkenbaar merk en
  herkenbare naven, dus géén "naamloos carbon" in de waardering. Maar wel
  clincher, velrem en met 18 mm binnenbreedte gebouwd rond 25 mm banden: een
  smalle, krimpende koperskring.

**Uitvoer van deze fase:** `mijn_fiets.md` (bestaat) plus rijen in de tabel
`owned_item` (§5) zodra fase 1 er is — fase 1 importeert `mijn_fiets.md`.

**Let op bij het afmaken:** verifieer de 2012 Defy-line-up (Composite 1 vs 2,
nieuwprijs, standaard groepset) en de Ultegra-generaties met bronvermelding via
webonderzoek. Niet uit het hoofd invullen — modeljaren, spec-niveaus en
nieuwprijzen zijn precies het soort detail waar een taalmodel overtuigend naast
zit. Vergelijk in de comps ook niet met Defy **Advanced**: dat is een hogere
carbonlaag en trekt de schatting te hoog.

## 5. Datamodel (SQLite)

Eén bestand `koopjes.db`, benaderd met `sqlite3` uit de standaardbibliotheek.
Geen extra dependency, geen server.

**Waarom niet bij CSV blijven:** de taxatie heeft queries nodig als "mediaan
vraagprijs van Giant Defy, bouwjaar 2010-2014, carbon, Ultegra, maat 54-57,
laatste 180 dagen, n≥5". Dat is één `SELECT` met `GROUP BY`, of vijftig regels
broze Python over vier losgekoppelde CSV's. Bovendien moet één advertentie
straks meerdere modellen kunnen matchen (fiets + powermeter + computer in
dezelfde advertentie); dat is een many-to-many en die hoort niet in een CSV.

```sql
-- kerntabellen
crawl_run(id, query, pages_requested, pages_fetched, listing_count, started_at, finished_at)
listing(item_id PK, title, description, price_eur, price_type, is_bid, city,
        posted_date, condition, frame_height, url, query,
        first_seen, last_seen, disappeared_at, days_online)
listing_price(id, item_id FK, observed_at, price_eur)   -- elke waarneming, niet alleen de laatste

-- kennis
model(id, kind, brand, model, variant, year_from, year_to, pattern,
      original_price_eur, specs_json, score, notes, source_url)
      -- kind: 'bike' | 'frameset' | 'groupset' | 'wheelset' | 'computer' | 'powermeter' | 'other'
listing_model(listing_id FK, model_id FK, matched_on, confidence)  -- MEERDERE per advertentie
spec(id, listing_id FK, key, value, source, confidence)
      -- key: frame_material, brake_type, speeds, groupset_tier, electronic,
      --      wheel_type, model_year, weight_kg, has_powermeter, has_computer, ...

-- eigen bezit
owned_item(id, kind, label, model_id FK NULL, acquired_price_eur, specs_json, notes)

-- uitkomsten
valuation(id, subject_type, subject_id, scenario, low_eur, mid_eur, high_eur,
          confidence, method_version, created_at)
valuation_evidence(id, valuation_id FK, kind, ref_id, ref_url, price_eur,
                   weight, note)
      -- kind: 'comp' | 'parts' | 'retail' | 'depreciation' | 'adjustment'
component_price(id, model_id FK, observed_at, price_eur, source_url, note)

-- housekeeping
schema_version(version, applied_at)
watchlist(id, name, query, filters_json, active)
```

**Regels bij dit model:**

- `listing_price` is ruwe waarneming. **Nooit** een afgeleide taxatie
  terugschrijven naar `listing_price` of `component_price` — dan wordt de
  waardering circulair en drijft hij binnen een paar weken weg van de markt.
- Bestaande bestanden migreren in fase 1: `seen_listings.json` → `listing` +
  `listing_price`, `reference_prices.csv` → `model`,
  `reference_price_history.csv` → `listing_price`, `bargains_log.csv` blijft
  puur een export.
- `reference_prices.csv` blijft geschreven worden als export, zodat
  `reference_overview.py` en `check_reference_overlaps.py` blijven werken.

## 6. Waarderingsmethode

Het lastige punt, en het moet expliciet in het rapport staan: **Marktplaats
publiceert vraagprijzen, geen verkoopprijzen.** Een taxatie die vraagprijzen
als verkoopprijzen behandelt, zit er structureel te hoog in. Drie onafhankelijke
schatters, daarna gemengd.

### E1 — Vergelijkbare advertenties (comps)

Mediaan + spreiding van vergelijkbare advertenties uit de eigen database.
Omdat exacte comps schaars zijn ("Defy Advanced 2012, Ultegra, maat 54" levert
er misschien nul op), een **ladder** met afnemend vertrouwen:

| Trede | Criterium | Vertrouwen |
| --- | --- | --- |
| 1 | zelfde model + bouwjaar ±2 + zelfde groepsettier | hoog |
| 2 | zelfde modelfamilie (Defy) + bouwjaar ±3 | midden |
| 3 | zelfde segment: carbon/alu endurance, 10-11sp, velrem, 2009-2015 | laag |

Registreer altijd **welke trede** en **welke n** gebruikt is; dat hoort in de
bewijsregels. Onder n=5 nooit als hard getal presenteren.

### E2 — Correctie vraagprijs → realistische verkoopprijs

Hier zit de meeste winst, en de bestaande crawl kan het meten. Zodra
`disappeared_at` wordt bijgehouden, geldt: advertenties die binnen ~14 dagen
verdwijnen waren realistisch geprijsd; advertenties die na 60+ dagen nog
online staan, niet. De verhouding tussen de medianen van die twee groepen is
een **empirische** correctiefactor per categorie, in plaats van een gegokte
"er gaat altijd 10% af".

- Start met een heuristische default (−10% tot −15% onderhandelingsruimte) en
  laat de data die pas overschrijven vanaf n≥20 per categorie.
- **Eerlijke kanttekening, zet hem in het rapport:** verdwenen ≠ verkocht. Een
  advertentie kan ook ingetrokken of verlopen zijn. Het is een proxy.
- **Valkuil in de implementatie:** je mag alleen "verdwenen" concluderen als de
  crawl dezelfde query met dezelfde diepte heeft gedaan. Een run met
  `--pages 1` zou anders alles behalve de eerste 30 advertenties als verdwenen
  markeren. Daarom de tabel `crawl_run`: voer de verdwijn-sweep **uitsluitend**
  uit na een volledige crawl (`--pages 0`) en alleen voor die query.

### E3 — Som der delen

`framewaarde + groepset + wielen + accessoires`, elk uit `component_price`
(gevoed door gerichte zoekopdrachten: "ultegra 6700 groepset", "carbon wielset
racefiets", "wahoo elemnt roam"), maal een bundelfactor.

Bij deze fiets is E3 vermoedelijk **hoger** dan E1, en dat verschil is precies
het antwoord op scenario B. Toon het expliciet als:

```
geïnvesteerd in upgrades      €X
daarvan terug te verdienen    €Y   (compleet verkopen)
daarvan terug te verdienen    €Z   (wielset apart)
```

Kopers van een complete fiets betalen zelden mee aan andermans upgrades; ze
kijken naar model en bouwjaar. Verwacht dat dit onprettig nieuws oplevert en
presenteer het gewoon.

### Mengen en presenteren

- `mid` = gewogen mediaan van E1(gecorrigeerd met E2) en E3(met bundelkorting),
  wegen op basis van n en vertrouwen.
- `low`/`high` = 20e/80e percentiel van de bewijsset. **Nooit één getal tonen
  zonder band en zonder n.**
- Elke euro traceerbaar via `valuation_evidence`: links naar de comps, de
  gebruikte trede, de toegepaste factoren.

### Specifieke aandachtspunten voor deze fiets

- **De CSC-wielset**: zoek comps op de werkelijke kenmerken (50 mm carbon
  clincher, velrem, Novatec-naven), niet op "AliExpress wielen" en niet als
  percentage van de €300 nieuwprijs. Drie dingen duwen tegengesteld: merknaam
  en herkenbare naven duwen omhoog, velrem + clincher + 18 mm binnenbreedte
  duwen omlaag. Zoek daarom apart op vergelijkbare Chinese carbon velremsets
  (CSC, Elitewheels, Superteam, Yoeleo, Winspace) in plaats van op merkloze
  sets, anders schat je te laag.
- **Velrem-carbon is een krimpende markt.** Dit onderdeel veroudert sneller dan
  de rest van de fiets. Als de eigenaar twijfelt over het moment van verkopen:
  hier is wachten duurder dan bij het frame.
- **Pirelli P Zero Race banden**: gebruikte banden voegen in de praktijk
  nauwelijks iets toe aan de verkoopprijs. Waarderen als klein plusje, niet als
  component.
- **Een 14 jaar oud frame**: de frameklasse en het bouwjaar domineren de prijs.

## 7. Scoring en de upgrade-finder

### Kwaliteitsscore

Per dimensie 0-100, gewichten in `scoring_config.json` (JSON, geen TOML —
`tomllib` bestaat pas vanaf Python 3.11 en de doelmachine is onbekend).

| Dimensie | Signalen |
| --- | --- |
| `frame` | materiaal (alu/carbon/high-mod) × frameklasse (endurance/performance/race) × leeftijdsverval |
| `drivetrain` | groepsettier 1-6 (bestaat al: `GROUPSET_CATALOG`) + elektronisch + aantal versnellingen |
| `brakes` | velrem 40 / mechanische schijf 60 / hydraulische schijf 100 |
| `wheels` | alu 40 / naamloos carbon 60 / merk-carbon 85 |
| `extras` | powermeter, fietscomputer, extra wielset, pedalen — **relatief aan wat hij al heeft**: hij houdt zijn Wahoo Elemnt Roam, dus een fietscomputer bij een advertentie is alleen doorverkoopwaarde waard, een powermeter telt volledig mee |
| `fit` | **geen score maar een harde poort** — verkeerde framemaat = uitgesloten |

De eigen fiets wordt met dezelfde functie gescoord; dat getal is de baseline.
`beter_dan_mijn` = score > baseline + marge. De invoer voor die baseline staat
onderaan `mijn_fiets.md`: carbon instap-frame uit 2012, Ultegra 10-speed
mechanisch, velremmen, naamloos carbon velremwielen, plus een fietscomputer.
Dat is een lage baseline op `brakes` en `drivetrain` en een middelmatige op
`frame` — verwacht dus veel kandidaten en laat de maat-poort (56) het zware
filterwerk doen.

**Uitlegbaarheid is een eis, geen extra.** Het rapport moet de uitsplitsing per
dimensie tonen. Een niet-uitlegbaar totaalcijfer wordt niet vertrouwd en dus
niet gebruikt.

Volg hierin het patroon dat `deal_score` al gebruikt: naast het getal houdt
elke advertentie een `deal_reasons`-regel bij met de signalen die erin zaten,
zichtbaar in de console en als tooltip in het rapport. Doe voor de
kwaliteitsscore hetzelfde per dimensie.

### Upgrade-finder

Kandidaat = `past_qua_maat` ∧ `kwaliteitsscore > baseline + marge` ∧
`effectieve_prijs ≤ budget`.

- `budget` = midden-taxatie van het gekozen scenario (A of B), plus een
  instelbare marge. **Het scenario hangt af van de kandidaat**, want de
  CSC-wielset is een velremset:
  - kandidaat met **velremmen** → de wielset kan mee naar de nieuwe fiets.
    Budget = opbrengst van de fiets met de originele wielen (scenario B, alleen
    het fietsdeel), en de kandidaat krijgt in de score de waarde van de
    meeverhuisde wielen erbij.
  - kandidaat met **schijfremmen** → de wielset kan niet mee en moet verkocht
    worden. Budget = scenario B volledig (fiets + wielset).

  Dat is geen detail: het verschil bepaalt of een schijfremfiets binnen bereik
  ligt. Reken het per kandidaat uit in plaats van één budget vooraf te kiezen.
- `effectieve_prijs` = vraagprijs × onderhandelingsfactor voor vaste prijzen,
  of het huidige bod voor biedadvertenties. Toon altijd **beide**: vraagprijs
  én verwachte biedprijs. "Bieden" hoort in de rekensom te zitten, niet als
  voetnoot.
- Rangschikken op **upgrade per euro**: `(score − baseline) / effectieve_prijs`.
- **Verwachting bij dit budget (opbrengst + max €250):** de velremroute wint
  bijna altijd, omdat de CSC-wielset dan meeverhuist en effectief waarde
  meeneemt. Bouw de finder daar echter **niet** op vast: schijfremkandidaten
  moeten zichtbaar blijven, want juist een uitgesproken koopje daar is de reden
  dat dit gereedschap bestaat. Sorteer op upgrade per euro en laat de
  rangschikking het werk doen, in plaats van een remtype vooraf uit te sluiten.
- **Het budget is krap, dus de bied-kant is hier niet optioneel.** Met deze
  marge is de kans op een generatiesprong via een gewone vaste-prijsadvertentie
  klein; een onderbeboden biedadvertentie is de realistische route. Het
  biedoverzicht zelf bestaat al (zie hieronder) — wat ontbreekt is de
  **speelruimte**-sortering, en die heeft de taxatie uit fase 3 nodig. Geef
  die voorrang boven cosmetische verbeteringen elders.

### Biedadvertenties

Hier komt het samen. Eigen paneel met alle FAST_BID/MIN_BID-advertenties,
gesorteerd op **speelruimte** (`geschatte waarde − huidig bod`). Dat is waar
de koopjes zitten, omdat deze advertenties onzichtbaar zijn voor wie op prijs
sorteert.

**Dit is uitbreiden, niet bouwen.** Wat er al staat:

- `enrich_bid_listings(listings, delay, mode)` — let op de naam, hij heette
  vroeger `enrich_fast_bid_listings`. Haalt per advertentie het biedaantal en
  het minimumbod op. `mode="fast"` (standaard) doet alleen FAST_BID,
  `mode="all"` ook MIN_BID, `mode="none"` niets.
- `Listing.bid_count`, `.bid_minimum`, `.bid_minimum_pct_of_median`,
  `.bid_open` — en `apply_bid_flags()` die `bid_open` zet.
- `print_bid_overview()` in de console; de tabs "Bieden" en "Vrij te bieden"
  in het rapport; de vlaggen `--bids-only` en `--min-score`.

Wat deze fase toevoegt is de **speelruimte** zelf, want daar is de taxatie uit
fase 3 voor nodig: `geschatte waarde − huidig bod`. Sorteer het paneel daarop
in plaats van op dealscore.

**Eén valkuil die al een keer is gemaakt:** bij een MIN_BID-advertentie is de
prijs uit de zoekresultaten de **vraagprijs**, niet het minimumbod. Het
minimumbod staat alleen op de advertentiepagina en ligt er vaak flink onder
(gezien: vraagprijs €200 / minimumbod €120). Overschrijf de vraagprijs dus
niet met het minimumbod — dan lijken bied-advertenties goedkoper dan
vaste-prijs-advertenties puur omdat er geboden mag worden. Er staat een test
op (`tests/test_bids.py`).

### Losse producten (watchlist)

De eigenaar wil ook los kunnen jagen op bijvoorbeeld een powermeter of een
nieuwere fietscomputer. De `watchlist`-tabel houdt benoemde zoekopdrachten bij
(naam, query, filters, eigen referentiemodellen), zodat dezelfde machinerie
accessoires jaagt. Het script ondersteunt al komma-gescheiden queries; dit is
vooral het opslaan en per-watchlist toepassen van filters.

## 8. Rapport

De huidige `.filters`-knoppen filteren rijen in één tabel. Twee van de nieuwe
weergaven zijn géén advertentietabel, dus promoveer dit tot echte
tab-**panelen**:

| Tab | Inhoud |
| --- | --- |
| Alles / Nieuw / Koopjes / Prijsverlaging / Beter dan referentie / Topdeals / Bieden / Vrij te bieden | bestaan al; ongewijzigd, rijfilters binnen het advertentiepaneel |
| **Mijn fiets** | taxatie per scenario (A en B), band laag-midden-hoog, en de volledige bewijslijst met links naar de comps |
| **Upgrade** | betere fietsen binnen budget, gesorteerd op upgrade per euro, met score-uitsplitsing |
| **Bieden** | bestaat al als rijfilter; promoveren tot paneel en sorteren op speelruimte |

**Technische waarschuwing:** `HTML_TEMPLATE` is een `.format()`-string met
verdubbelde accolades `{{ }}`. Er JavaScript met object-literals in schrijven is
foutgevoelig. Haal de template daarom in fase 6 uit `racefiets_jev.py` naar een
apart `report_template.html` dat runtime wordt ingelezen, of stap over op
`string.Template` ($-placeholders). Doe dat als eerste stap van die fase, in een
aparte commit, zodat de refactor los te reviewen is van de nieuwe inhoud.
`tests/test_report.py` beschrijft wat er na die refactor nog moet kloppen
(geen onvervangen placeholders, HTML-escaping, en elk tabblad-aantal gelijk
aan het aantal rijen dat erbij hoort) — draai die tests vóór en ná.

## 9. Fasering

Eén fase per agent-sessie. Draai de acceptatiecriteria vóór je commit. Fase 0 en
fase 7 raken alleen data en mogen parallel met alles lopen.

### Fase 1 — SQLite-fundament *(blokkeert alles)*

Opgeknipt in twee sessies: 1a raakt `racefiets_jev.py` niet aan, 1b wel. Zo
blijft de diff per sessie te overzien en kun je 1a afronden en committen
zonder dat het script ook maar iets anders doet.

`tests/` bestaat inmiddels (87 tests). Breid uit, begin niet opnieuw, en draai
ze vóór én na elke stap: `python -m unittest discover -s tests -t tests`.

**Fase 1a — `db.py` los, nog niet aangesloten**
- Nieuw `db.py`: schema uit §5, `schema_version`-migraties, `connect()`,
  `import_legacy()` (de vier bestaande bestanden), `export_csv()`.
- Tests voor `db.py` in `tests/test_db.py`, met een DB in een tijdelijke map.
- **Acceptatie:** `import_legacy()` op een kopie van de echte bestanden vult
  de tabellen; twee keer draaien geeft geen dubbele rijen (idempotent);
  `export_csv()` levert een bestand dat `reference_overview.py` nog leest;
  `racefiets_jev.py` is ongewijzigd en de hele suite is groen.

**Fase 1b — aansluiten op het script**
- `racefiets_jev.py` schrijft naar de DB **en** blijft de bestaande CSV's
  schrijven. Geen zichtbare gedragsverandering.
- **Geef `import_legacy()` alle drie de paden expliciet mee**, uit
  `args.history_file`, `args.reference_file` en `args.price_history_file`.
  De functie heeft standaardwaarden die naar het werkpad wijzen, dus laat je
  er een weg, dan importeert hij stilzwijgend het verkeerde bestand zodra de
  gebruiker zo'n vlag overschrijft. Zet er een test op.
- **Plan de crawl-schema's zo in** (dit is de gekozen opzet, bouw ernaar):
  ondiepe runs (`--pages 3`) drie keer per dag voor nieuwe advertenties en
  prijsdalingen, plus één volledige crawl (`--pages 0`) per nacht. De
  verdwijn-sweep hoort uitsluitend bij die nachtelijke volledige crawl.
- `crawl_run`-registratie + de verdwijn-sweep, alleen na `--pages 0`.
- `--db` (pad, default `koopjes.db`) en `--no-db` toevoegen.
- **Acceptatie:** script twee keer draaien; DB gevuld; CSV's ongewijzigd van
  formaat (`tests/test_storage.py` blijft groen — die suite is er precies voor
  deze stap); `--no-db` werkt; de hele suite groen.

### Fase 2 — Spec-extractie en meervoudige matches *(na 1)*
- Detectie uitbreiden voorbij groepset: `frame_material`, `brake_type`,
  `speeds`, `wheel_type`, `model_year`, `weight_kg`, `has_powermeter`,
  `has_computer`. Wegschrijven naar `spec`.
- De `break` in `apply_reference_data` laten vallen: meerdere modelmatches per
  advertentie, opslaan in `listing_model`.
- **Acceptatie:** testset van ~50 echte advertentieteksten met verwachte
  uitkomst in `tests/fixtures/`. Stuur op **precisie boven dekking** — niets
  extraheren is beter dan iets fout extraheren, want een foute spec vervuilt de
  comps. Controleer dat het bestaande "Beter dan referentie"-filter niet
  verandert van gedrag.

### Fase 3 — Waarderingsmotor *(na 1, beter na 2)*
- Nieuw `valuation.py`: E1, E2, E3, de menging, en het schrijven van
  `valuation` + `valuation_evidence`.
- Pure functies, geen netwerk; de DB-query's apart van de rekenkunde.
- **Acceptatie:** unittests met synthetische comps (bekende invoer → bekende
  mediaan/band); taxatie van de eigen fiets levert een band + ≥5 bewijsregels;
  elk getoond getal is terug te voeren op een bewijsregel; expliciete test dat
  een taxatie nóóit in `listing_price` belandt.

### Fase 4 — Scoring *(na 2)*
- Nieuw `scoring.py` + `scoring_config.json` met de gewichten uit §7.
- Dezelfde functie voor advertenties en voor `owned_item`.
- Dit is de **kwaliteitsscore** — laat `deal_score` in `racefiets_jev.py` met
  rust, dat is een andere score (zie §2).
- **Acceptatie:** eigen fiets krijgt een baseline; een moderne Ultegra Di2
  disc-fiets scoort hoger; een alu Sora-fiets lager; gewicht aanpassen in de
  JSON verandert de uitkomst voorspelbaar; uitsplitsing per dimensie is
  opvraagbaar.

### Fase 5 — Upgrade-finder en biedlogica *(na 3 en 4)*
- Budget uit de taxatie, maatpoort (hergebruik `frame_height_bounds`),
  effectieve prijs met onderhandelingsfactor, rangschikking op upgrade per euro.
- Biedpaneel-data: speelruimte per biedadvertentie.
- **Acceptatie:** met fixture-advertenties komt de verwachte volgorde eruit;
  een fiets buiten de maat verschijnt nooit; een biedadvertentie zonder
  opgehaald bod valt niet stil terug op €0.

### Fase 6 — Rapport-tabs *(na 5)*
- Eerst de template-refactor (§8) in een eigen commit, daarna de drie panelen.
- **Acceptatie:** rapport opent, tabs wisselen, geen console-fouten, bestaande
  filters en sortering werken nog, bewijslijst is zichtbaar en klikbaar.

### Fase 7 — Referentiedata fietsen *(parallel, alleen data)*
- Dezelfde prijssegment-aanpak als bij de luidsprekers, nu voor fietsen: vul
  `model` met de Defy-familie, de gangbare upgradedoelen, en de accessoires
  (Wahoo/Garmin, powermeters).
- Bronvermelding per rij in `source_url`.
- `reference_prices.csv` bevat op dit moment **alleen luidsprekers** (43
  rijen). De onjuiste regel in `NEXT_STEPS.md` hierover is al gecorrigeerd.
  *(Gedaan: de fietsen staan in `reference_bikes.csv` en
  `reference_bike_accessories.csv`, zie §12.)*
- **Deze fase is opzoekwerk, geen programmeerwerk.** Modeljaren,
  groepsetgeneraties en nieuwprijzen zijn precies waar een taalmodel
  overtuigend naast zit. Zoek elk getal op, noteer de bron, en gok nooit —
  liever een lege kolom dan een verzonnen nieuwprijs, want die vervuilt de
  taxatie voorgoed. Geef deze fase bij voorkeur aan een sterker model of doe
  hem met de hand.
- **Let op de volgorde bij export.** `export_csv()` schrijft op `id`, dus op
  invoegvolgorde. In `reference_prices.csv` geldt "eerste match wint", dus een
  nieuw, specifiek patroon dat je achteraan toevoegt komt ná een bestaand
  breder patroon te staan en wordt dan nooit geraakt. Draai
  `check_reference_overlaps.py` na elke export — die vindt precies dit.
- **Acceptatie:** `check_reference_overlaps.py` meldt geen onbedoelde
  overlappen; elk model heeft een bron.

### Fase 8 — Watchlist *(na 1)*
- `watchlist`-tabel bruikbaar maken: benoemde zoekopdrachten met eigen filters
  voor losse producten.
- **Acceptatie:** een watchlist "powermeter" draait met eigen prijsfilters
  zonder de fietsqueries te beïnvloeden.

## 10. Werkafspraken voor agents

- **Begin bij een verse `main`, eindig op `main`.** Je sessie krijgt
  waarschijnlijk een eigen branch toegewezen (`claude/...`); werk daar gerust
  op, maar vertak van de actuele `main` en meld aan het eind naar welke branch
  je gepusht hebt. Fase 1a stond na afloop op een losse branch; dat moet elke
  keer nog gemerged worden, en vergeet je dat, dan bouwt de volgende fase op
  oude code. Commitbericht begint met `Fase N:`.
- **Fetch opnieuw vlak vóór je merget, niet alleen bij het starten.** Dit is
  een keer misgegaan: een merge op een acht minuten oude `origin/`-ref liet
  twee commits van een andere sessie vallen, met echte gegevens erin. Er
  werken soms meerdere sessies tegelijk aan deze repo. Pak niet twee fases
  tegelijk in twee chats.
- **Breek geen bestaande CLI-vlaggen of bestandsformaten.** Alles in de README
  moet blijven werken; werk de README bij in dezelfde commit als de wijziging.
- **Geen nieuwe dependencies** tenzij je motiveert waarom de standaardbibliotheek
  niet volstaat. `requirements.txt` bevat nu alleen `requests`; `sqlite3`,
  `json` en `unittest` zitten in de stdlib.
- **Houd de tests groen.** `python -m unittest discover -s tests -t tests`
  vóór je begint en vóór je commit. Faalt er iets wat je niet hebt aangeraakt,
  zoek dat dan eerst uit in plaats van de test aan te passen. Een test
  weghalen of uitzetten om groen te worden is nooit de oplossing.
- **Blijf beleefd tegen Marktplaats:** de `--delay` respecteren, geen
  parallelle verzoeken, geen crawl-frequentie opvoeren voor deze functies.
- **Commit geen persoonlijke datafiles**: `seen_listings.json`,
  `*_history.csv`, `koopjes.db` horen in `.gitignore` (de DB toevoegen).
  `reference_prices.csv` is bewust force-added; houd dat zo.
- **Nederlandse UI-teksten, Engelse code-identifiers** — zoals de codebase nu
  is.
- **Onzeker over een marktfeit?** Zoek het op en noteer de bron. Modeljaren,
  groepsetgeneraties en nieuwprijzen zijn precies waar gokken plausibel klinkt
  en fout is.
- Vink je fase af in §12 en noteer wat je hebt gelaten voor de volgende.

## 11. Buiten scope

- **Automatisch bieden of reageren op advertenties.** Nooit. Geld en een
  externe partij; de eigenaar doet dit zelf.
- Scrapen van andere platforms dan Marktplaats.
- Machine learning. De dataset is te klein en een uitlegbaar model is hier meer
  waard dan een nauwkeuriger blackbox.
- Een webserver of hosted database. Alles blijft lokaal en bestandsgebaseerd.
- Volledig strippen en alle onderdelen los verkopen — expliciet niet gewenst
  (§3).

## 12. Voortgang

- [x] Fase 0 — intake eigen fiets *(`mijn_fiets.md` is compleet genoeg om op te taxeren; drie verfijningen open, zie §4)*
- [x] Testsuite *(87 tests in `tests/`; hoorde bij fase 1, is vooruit gedaan)*
- [x] Eerste handmatige taxatie *(`taxatie_2026-09-22.md` — trede 2/3, n klein; fase 3 automatiseert dit)*
- [x] Fase 1a — `db.py` los, nog niet aangesloten *(schema uit §5, `import_legacy()` voor de drie databestanden, `export_csv()`; `racefiets_jev.py` ongewijzigd, 107 tests groen. Voor 1b: `listing_model` blijft leeg — many-to-many matching is fase 2 — en `bargains_log.csv` is bewust niet meegenomen, zie §5.)*
- [x] Fase 1b — aansluiten op het script *(`racefiets_jev.py` schrijft nu ook naar `koopjes.db` via `db.sync_listings()`/`record_crawl_run()`, naast de bestaande CSV/JSON-bestanden die ongewijzigd blijven; `--db`/`--no-db` toegevoegd. `import_legacy()` krijgt in `sync_database()` altijd alle drie de paden expliciet uit `args`. De verdwijn-sweep (`db.sweep_disappeared()`) draait alleen bij `--pages 0`; er is geen echte cron/scheduler gebouwd, dat blijft aan de gebruiker om in te plannen zoals in de fase beschreven. `pages_fetched` in `crawl_run` wordt niet ingevuld — `collect_listings()` telt dat zelf niet bij en het was niet nodig voor de acceptatiecriteria van deze fase. Tests in `tests/test_db_wiring.py`, 135 tests groen.)*
- [x] Fase 2 — spec-extractie en meervoudige matches *(`extract_specs()` in `racefiets_jev.py` detecteert `frame_material`, `brake_type`, `speeds` (8-13, bewust buiten dat bereik niks), `wheel_type`, `model_year` (alleen met expliciet label: bouwjaar/model(jaar)/uit), `weight_kg`, `has_powermeter`, `has_computer` — precisie boven dekking, dus veel gevallen leveren bewust niks op. `frame_material` is clause-scoped (splitst op `.,;`) om een los vermelde carbon wielset niet als carbon frame te lezen — zie `mijn_fiets.md`: alu/carbon-frame-plus-carbon-wielset is precies dit scenario. Weggeschreven naar `spec` via `db.sync_listing_specs()` (idempotent: vervangt per bron, geen dubbele rijen bij een herhaalde crawl). De `break` in `apply_reference_data()` is vervallen: hij retourneert nu ook `{item_id: [pattern, ...]}` met élk matchende patroon, maar `Listing.ref_* blijft exact op het eerste-match-wint-gedrag van vóór deze fase staan (apart getest), dus "Beter dan referentie" verandert niet. Alle matches gaan naar `listing_model` via `db.sync_listing_models()`. Testset: `tests/fixtures/spec_extraction.json` (50 advertentieteksten) + `tests/test_spec_extraction.py`; db-kant in `tests/test_db.py`/`test_db_wiring.py`, referentie-kant in `tests/test_storage.py`. 189 tests groen. Voor fase 3: `listing_model.confidence` staat overal op 1.0 (regex-match is deterministisch) — een échte confidence-schaal is nog niet ingevuld, en `spec.source` is altijd `"regex"`, dus een toekomstige handmatige correctie kan er naast bestaan.)*
- [x] Fase 3 — waarderingsmotor *(`valuation.py`: E1-ladder met trede + n in de bewijsregels, E2 op de heuristische 10-15% tot er ≥20 verdwenen én ≥20 blijvende advertenties zijn, E3 uit `component_price` maal bundelfactor, menging naar low/mid/high, en wegschrijven naar `valuation` + `valuation_evidence`. `mijn_fiets.md` wordt nu pas geïmporteerd naar `owned_item` — dat stond bij fase 0/1 maar was nooit gebeurd. 44 tests in `tests/test_valuation.py`, 249 tests groen.*
  *Wat voor de volgende fase blijft liggen:* E2's gemeten factor is nog nooit gedraaid — daarvoor moeten er eerst volledige crawls (`--pages 0`) met verdwijn-historie zijn. E3 weegt in de praktijk nul zolang `component_price` leeg is (dat vullen is opzoekwerk, fase 7). De scenario's A en B leveren nu hetzelfde bedrag op omdat de wielset geen prijswaarnemingen heeft; het verschil tussen "compleet" en "wielset apart" is pas zichtbaar zodra die er zijn. De bundelfactor (0,80) en het aandeel van een upgrade dat een koper van een complete fiets betaalt (0,50) zijn heuristieken zonder meting — ze staan als aparte bewijsregel in de uitvoer, maar ze zijn niet gekalibreerd.
- [x] Fase 4 — scoring *(`scoring.py` + `scoring_config.json`: vijf gewogen dimensies (frame, drivetrain, brakes, wheels, extras) uit §7, elk 0-100 met een reden-string per dimensie — zelfde patroon als `deal_reasons`. Eén `Build`-dataclass en één `score_build()` voor zowel advertenties (`build_from_listing()`, op `extract_specs()`/`detect_groupset()`-uitvoer) als de eigen fiets (`build_from_owner_specs()`, op hetzelfde specs-dict dat `valuation.parse_owner_bike()` al uit `mijn_fiets.md` haalt — geen tweede parser). Wielmerk (merk-carbon vs. naamloos) wordt apart herkend via `detect_wheel_branded()`, want `extract_specs()` maakt dat onderscheid niet. `extras` is relatief aan wat de eigenaar al heeft via `owner_already_has` (fase 5 geeft daar `{"computer"}` aan mee bij het scoren van kandidaten — hier nog niet aangesloten). `fits_frame_size()` is de losse, pure poort-rekenkern voor de maat — nog niet gekoppeld aan `frame_height_bounds()` of de database, dat is fase 5. Alle getallen en gewichten staan in `scoring_config.json`, niets hardgecodeerd. 27 tests in `tests/test_quality_scoring.py` (niet `test_scoring.py`, dat bestond al voor `deal_score`), 291 tests groen.*
  *Wat voor de volgende fase blijft liggen:* `build_from_listing()` vult `has_extra_wheelset`/`has_pedals` nooit — `extract_specs()` detecteert die specs niet, dat zou eerst een uitbreiding van fase 2 zijn; voor advertenties tellen die twee extra's dus nog niet mee. `frame_class` (endurance/performance/race) is voor advertenties altijd onbekend om dezelfde reden: geen extractie ervoor. De CLI (`python scoring.py`) scoort alleen de eigen fiets uit `mijn_fiets.md`; er is geen commando dat een hele crawl scoort — dat hoort logisch bij fase 5's upgrade-finder, die de scores toch per kandidaat nodig heeft.)*
- [x] Fase 5 — upgrade-finder en biedlogica *(`upgrade.py`: de maatpoort, het budget per kandidaat, de effectieve prijs, de rangschikking op upgrade per euro en de speelruimte per biedadvertentie. De maatpoort heeft **drie** uitkomsten, niet twee — `frame_height_bounds()` geeft None zowel voor "veld leeg" als voor "onleesbaar", en dat is iets anders dan een maat die niet past; buiten de maat valt af, maat onbekend blijft zichtbaar met een vlag (`--strict-size` gooit die ook weg). Het budget hangt aan de kandidaat zoals §7 voorschrijft: een velremkandidaat krijgt de wielset in zijn *score* (`with_owner_wheels()`, alleen als die wielen beter zijn dan wat er al op zit), een schijfremkandidaat krijgt de opbrengst ervan in zijn *budget*; een onbekend remtype krijgt het lagere velrembudget en geen wielbonus. Effectieve prijs = vraagprijs × onderhandelingsfactor, of de instapprijs bij een bod — nooit een onderhandelingsfactor op een bod, want onder het minimumbod kun je niet kopen. De vraagprijs blijft er los naast staan (`EffectivePrice.asking_eur`). Speelruimte = geschatte waarde − instapprijs, met een eigen benchmark-ladder (waargenomen 2e-hands gemiddelde vóór de mediaan van de zoekopdracht, allebei ×E2-factor omdat het vraagprijzen zijn). Aangesloten op het script: `print_bid_overview()` heeft een `RUIMTE`-kolom en sorteert daarop in plaats van op dealscore (`bid_overview_order()`, `bid_headroom_by_id()` — die laatste importeert `upgrade` lokaal, want `upgrade.py` leest `racefiets_jev.py`). README bijgewerkt voor `upgrade.py`, `scoring.py` (die stond er nog niet in) en de nieuwe kolom. 64 tests in `tests/test_upgrade.py` + 8 nieuwe in `tests/test_bids.py`, 363 tests groen. `tests/helpers.py` heeft er een `repo_file()` bij: de suite las `scoring_config.json` en `mijn_fiets.md` via een kaal relatief pad en viel daardoor om zodra je hem vanuit `tests/` startte in plaats van vanuit de repo-root — dat geldt nu voor beide.*
  *Wat voor de volgende fase blijft liggen:* het rapport heeft nog geen paneel — de kandidaten en de speelruimte zitten alleen in de console en in `upgrade.py`'s eigen CLI; dat aansluiten is fase 6, en `Candidate`/`BidRow` zijn daar met opzet als dataclasses voor klaargezet. `bid_count`/`bid_minimum` staan niet in het schema van §5, dus een uit de database herbouwde biedadvertentie heeft per definitie geen opgehaald bod: `upgrade.py`'s eigen CLI toont daar de vraagprijs met "bod niet opgehaald", terwijl een live run wél het echte bod gebruikt. Die kolommen toevoegen zou het schema uitbreiden en is bewust niet in deze fase gedaan. De speelruimte valt zonder gematchte referentiemodellen terug op één mediaan voor de hele zoekopdracht, waardoor de sortering dan feitelijk op instapprijs neerkomt — dat wordt scherper naarmate fase 7 `reference_prices.csv` met fietsen vult. En één scheefheid die uit fase 4 komt en hier zichtbaar wordt: de eigen fiets scoort op `frame` lager (40) dan een advertentie waarvan het bouwjaar en de frameklasse niet herkend zijn (±54), puur omdat er over de eigen fiets méér bekend is — onbekend scoort neutraal, bekend-en-oud scoort laag. De `--margin` dempt dat, maar de eerlijke oplossing is `frame_class` en `model_year` beter uit advertenties halen (fase 2) of de neutrale aanname in `scoring_config.json` kalibreren; niet stilletjes aan de gewichten draaien. Tot slot: de **waardescore** uit §2 (`geschatte waarde / gevraagde prijs`) heeft nog steeds geen plek. De bouwsteen ervoor staat er wel — `estimate_value()` levert de geschatte waarde per advertentie — maar de upgrade-finder rangschikt op upgrade per euro, niet op prijs, dus er is in deze fase niets dat die naam draagt. Bouw hem in fase 6 als een eigen kolom, en houd hem gescheiden van `deal_score` zoals §2 voorschrijft.*
- [x] Fase 6 — rapport-tabs *(Twee commits, zoals §8 vraagt. Eerst de refactor: `HTML_TEMPLATE` staat nu in `report_template.html` als `string.Template` (`$`-placeholders, `substitute()` faalt hard op een vergeten placeholder), runtime ingelezen; de gerenderde pagina was daarna byte-voor-byte gelijk aan die van ervoor. Daarna de panelen, in een nieuw `report.py`: tabs **Advertenties** (de oude tabel met rijfilters en sortering ongewijzigd, "Bieden" blijft daar een rijfilter) / **Biedpaneel** (op speelruimte, uit `upgrade.bid_panel()`) / **Upgrade** (`find_upgrades()` op de advertenties van deze run, met uitsplitsing per dimensie als tooltip en een `Afgevallen`-lijst met reden) / **Mijn fiets** (scenario A en B als band laag-midden-hoog met n, het budget per route, de volledige bewijslijst met links naar de comps, en de baseline per dimensie). De gekozen tab staat in de URL-hash. Nieuwe vlag `--mijn-fiets` (default `mijn_fiets.md`). De taxatie voor het rapport is alleen-lezen — niets naar `valuation`, dat blijft van `valuation.py`; zonder database (`--no-db`, of het bestand bestaat niet — het wordt dan ook niet aangemaakt) of zonder comps zeggen de twee tabs waarom in plaats van een getal te tonen. De **waardescore** heeft nu een eigen kolom in Upgrade en Biedpaneel (`upgrade.value_score()`), naast en niet in plaats van de dealscore. Eén bewuste afwijking van §2: de noemer is de *effectieve* prijs, niet de kale vraagprijs — de geschatte waarde is al een verkoopprijs (×E2), dus delen door een vraagprijs zou een advertentie precies op de mediaan 0,875 geven en een bod met een vraagprijs vergelijken; zo is 1,00× "kost wat hij waard is". Gecontroleerd in headless Chromium: tabs wisselen, rijfilter en kolomsortering werken, geen console-fouten, bewijslinks klikbaar. 23 nieuwe tests in `tests/test_report_panels.py` + 3 in `tests/test_report.py`, 389 tests groen.*
  *Wat voor de volgende fase blijft liggen:* ~~De scheefheid uit fase 4/5: het eigen model kwam als upgrade (+6) binnen~~ — **opgelost na fase 6** op verzoek van de eigenaar: `upgrade.listing_specs()` neemt het bouwjaar uit de titel als de tekst geen gelabeld bouwjaar heeft, met dezelfde regel als de comp-ladder (`valuation.title_year()`), en zet "bouwjaar N uit de titel" in de redenen. Een Defy Composite 2012-advertentie scoort nu 53 tegen 51 voor de eigen fiets en valt onder de marge af. Wat daarvan overblijft: (1) die +2 komt uit de frameklasse — onbekend is ×1,00, de eigen fiets is endurance ×0,85; `frame_class` wordt voor advertenties nog steeds niet herkend (bewust niet op losse woorden als "race"/"aero", die staan ook in bandennamen en wielbeschrijvingen); (2) een advertentie zónder enig jaar krijgt nog steeds geen leeftijdsverval. Dat is de neutrale aanname in `scoring_config.json` en die kalibreren vraagt data, niet een gok. Het Upgrade-paneel werkt op de advertenties van deze run (mét live opgehaalde biedingen), niet op de hele database zoals `upgrade.py`'s CLI; bij `--bids-only`/`--min-score` ziet hij dus ook alleen wat die filters overlaten. De waardescore staat niet in de hoofdtabel — daar zegt "% v. mediaan" voor vaste prijzen al vrijwel hetzelfde; toevoegen kan als het gemist wordt. Tot slot: `valuation.main()` rekende `empirical_negotiation_factor()` uit maar gaf hem niet door aan `value_subject()`, dus de CLI gebruikte altijd de heuristische E2 — **opgelost na fase 6**, met een test die `main()` op 20 snelle verkopen en 20 blijvers draait.)*
- [x] Fase 7 — referentiedata fietsen *(Twee nieuwe, geforceerd toegevoegde bestanden in plaats van rijen in `reference_prices.csv`, want dat bestand wordt tegen élke query gematcht: `reference_bikes.csv` (10 rijen: Defy Advanced SL, Defy Advanced, Defy Composite 1/2/onbekend — die laatste is de baseline — de aluminium Defy 0-5, Canyon Endurace CF SL(X) Disc en overig, Specialized Roubaix, Trek Domane) en `reference_bike_accessories.csv` (16 rijen: Wahoo Roam v1/v2/3 en Bolt v1/v2/3, Garmin Edge 530/830/540(Solar)/840(Solar)/1030, Favero Assioma Duo/Uno, Garmin Rally). Accessoires staan bewust apart: de eerste match levert de nieuwprijs voor de dealscore, dus een Garmin-rij in het fietsbestand zou een fiets "met Edge 530" op 300% van €299,99 zetten. Beide bestanden hebben drie extra kolommen — `kind`, `brand`, `source_url` — die `load_reference_data()` negeert en `db._import_reference_prices()` nu naar `model` schrijft (zonder die kolommen importeert het als vroeger, als `other`; een onbekend kind geeft een waarschuwing). `db.sync_listing_models()` koppelt nu standaard op patroon ongeacht kind, anders viel elke fietsmatch weg. Elke rij heeft een bron; een nieuwprijs staat er alleen waar een bron een europrijs geeft (Roam v1/v2, Bolt v2, Edge 530/830/540/840 en Solar, Edge 1030, Assioma). Onderweg bleek hoe nodig dat is: een zoeksamenvatting gaf €449,99 voor de Roam v2, de bron zelf zegt €399,99. Gevonden en vastgelegd: de alu Defy 0 van 2012 had óók Ultegra (dus "Defy Ultegra" ≠ carbon), en carbon Defy's zijn vanaf modeljaar 2015 alleen schijfrem. Getest op een echte crawl ("giant defy", 1 pagina): 9 van de 21 advertenties matchten, 12 na toevoeging van "Aluxx" aan de alu-rij (de rest is o.a. "Defy 9", een kale "Giant Defy" en een Cube Attain); `listing_model` wordt gevuld met `kind='bike'`. 13 tests erbij (`tests/test_reference_bikes.py` + import/koppeling in `tests/test_db.py`), 376 tests groen.*
  *Wat voor de volgende fase blijft liggen:* **geen enkele Defy heeft een nieuwprijs.** Giant NL toonde in 2012 geen prijzen op de modelpagina's (gecontroleerd in het webarchief), en de dollarbedragen die wél te vinden zijn spreken elkaar tegen ($2.400 bij Bicycle Blue Book voor de 2012 Composite 1, $3.161 bij opticycles voor de 2013) — die zijn bewust niet omgerekend. De Nederlandse 2012-spec van de Composite 2 is niet gearchiveerd; de rij noemt de Amerikaanse spec en zegt dat erbij. Bij de upgradedoelen spant één patroon meerdere generaties en dus zowel velrem als schijfrem; alleen de Endurace CF SL(X) Disc draagt `better_than_baseline=1`, omdat alleen daar het patroon het remtype vastlegt. Geen nieuwprijzen voor de upgradedoelen (alleen een UK-prijs gevonden, in de specs-tekst gezet). Garmin Rally, Bolt v1, Roam 3 en Bolt 3 staan er zonder prijs in; de Edge 1030-prijs komt uit een Eurobike-verslag, niet uit een persbericht, en de 1030 Plus matcht bewust niets. Niet gedaan: Cube Attain (kwam in de echte crawl voorbij), Cannondale Synapse, groepsets en wielsets. `component_price` (E3) is nog steeds leeg — dat zijn waargenomen tweedehands prijzen uit crawls, geen opzoekwerk. `export_csv()` schrijft nog steeds alleen de zes oude kolommen van één kind, dus exporteren verliest `kind`/`brand`/`source_url`; de CSV's zijn de bron van waarheid, niet de export. En omdat het script maar één `--reference-file` per run leest, komen accessoires in een fietsadvertentie niet in `listing_model` — fase 8 (watchlist) is de plek om accessoires met hun eigen bestand te crawlen.)*
- [x] Fase 7 (uitbreiding) — fietscatalogus *(Op verzoek van de eigenaar: "alle Giant, Cube, Trek en Sensa vanaf 2010 met specs en nieuwprijs", daarna "ga door met andere bekende merken". Dat past niet in `reference_bikes.csv` — daar wint het eerste patroon, dus tien modeljaren "Defy Advanced 2" zouden één dood patroon opleveren — en staat daarom in een eigen bestand, `reference_bike_catalog.csv`: één rij per merk/model/modeljaar, met specs, nieuwprijs, `market` en bron-URL. Bronnen: Giant NL (webarchief + Giants eigen "Oudere modellen"), Trek NL (Treks archief 2011-2026, prijzen uit gearchiveerde overzichten/productpagina's), Sensa (gearchiveerde en huidige sensabikes.com), Cube (huidige cube.eu/nl-nl) en bikezona.com (Spaanse catalogus, `market=ES`) voor Cube tot 2024 en de andere merken. De scripts staan in `catalog_tools/`, de hygiëne in `tests/test_bike_catalog.py`.*
  *Wat blijft liggen:* 99spokes (de beste bron, specs en prijzen per land) blokkeert geautomatiseerde toegang; bikeinsights was onbereikbaar. Cube publiceerde vóór 2022 geen prijs in de HTML (die werd per IP opgehaald), dus Cube vóór 2025 heeft alleen de Spaanse catalogusprijs. Sensa zet geen modeljaar op de pagina: `model_year` blijft leeg, `seen_date` is de archiefdatum. Treks prijzen vóór 2015 en in 2018-2019 zijn dun, omdat die pagina's de prijs pas in de browser laadden. Het remtype is vaak leeg bij oudere fietsen: de remregel noemt dan alleen het model (bijv. "Shimano 105 BR-5800") en dat wordt niet vertaald. De catalogus is nog nergens aangesloten — `valuation.py` zou er de nieuwprijs per modeljaar uit kunnen halen, maar dan moet eerst de koppeling advertentie → catalogusrij er zijn.)*
- [x] Fase 8 — watchlist losse producten *(De `watchlist`-tabel uit §5 is bruikbaar: `db.save_watchlist()`/`get_watchlist()`/`list_watchlists()`/`delete_watchlist()`, en in het script `--watchlist-add NAAM` (slaat `--query` plus de filtervlaggen op die van hun standaard afwijken; draait niets), `--watchlist-list`, `--watchlist-remove NAAM` en `--watchlist NAAM[,NAAM]|all`. Isolatie is het hart: een watchlist-run begint vanaf de *standaard*filters en legt alleen zijn eigen erop (`args_for_watchlist()`), niet vanaf de commandoregel — anders zou `--max-frame-height 58 --watchlist powermeter` elke powermeter wegfilteren, want `filter_by_frame_height()` laat advertenties zonder maat vallen. Welke vlaggen een watchlist meedraagt staat in `WATCHLIST_FILTERS` (prijs, framemaat, bargain-ratio, reference-file, bid-lookup, bids-only, min-score); `--pages`/`--delay`/`--db`/de historiebestanden blijven van de commandoregel, zodat een watchlist een ondiepe geplande run niet stilletjes in een volledige crawl verandert. Elke watchlist krijgt een eigen rapport (`<html>_<naam>.html`, `<output>_<naam>.csv`), dus hij overschrijft het fietsrapport van dezelfde run niet. `--query` heeft nu `None` als default (valt terug op `racefiets`), zodat `--watchlist` zonder `--query` alleen de watchlists draait; een kale run doet precies wat hij deed. Een onbekende naam of een ontbrekende database stopt de run vóór er iets wordt opgehaald, en maakt geen lege database aan. Met een watchlist die `--reference-file reference_bike_accessories.csv` draagt komen accessoires nu wél in `listing_model` — het losse eindje uit fase 7. Echt gedraaid naast `--query luidsprekers --max-price 150`: twee rapporten, elk met eigen filters. 18 tests in `tests/test_watchlist.py`, 427 tests groen.*
  *Wat voor de volgende fase blijft liggen:* er is geen vlag om een watchlist op inactief te zetten — de kolom `active` wordt gerespecteerd door `--watchlist all` en `db.save_watchlist(active=False)` kan het, maar vanaf de commandoregel alleen door hem te verwijderen. Een watchlist-rapport toont dezelfde tabs Mijn fiets/Upgrade als het fietsrapport; die zijn daar zinloos maar onschuldig. En let op bij het kiezen van de zoekterm: "powermeter" levert op Marktplaats vooral complete fietsen mét powermeter op (pagina 1: mediaan ca. €2.500), die met een prijsfilter van €100-500 terecht allemaal afvallen — gerichtere termen ("assioma", "powermeter pedalen") geven meer losse exemplaren. Dat is een keuze voor de eigenaar, niet voor de code.)*
  *Na fase 8 — grondige controle van de zoeklogica tegen de echte site (22-09-2026).* Vier fouten gevonden en opgelost, elk met tests (`tests/test_crawl.py`, plus aanvullingen in `test_db_wiring.py`/`test_watchlist.py`; 461 tests groen):
  1. **Elke zoekterm met een spatie kreeg steeds pagina 1.** `quote()` maakte van de spatie `%20`, en Marktplaats stuurt `/q/giant%20defy/p/2/` door naar `/q/giant+defy/` — pagina 1. "giant defy" over 6 pagina's gaf 31 unieke advertenties van de 159. Nu `quote_plus()`, en `check_page_offset()` stopt de crawl hard als Marktplaats een andere pagina teruggeeft dan gevraagd. **Gevolg voor een bestaande `koopjes.db`:** een eerdere `--query "giant defy" --pages 0` zag maar 30 advertenties en heeft de rest als verdwenen gemarkeerd. De `disappeared_at`/`days_online` van meerwoordige queries uit de tijd vóór deze fix zijn onbetrouwbaar; E2 mag daar niet op leunen.
  2. **De verdwijn-sweep draaide op onvolledige crawls.** `--pages 0` ziet bij "racefiets" ~5000 van 26000+ resultaten (Marktplaats stopt op pagina 167), een mislukte pagina brak de crawl af, en de standaardsortering herhaalt advertenties over pagina's heen (1200 plekken, 951 unieke). Alles daarbuiten werd als verkocht gemarkeerd. `collect_listings()` geeft nu een `CrawlResult` met `complete` terug — alleen waar als geen pagina faalde, het einde bereikt is én het aantal unieke advertenties het totaal van Marktplaats haalt — en de sweep draait alleen dan. Gevolg: voor "racefiets" draait de sweep nooit meer; voor E2 is een smalle, complete crawl nodig (`--query "giant defy" --pages 0 --sort newest` is compleet).
  3. **Een tweede hoofdcategorie werd stil weggegooid.** "powermeter" is dominant in *fietsonderdelen* (255) én *racefietsen* (508); de grootste won, dus elke losse powermeter viel af als "off-topic". Nu meldt het script de overgeslagen hoofdcategorie, en `--category` kiest zelf, server-side gefilterd via de zoek-API (`l1CategoryId` + herhaalde `l2CategoryIds`; het enkelvoud wordt stil genegeerd). Ook een watchlist-filter.
  4. **`--min/max-frame-height` verborg 76% van de fietsen**: zoveel racefietsen hebben geen maat ingevuld. Die blijven nu staan; `--strict-frame-height` geeft het oude gedrag (ook een watchlist-filter). Dit is een bewuste gedragswijziging, in de README beschreven.
  5. **Elke bied-advertentie zonder bod werd een Topdeal.** Marktplaats stuurt `currentMinimumBid: -1` voor "bieden zonder minimum"; de truthiness-test liet dat door als prijs €-0,01, dus 100/100 "Topdeal" en "min. €-0" in de console. Bij racefietsen is 18% FAST_BID. Nu `real_minimum_bid()`: ≤ 0 is geen minimum.
  6. **"Gezocht"-advertenties** (iemand die zoekt) stonden tussen het aanbod en kregen via punt 5 ook 100/100. Niets in de data onderscheidt ze, dus op de titel: "gezocht" aan het begin, aan het eind of tussen haakjes (`is_wanted_ad()`, niet bij "veel/zeer/vaak gezocht").
  7. **Een watchlist negeerde `--bid-lookup` van de commandoregel.** Gevonden in een echte run met `--bid-lookup none` die toch 24 advertentiepagina's ophaalde (en bij een volledige crawl honderden). Bid-lookup bepaalt het aantal verzoeken en staat nu aan de kant van `--pages`/`--sort`; een eerder opgeslagen `bid_lookup` wordt met een waarschuwing genegeerd.
  Daarnaast `--sort newest` (via `/lrp/api/search`, dezelfde API die de site gebruikt): de standaardsortering is niet op datum — van de advertenties van vandaag stonden er 83 van 314 op pagina 1-3 — dus het schema uit fase 1b ("drie keer per dag `--pages 3` voor nieuwe advertenties") miste het meeste. Default blijft `optimized`. Gemeten aanvoer bij `--sort newest --category fietsen-racefietsen` (stats.since van één advertentie per pagina, 20-22 september): ~400-500 per dag, vrij vlak ~25-30 per uur tussen 09:00 en 22:00 (NL-tijd), weinig 's nachts. Eén weekend/maandag/dinsdag, dus geen weekpatroon gemeten. Watchlist-hardening: typecontrole op opgeslagen filters, waarschuwing bij een ontbrekend referentiebestand, `--watchlist` samen met `--watchlist-add/-list/-remove` geweigerd.
  *Wat blijft liggen:* framemaat uit de tekst halen ("maat 56", "56cm" — in de titels alleen al ~14% van de maatloze fietsen) zou het maatfilter weer scherp maken; precisie boven dekking, dus als fase-2-uitbreiding met een eigen testset. Een zelf-stoppende crawl (`--sort newest` tot een hele pagina al bekend is) zou het vaste `--pages` overbodig maken. `listing.query` wordt overschreven door de laatste query die een advertentie zag; bij overlappende zoekopdrachten kan de sweep van query B dan een advertentie markeren die alleen nog onder query A online staat — zeldzaam zolang de sweep alleen op complete crawls draait, maar niet uitgesloten.
  *Tweede controleronde (22/23-09-2026), op verzoek van de eigenaar: "een overzichtelijk en automatiseerbaar systeem".* De hele keten op echte data gedraaid (crawl → valuation.py → upgrade.py → rapport). Gevonden en opgelost: (1) de upgrade-finder zette een crankstel, powermeter en kettingblad op 1-3 — sinds watchlists onderdelen in koopjes.db zetten keek hij naar alles; nu alleen advertenties uit de categorie racefietsen (uit de URL, `category_from_url()`), dezelfde poort voor de comps. (2) De enige comp voor de carbon Defy Composite was een aluminium "Giant Defy 1" van €250 (taxatie €219): trede 1-2 keken niet naar materiaal. `reference_bikes.csv` kreeg een kolom `frame_material`, alleen gevuld waar de bestaande specs-tekst met bron het materiaal noemt; comps met ander materiaal vallen af op elke trede. METHOD_VERSION → e1e2e3-2. (3) Daarmee is er nu géén taxatie (geen Defy Composite met bouwjaar online), en zonder taxatie geen budget: `verkoopprijs_handmatig` in mijn_fiets.md is de terugval, leeg gelaten — dat getal is aan de eigenaar. (4) `listing.query` werd door elke run overschreven, dus een Defy die overdag via "racefiets" langskwam viel buiten de nachtelijke sweep van "giant defy": migratie 2 voegt `listing_query` toe. Daarbovenop de automatisering: `schedule.json` (zoekopdrachten + tijdsloten) en `koopjes.py` (`run`, `status`, `schedule`, `overview`) met lock, log en `overzicht.html` (laatste cijfers per zoekopdracht, beste upgrades, nieuwe advertenties, planning). `racefiets_jev.py --summary-file` levert de cijfers. 505 tests groen; beide rondes live gedraaid.
  *Wat blijft liggen:* (a) trede 3 eist een bouwjaar, en fietsen met Ultegra 6700 noemen dat zelden — de groepsetgeneratie als bouwjaarband gebruiken kan, maar alleen met een opgezochte, van bron voorziene tabel (CLAUDE.md: geen groepsetgeneraties uit het hoofd). (b) Een trede "zelfde model, bouwjaar onbekend" zou de twee Defy Composites zonder jaar (€600, €650) laten meetellen; dat wijkt af van de ladder in §6 en is een keuze voor de eigenaar. ~~(c) comps sluiten álle biedadvertenties uit (fase 3), ook MIN_BID met een gewone vraagprijs — ruim de helft van het aanbod; exact maken vraagt dat de database weet of `price_eur` een vraagprijs of een bod is.~~ **Opgelost 27-09-2026**, zie hieronder. (d) `koopjes.py schedule` drukt de Taakplanner-regels af maar voert ze niet uit; op Windows zelf niet getest.
- [x] Buiten het plan — slapers *(Op verzoek van de eigenaar, na een Cannondale CAAD10 die op 23-09-2026 voor een bod van €45 wegging, twee uur na plaatsing: titel "Heren racefiets", beschrijving "Moet weg wegens verhuizing!", merk "Overige merken", bieden zonder minimum. De dealscore kon er niets mee — geen prijs, geen herkend model. `sleepers.py` geeft zulke advertenties een eigen signaal (0-100, los van dealscore en waardescore): algemene titel (verplicht), dunne beschrijving, haast-frase, bod zonder bod of prijs ≤60% van de mediaan, nieuw. Uitgesloten: een merk in de beschrijving (merken uit `reference_bike_catalog.csv` plus een korte lijst die in de crawl opdook) en gereserveerde advertenties. Alles uit de zoekresultaten, geen extra verzoeken; `Listing` kreeg vijf velden achteraan (`thin_content`, `reserved`, `image_urls`, `sleeper_score`, `sleeper_reasons`), dus de CSV krijgt alleen kolommen bij. Tab **Slapers** in het rapport met foto's, `SLAPERS`-blok in de console, en nieuwe slapers met eerste foto in `overzicht.html`. Gemeten op 240 racefietsen (8 pagina's newest): 13 algemene titels, 8 daarvan met een merk in de beschrijving, 1 slaper. Stap 2 uit het gesprek ("breder zoeken op categorie") bleek niet nodig: met de categorie gezet geeft "racefiets" de hele categorie (12780 resultaten met én zonder zoekterm). 29 tests in `tests/test_sleepers.py`, 549 tests groen.*
  *Wat blijft liggen:* (a) leren welke signalen echt voorspellen: `reserved` wordt nu gelezen maar niet opgeslagen; als `koopjes.db` bijhoudt wanneer een advertentie gereserveerd raakt, is "binnen een paar uur weg" een meetlat voor de gewichten, die nu met de hand gekozen zijn. (b) De advertentiepagina (weergaven, favorieten, hoe lang de verkoper actief is) alleen voor de topkandidaten ophalen, net als `--bid-lookup`. (c) Een melding (geluid, zoals bij `notify_better_matches()`) bij een nieuwe slaper — snelheid is bij deze advertenties alles. (d) De woordenlijst en merkenlijst zijn met de hand, op één crawl; bijhouden als er slapers zijn die het niet hadden moeten zijn.
  *Herkenning in de kwaliteitsscore (23-09-2026), op vraag van de eigenaar ("ik zie nooit een fiets beter dan de mijne").* Op echte data scoorde een Trek Émonda SL5 Disc 2022 37 en een Scott Addict 2026 Force AXS 38 tegen 51 voor de eigen Defy: de eigen fiets is volledig bekend uit `mijn_fiets.md`, een advertentie heeft alleen titel + ~200 tekens, en wat daar niet in staat scoort neutraal-laag. Opgelost wat uit de tekst te halen is: "Disc" in de modelnaam is een schijfrem (niet "disc wiel"), "Force AXS"/"Red eTap" is SRAM zonder dat "SRAM" er staat, en een wielmerk zonder materiaal ("Roval Rapide CLX") krijgt `wheels.merk_materiaal_onbekend` (60). 530 tests groen. *Wat blijft liggen:* (a) de beste fietsen binnen €850 komen nu op 52-56 tegen 51 en halen de marge van 5 nog nét niet — remtype en wielen staan meestal pas in de volledige omschrijving op de advertentiepagina, die alleen de bid-lookup ophaalt; die pagina voor de paar kandidaten binnen budget ophalen is de volgende stap. (b) Losgelaten: onbekende dimensies helemaal weglaten in plaats van neutraal scoren — dan scoort een advertentie met alleen "carbon 2024" in de titel op het frame alleen, en dat is erger. (c) Nog steeds geen taxatie zonder `verkoopprijs_handmatig`, en `racefiets_jev.py` zonder `--reference-file reference_bikes.csv` taxeert op een aluminium Defy — gebruik `koopjes.py run` of geef die vlag mee.
- [x] Buiten het plan — opschoning en controle op echte data *(27-09-2026, op verzoek van de eigenaar na een extern advies dat deels niet klopte. Opgelost: (1) `upgrade.py` en `scoring.py` crashten met een traceback als ze niet vanuit de repo-map werden gestart — de standaardconfig was een kale bestandsnaam; nu `scoring.BUNDLED_CONFIG_PATH`, naast het script (`koopjes.py` had er geen last van, die start alles vanuit de repo-map). (2) `--reference-file reference_bike_catalog.csv` herkende stil niets; `load_reference_data()` waarschuwt nu bij een bestand zonder `pattern`-kolom. (3) Tekstvelden met een `null`-waarde (`title`, `location`, `vipUrl`, `facets`, een attribuut-`value`) werden `None` of lieten `parse_listing()` crashen; nu `text_value()`. (4) Verouderde zinnen in README, NEXT_STEPS en `mijn_fiets.md` over wie de catalogus en de intake leest. 563 tests groen. Gecontroleerd met twee echte crawls (giant defy volledig, 129 advertenties; racefiets 8 pagina's maat 54-58, 222) → valuation.py → upgrade.py → rapport.*
  *Wat blijft liggen:* (a) ~~**De verdwijn-sweep sneuvelt op precies de gebeurtenis die hij moet meten.**~~ **Opgelost 27-09-2026**, zie de sweep-regel hieronder. De volledige crawl van "giant defy" zag 164 van 165 resultaten en sloeg de sweep over; een tweede crawl direct daarna: 164 van 164. Er was tijdens het bladeren een advertentie verdwenen, waardoor de rest een plek opschoof. Bij een actieve zoekterm gebeurt dat vaak, en dan komt E2 nooit aan zijn 20 waarnemingen. Oplossingsrichtingen, keuze voor de eigenaar: één keer opnieuw bladeren en de twee passes samennemen, of een advertentie pas verdwenen noemen na twee gemiste complete-op-één-na crawls. (b) De week-ronde (`racefietsen`, alle pagina's) is nooit compleet — Marktplaats stopt rond 5000 — en sweept dus nooit; hij levert wel prijzen. (c) Het Biedpaneel waardeert elke advertentie op de mediaan van de hele zoekopdracht (€750 × 0,88 bij racefiets), ook een verkeerd ingedeelde zadelpen van €20; "speelruimte" is daar dus vooral "goedkoopste eerst". (d) Nog open van hierboven: comps zonder MIN_BID (bij giant defy 64 van de 129), omschrijvingen van 200 tekens, geen taxatie zonder `verkoopprijs_handmatig`.)*
- [x] Buiten het plan — vraagprijzen van bied-advertenties in de taxatie *(27-09-2026, eerste van de openstaande punten op verzoek van de eigenaar. `Listing.price_is_asking` (een property, geen veld — anders krijgt elk bestaand koopjeslog een kolom erbij): een prijs is een vraagprijs tenzij er al op geboden is; dezelfde regel die `append_reference_price_observations()` al gebruikte. Migratie 3 zet hem als kolom `listing.price_is_asking`; `fetch_comp_candidates()` neemt MIN_BID zonder bod nu mee, rijen van vóór de kolom (NULL) houden de oude regel tot een crawl ze opnieuw ziet. Op echte data (giant defy + racefiets): 146 comps in het meetvenster in plaats van 44, en voor het eerst een taxatie van de eigen fiets (n=1, indicatief, €284). Dat legde een tweede fout bloot: elke taxatie verving `verkoopprijs_handmatig`, ook een indicatieve op één comp, terwijl `mijn_fiets.md` het omgekeerde belooft. Nu `upgrade.budget_basis()`, gedeeld door CLI en rapport: een harde taxatie (n≥5) wint, een indicatieve niet van het bedrag van de eigenaar. Twee tests aangepast van "elke bied-advertentie valt af" naar "een advertentie met biedingen valt af" (dat was de bedoeling; het ontbrekende biedtype maakte ze dubbelzinnig), zes nieuwe.*
  *Wat blijft liggen:* FAST_BID zonder bod telt ook als vraagprijs (de ondergrens van de verkoper), maar heeft alleen een prijs als de bid-lookup draaide.
- [x] Buiten het plan — verdwijn-sweep bij een crawl die bijna compleet was *(27-09-2026. Gekozen voor de variant zonder extra verzoeken (CLAUDE.md: de crawl-frequentie niet opvoeren): `CrawlResult.near_complete` als alle pagina's laadden, het bladeren tot het eind liep en er hooguit `near_complete_max_missing()` ontbreken (3, of 2% van het totaal). Dan zet `db.sweep_disappeared(confirmed=False)` alleen `missed_at` (migratie 4); een advertentie die ook de volgende volledige crawl mist, is verdwenen per de eerste mis, en `days_online` rekent vanaf dan. Elke crawl die hem wél ziet wist `missed_at` — en nu ook `days_online`: die bleef eerder staan bij een advertentie die na een verdwijning terugkwam, en E2 telde hem dan als snelle verkoop. De paginalimiet (duizenden te weinig) en de herhalingen van de standaardsortering (~20%) vallen ver buiten de marge. 10 nieuwe tests.*
  *Wat blijft liggen:* twee bijna-complete crawls die toevallig dezelfde levende advertentie missen, markeren hem ten onrechte; de volgende crawl die hem ziet herstelt dat. De marge van 3/2% is gekozen op één waarneming (1 van 165) — bijstellen als de logs anders laten zien.
- [x] Buiten het plan — kenmerken uit de zoekresultaten *(27-09-2026. De zoekresultaten dragen in `extendedAttributes` wat de verkoper zelf aanklikte: `material` bij 17 van 30 racefietsen, soms `brakeType`. Het script las alleen `condition` en `frameHeight`. Nu `site_specs()` in `parse_listing()`, alleen waarden die één ding zeggen (Carbon/Aluminium/Staal/Titanium, Velgrem/Schijfrem/…), in de woorden van `extract_specs()`; opgeslagen als `spec`-bron `marktplaats`, gelezen via `db.read_listing_specs()` (tekst wint, zelfde volgorde als `listing_spec_dict()` live). `Listing.site_specs` is geen CSV-kolom (`metadata={"csv": False}`), zodat bestaande koopjeslogs niet gaan waarschuwen. Op 240 echte racefietsen: materiaal voor 190, waarvan 114 alleen via Marktplaats; remtype voor 28. 6 nieuwe tests.*
  *Wat blijft liggen:* `numberOfGears` telt versnellingen ("Meer dan 20"), geen tandwielen achter, dus niet gebruikt. De groepset staat er niet in; die is het grootste gat in de kwaliteitsscore (onbekend 30 tegen Ultegra 80) en staat alleen in de volledige omschrijving.
- [x] Buiten het plan — volledige omschrijving voor kanshebbers (`--detail-lookup`) *(27-09-2026. Punt (a) van "Herkenning in de kwaliteitsscore": de advertentiepagina ophalen voor de paar kandidaten binnen budget. `upgrade.detail_lookup_targets()` gebruikt de poorten van `find_upgrades()` behalve de score (die is juist wat het fragment onderschat): racefiets, maat niet fout, effectieve prijs ≤ het ruimste budget, nog niet opgehaald; hoogste huidige score eerst, max. `DETAIL_LOOKUP_LIMIT` = 10 per run, `--delay` ertussen. De pagina (server-gerenderd, 27-09-2026 gecontroleerd) levert de omschrijving (`data-collapsable="description"`) en de Kenmerken; opgeslagen in migratie 5 (`full_description`, `details_fetched_at`) en bij latere runs zonder verzoek teruggezet. `frame_height` blijft in de database staan als de zoekresultaten hem leeg laten. Twee herkenningsregels aangescherpt omdat de langere tekst ze liet ontsporen: een gelabelde groepsetregel wint van een hoger onderdeel verderop (de eerste pagina had "Groepset: Ultegra" en "Cassette: Dura Ace" → werd Dura-Ace), en "Garmin houder"/"Wahoo Kickr" is geen fietscomputer. Randgeval opgelost: bij een database die nog niet bestond gaf het rapport geen budget, ook niet met `verkoopprijs_handmatig`. De testsuite deed na deze wijziging 24 echte verzoeken (hele-run-tests met het echte `mijn_fiets.md`); `tests/helpers.py` blokkeert `fetch_listing_page` nu voor alle tests. Op echte data: 10 pagina's, één nieuwe kandidaat (Prorace carbon, Campagnolo Record 10-speed, €200 — op het fragment scoorde een vergelijkbare 32). 9 nieuwe tests.*
  *Wat blijft liggen:* een verkeerd ingedeeld onderdeel in de racefietsen-categorie (een wielset) kost een verzoek; de categorie is het enige wat de selectie ervan weet. De taxatie leest de volledige tekst van een comp waar die er is — dat geldt maar voor een handvol advertenties, maar een omschrijving die een ander model noemt ("vergelijkbaar met een Defy") kan de familie-herkenning daar misleiden. Bouwjaar en frameklasse staan zelden op de pagina; die blijven de grootste onzekerheid in de score.
- [x] Buiten het plan — resellen: waarde per advertentie in het Biedpaneel *(27-09-2026. De speelruimte rekende elke advertentie op de mediaan van de hele zoekopdracht (€750 × 0,88 bij racefiets), dus bovenaan stonden een zadelpen van €20, schoenen en een rollenbank. Onderdelen zijn in de zoekresultaten niet te herkennen (op 90 racefietsen-advertenties geen kenmerk dat alleen bij onderdelen voorkomt; een pedaal had zelfs `material: Carbon`), dus geen onderdelenfilter op gokwerk. In plaats daarvan een trede tussen referentiemodel en zoekmediaan: `upgrade.segment_benchmarks()` — mediaan vraagprijs van vergelijkbare fietsen uit dezelfde set advertenties, zelfde framemateriaal en groepsettier, versmald tot velrem/schijfrem waar dat bekend is en er genoeg zijn; minimaal `SEGMENT_MIN_N` (= 5, de harde grens van de taxatie), zonder de advertentie zelf, zonder lopende biedingen. De zoekmediaan blijft als laatste trede maar heet nu `grof` (`ValueEstimate.rough`) en zakt in het Biedpaneel onder de echte schattingen; de console-kolom RUIMTE toont er geen getal voor. Ook de waardescore (Upgrade- en Biedpaneel) rekent met de segmenten. Op echte data (238 racefietsen uit de database): 44 biedadvertenties met een echte schatting, 132 grof, 40 onbekend; bovenaan nu carbon Dura-Ace/Ultegra-fietsen in plaats van onderdelen. 6 nieuwe tests, één aangepast (een biedadvertentie waar niets over bekend is, krijgt in de console geen getal meer).*
  *Wat blijft liggen:* (a) het segment mengt nog modeljaren — "carbon, Ultegra" zonder remtype omvat 2009 en 2024; het remtype vult zich met `--detail-lookup` en de Marktplaats-kenmerken, maar de velrem-groep had op de eerste dag 5 fietsen (4 zonder de advertentie zelf). Een bouwjaarband als extra trede zodra genoeg advertenties een jaar hebben. (b) Beter dan vraagprijzen: de prijzen van advertenties die binnen 14 dagen verdwenen (de "snel weg"-groep van E2) per segment — dat is wat er echt voor betaald wordt. Kan zodra de verdwijn-sweep een paar weken gelopen heeft. (c) Kosten van doorverkopen (onderhoud, banden, tijd) zitten nergens in; speelruimte is geen winst.

- [x] Buiten het plan — fietscomputers: upgrade en flipmarge *(28-09-2026, op verzoek van de eigenaar, die een lijst van 77 fietscomputers aanleverde. Die lijst had 44 rijen met verschoven kolommen, 51 rijen zonder bron en een handvol feitelijke fouten (Polar V650/M460 zonder ANT+, CatEye Padrone Digital zonder GPS, Edge 520/Explore/Explore 2 zonder wifi, Edge 510 zonder kaarten, Sigma ROX 2.0 zonder sensoren, dollar- en pondprijzen als euro). Nieuw bestand `reference_bike_computers.csv` (81 rijen, met `git add -f`): de kolommen van de eigenaar plus `pattern`, `bediening`, `route_sync`, `rerouting`, `planning_op_apparaat`, `schakel_integratie`, `workouts`, `klimfunctie`, `ondersteund` en `prijs_bron`, met vaste woorden per kolom. Bronnen: vooral DC Rainmaker-reviews per model, Garmin-handleidingen en -persberichten, merksites; een prijs alleen waar een bron euro's geeft. De eigenaar koos de weging: route erop + rerouting, planning op het apparaat en training het zwaarst, knoppen boven touch, aftrek voor merken zonder updates (Pioneer, Karoo 1/2; Lezyne licht), upgrade en flipmarge apart. `computers.py` + `computer_scoring.json`; eigen tab "Fietscomputers" en een consoleblok, `Listing.computer` is geen CSV-kolom. Op een echte crawl ("garmin edge", 1 pagina) 21 van de 22 titels herkend; twee advertenties "scherm vervangen" (reparatiedienst) stonden eerst boven aan de flipmarge en worden nu apart gehouden. 24 tests in `tests/test_computers.py`, 626 tests groen.)*
  *Wat blijft liggen:* (a) veel rijen zijn nog leeg — Edge 200/205/305/605/705, Bryton 330-530, XOSS, Magene C506/C606 Pro, iGPSPORT BiNavi/BSC300T, BOLT 3 — en scoren daardoor laag; dat is "onbekend", niet "slecht", en de tab zegt het per model. Ontbrekende modellen: Edge Touring (Plus) (kwam al voor in de crawl), Edge 20/25, Bryton 420/320, iGPSPORT iGS630. (b) De Roam v1 zonder versienummer vangt ook v2/v3 op, zoals in `reference_bike_accessories.csv`; een "Hammerhead Karoo" zonder nummer wordt niet herkend. (c) De flipmarge rekent op vraagprijzen maal 0,875 — dezelfde ongekalibreerde heuristiek als de taxatie; na genoeg verdwenen advertenties kan die per model gemeten worden. (d) `reference_bike_accessories.csv` blijft de nieuwprijzen voor de dealscore leveren; de twee bestanden overlappen voor de Wahoo's en de Edge 530-1030.
- [x] Buiten het plan — fietscomputers: volledige crawl en herkenning aangescherpt *(28-09-2026. De zoekopdracht `fietscomputer` in `schedule.json` zoekt nu op alle 17 merken uit `reference_bike_computers.csv`, zonder prijsgrens. Volledige crawl van de categorie: 361 advertenties (Stages Dash en COROS Dura hadden geen resultaten). Titel-herkenning ging van 244 naar 291 door (1) de fietswoord-regel alleen te laten gelden vóór de modelnaam ("Garmin Edge 800 fiets navigatie", "Edge 130 MTB fietscomputer" vielen weg) en (2) modellen toe te voegen die in de crawl voorkwamen: Edge Touring (bron) en Touring Plus, Edge 20/25, ELEMNT MINI en Bryton Rider 420 (bron), en alleen-herkenning voor Bryton 320/50/10, Sigma ROX 10.0, Lezyne Micro/Macro, iGPSPORT BSC100S/BSC200S/iGS50E, Magene C706, XOSS G/G+, Mio Cyclo, Teasi — die scoren 0 op functies maar krijgen wel een flipmarge. Herkenning op de advertentietekst als terugval onderzocht en verworpen: 6 extra treffers, waarvan 5 hoesjes, houders of een Mio. Losse onderdelen (LCD, color kit, koord) en goedkope houders (houderwoord ergens in de titel én onder 40% van de mediaan van het model) tellen niet meer als upgrade, flip of vergelijkingsprijs; die stonden eerst bovenaan de flipmarge. 628 tests groen.)*
  *Wat blijft liggen:* een houder van een model met minder dan 3 andere advertenties (een "Karoo 3 houder" voor €20) wordt niet herkend als accessoire — de nieuwprijs als tweede ijkpunt zou helpen, maar die ontbreekt juist bij zulke modellen. Een flipmarge op een lopend bod (`(bod)`) is een momentopname; het bod loopt nog op.
- [x] Buiten het plan — fietscomputer-dashboard *(28-09-2026, op verzoek van de eigenaar: "een master webpagina, nu heb ik ±15 HTML's die niet met elkaar geïntegreerd zijn; duidelijk hoeveel ik per flip kan maken; een aparte tab voor upgrades; houd het bij de fietscomputers; filter de mounts, houders en hoesjes eruit maar behoud alle computers". `dashboard.py` bouwt `dashboard.html` uit `koopjes.db` (alleen lezen): tabs Flips (winst met band en soort prijs, plus een maximaal bod voor advertenties zonder prijs), Upgrades (punten, netto bijbetalen na verkoop van de eigen Roam v1, wat je erbij krijgt/inlevert), Alle computers (ook "model onbekend", met zoeken/merkfilter/alleen nieuw), Marktprijzen per model en Uitgefilterd (met reden, om na te kijken). `koopjes.py` bouwt het na elke ronde (`python koopjes.py dashboard` los), `overzicht.html` linkt ernaar, en de zoekopdracht `fietscomputer` heeft `"report": false` — racefiets_jev draait die met `--no-html`, dus de 17 losse merkrapporten verdwijnen. Filter herschreven als `computers.classify_title()`: één soort per titel (computer/twijfel/accessoire/onderdeel/defect/gevraagd/fiets) op basis van waar het accessoirewoord staat t.o.v. de modelnaam en of er een koppelwoord of apparaatwoord tussen staat; twijfel beslist de prijs (mediaan → nieuwprijs → €30). Op de volledige crawl (361 advertenties) precies 18 uitgefilterd, geen echte computer kwijt; titels zonder bekend model gaan door `classify_unknown()` en blijven als "model onbekend" zichtbaar. Advertenties uit een fietscategorie tellen niet meer mee (een "Giant Defy met Garmin Edge 530" van €900 zou anders een vergelijkingsprijs zijn). Winst trekt `costs_eur` af (standaard €0, instelbaar). Migratie 6: `listing.image_urls`, voor de foto's. De tab Fietscomputers in het gewone rapport verschijnt alleen nog als de run computers bevat. 657 tests groen; end-to-end gedraaid met een scratch-schedule (2 merken, 1 pagina): geen losse rapporten, wel dashboard.html.)*
  *Wat blijft liggen:* het dashboard is alleen voor fietscomputers; racefietsen staan nog in `overzicht.html` en de losse rapporten — die integreren is de volgende stap als de eigenaar dat wil. Een lopend bod staat niet in de database (alleen dat het een bod is), dus de winst op zo'n advertentie is een momentopname. De foto's laden in je eigen browser; in de sandbox van deze sessie kon Chromium ze niet tonen (proxycertificaat), wel is gecontroleerd dat de URL's werken.
