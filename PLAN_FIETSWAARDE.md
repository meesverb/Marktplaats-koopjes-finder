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

Wat daar nog open staat (details in `mijn_fiets.md`, §Nog open): de staat
(kilometerstand, slijtage, schade), wat er meegaat bij verkoop, de
verkoopregio, en of er geld bij mag boven op de opbrengst.

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
| `extras` | powermeter, fietscomputer, extra wielset, pedalen |
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
- **Deze fase is opzoekwerk, geen programmeerwerk.** Modeljaren,
  groepsetgeneraties en nieuwprijzen zijn precies waar een taalmodel
  overtuigend naast zit. Zoek elk getal op, noteer de bron, en gok nooit —
  liever een lege kolom dan een verzonnen nieuwprijs, want die vervuilt de
  taxatie voorgoed. Geef deze fase bij voorkeur aan een sterker model of doe
  hem met de hand.
- **Acceptatie:** `check_reference_overlaps.py` meldt geen onbedoelde
  overlappen; elk model heeft een bron.

### Fase 8 — Watchlist *(na 1)*
- `watchlist`-tabel bruikbaar maken: benoemde zoekopdrachten met eigen filters
  voor losse producten.
- **Acceptatie:** een watchlist "powermeter" draait met eigen prijsfilters
  zonder de fietsqueries te beïnvloeden.

## 10. Werkafspraken voor agents

- **Ontwikkel op `main`.** Commitbericht begint met `Fase N:`. (Dit plan
  noemde eerder `claude/clever-dijkstra-64tu8z`; die branch is samengevoegd en
  wordt niet meer gebruikt.)
- **Begin elke sessie met `git pull`.** Er werken soms meerdere sessies
  tegelijk aan deze repo — één die data verzamelt (`mijn_fiets.md`) en één die
  code schrijft. Pak niet twee fases tegelijk in twee chats.
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

- [x] Fase 0 — intake eigen fiets *(kern vastgesteld in `mijn_fiets.md`; zes detailpunten nog open, zie §4)*
- [x] Testsuite *(87 tests in `tests/`; hoorde bij fase 1, is vooruit gedaan)*
- [ ] Fase 1a — `db.py` los, nog niet aangesloten
- [ ] Fase 1b — aansluiten op het script
- [ ] Fase 2 — spec-extractie en meervoudige matches
- [ ] Fase 3 — waarderingsmotor
- [ ] Fase 4 — scoring
- [ ] Fase 5 — upgrade-finder en biedlogica
- [ ] Fase 6 — rapport-tabs
- [ ] Fase 7 — referentiedata fietsen
- [ ] Fase 8 — watchlist losse producten
