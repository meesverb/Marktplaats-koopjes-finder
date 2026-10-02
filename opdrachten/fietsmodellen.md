# Opdracht: racefietsen koppelen aan fietsmodellen, zelf modellen beheren, en vergelijken met wat snel verkocht werd

> **Stand (02-10-2026): stap 1 (A t/m E) en stap 2 (F en G) zijn gebouwd.**
> Wat er is en welke keuzes daarbij gemaakt zijn staat in `NEXT_STEPS.md`
> ("Fietsmodellen").

Voor een nieuwe sessie die dit bouwt. Lees eerst `CLAUDE.md` (harde regels,
valkuilen) en werk vanaf een verse `main`. Alles hieronder komt uit gesprekken
met de eigenaar op 30-09 en 01-10-2026; zijn keuzes staan er letterlijk bij.
Wijk er niet van af zonder het te vragen.

## Waarom

Op `/racefietsen` (`racebikes.py`) krijgt elke fiets een flipschatting: wat
hij naar verwachting opbrengt, uit de prijzen van vergelijkbare fietsen. Die
vergelijking was eerst op onderdelen (materiaal + groepset + rem), en dat is
"appels met peren" (de eigenaar): een carbonfiets uit 2024 is niet te
vergelijken met een uit 2014, net als Di2 of Ultegra. Inmiddels vergelijkt
hij op model (`bike_identity.py`), maar:

- de modellen komen alleen uit `reference_bikes.csv` (339 patronen, scheef:
  61 Felt) of uit de titel (merk + modelwoord uit
  `reference_bike_catalog.csv`, of het woord na het merk). Op 100 echte
  titels: 58 met herkend model, maar maar ~6 met bouwjaar;
- een verkeerde koppeling kun je niet rechtzetten, en een model dat nergens
  staat kun je niet toevoegen;
- er wordt vergeleken met vraagprijzen, niet met waarvoor fietsen echt
  weggingen.

De eigenaar wil: **elke fiets gekoppeld aan een fietsmodel; hangen daar
bijvoorbeeld 10 andere advertenties aan, dan zie je of deze goedkoop is
vergeleken met die 10.** En: **"als er nog geen fiets is waar het aan
gekoppeld kan worden, dat je die zelf aan kan maken of toe kan voegen, en dat
ik kan scrollen door een lijst met alle fietsen(modellen)".**

## Zijn keuzes (01-10-2026)

| Vraag | Antwoord van de eigenaar |
| --- | --- |
| Waar komen de modellen vandaan? | **Automatisch + ik corrigeer.** Het systeem maakt zelf modellen uit de advertenties; jij kunt op de pagina een koppeling goedkeuren, wijzigen, een fiets aan een ander model hangen. Wat hij aanpast gaat voor. |
| Hoe fijn is een model? | **Model + uitvoering + generatie, en anders trapsgewijs.** Bv. "Trek Domane SL6", generatie = bouwjaar ±2. Te weinig vergelijkbare (< 5)? Een stap grover, en de kaart zegt op welk niveau. |
| Generaties | **Jaarvenster ±2.** Géén generatiejaren opzoeken of verzinnen (CLAUDE.md: "Verzin geen marktfeiten"). |
| Met welke prijzen vergelijken? | **Vooral wat snel wegging.** |
| Wanneer is iets "snel weg"? | **Binnen 7 dagen** (verdwenen ≤ 7 dagen na eerst gezien), of gereserveerd en daarna verdwenen. |
| Bouwjaar onbekend (meestal) | **Allebei:** automatisch de volledige beschrijving ophalen voor kanshebbers, én zelf invullen/verbeteren op de kaart. |
| Corrigeren | **Op de kaart** (knoppen *klopt* / *ander model*, met bouwjaar) en **regels leren** (na een paar dezelfde correcties een regel voorstellen die hij bevestigt). Een aparte lijst "te controleren" wilde hij niet. |
| Lijst van modellen | Een **scrollbare lijst met alle fietsmodellen** (zoeken erin), en een **nieuw model aanmaken** als het er niet in staat. |

## Volgorde

Bouw het in twee stappen, elk met eigen commit(s) en groene tests:

- **Stap 1** (dit eerst): modellen + uitvoering + eigen koppelingen + de
  modellenlijst met aanmaken + de nieuwe vergelijkingstrap + snel-verkocht-
  prijzen. Onderdelen A t/m E hieronder.
- **Stap 2**: regels leren (F) en bouwjaar ophalen voor kanshebbers (G).

## Wat er al is (lees deze bestanden)

| Bestand | Wat erin staat dat je nodig hebt |
| --- | --- |
| `racebikes.py` | de pagina `/racefietsen`. `_read()` leest alle racefiets-rijen één keer; `load_listings()` (actief = gezien binnen 8 dagen van de nieuwste) en `load_pool()` (laatste 180 dagen, ook verdwenen, alleen met vraagprijs) bouwen daaruit `Listing`s. `estimate()` geeft (verkoopprijs, onderbouwing, niveau, vergelijkingsfietsen, mediaan). `build_base()` is het zware deel (één keer per ronde, gecachet in `dashboard.LiveCache.racebikes`), `bike_json()` maakt per fiets een JSON-object met korte sleutels, `render()` de pagina; de kaarten tekent JavaScript (`JS`, functie `card(b)`) uit die JSON, 40 tegelijk. Weergaven: Te beoordelen / Favorieten / Mijn biedingen / Alle / Weggezet / Modellen / Patronen. De weergave **Modellen** bestaat al (`drawModels()` in de JS: per groep aantal, gekoppeld, mediaan, laagste; klik = filter `modelFilter`). |
| `bike_identity.py` | `identify(listing) -> Identity` (merk, familie, materiaal, jaar, disc, electronic, speeds, tier, reference), `Pool` (index per model/opbouw/referentie), `comparables()` (de huidige trap), `NOT_A_FAMILY` / `NOT_A_MODEL_AFTER_BRAND` (gewone woorden die geen model zijn: "maat 56" werd ooit een Pinarello MAAT), `fold()` (kleine letters zonder accenten). |
| `dashboard.py` | de server (`DashboardHandler`, `do_POST`). Acties in `ACTIONS`; voor `/racefietsen` stuurt de pagina `markt=racefietsen`, en dan antwoordt de server met JSON `{"message", "bike"}` via `rb.bike_update()` (zie `race = ...` in `do_POST`, en `RACE_LIVE_ACTIONS`). `LiveCache.racebikes()` cachet `build_base()` op `data_stamp(db_path, trades=False)`. `LIVE_JS` (gedeeld) definieert al `toast`, `say()`, `pageData`: declareer die niet opnieuw in de racefiets-JS. |
| `db.py` | **migratie 19 staat er al** (commit van 01-10-2026): tabellen `bike_model (id, name UNIQUE, brand, family, variant, created_at)` en `bike_link (item_id PK, model_id NULL, year NULL, confirmed, set_at)`, met `add_bike_model()`, `list_bike_models()`, `set_bike_link()`, `list_bike_links()` en `db.MODEL_TABLES`. Nog nergens gebruikt. |
| `upgrade.py` | `listing_specs()` (bouwjaar uit tekst of titel), `entry_price()`, `effective_price()`, `find_upgrades()`. |
| `valuation.py` | `NEGOTIATION_DEFAULT[1]` (0,875), `DEFAULT_COMP_WINDOW_DAYS` (180), `dutch()`. |
| `tests/test_racebikes.py` | bestaande tests van de pagina (`Case` maakt een database met fietsen; `LiveTest` start de server). Breid uit, niet vervangen. |

## Stap 1

### A. Het model van een fiets: merk + familie + uitvoering

Breid `Identity` uit met `variant` (uitvoering) en de eigen koppeling:

- **Uitvoering**: de 1-3 woorden direct na de familie in de titel die op een
  uitvoering lijken: `sl`, `slr`, `sl6`, `al`, `alr`, `al2`, `cf`, `cfr`,
  `slx`, `advanced`, `pro`, `comp`, `sport`, `elite`, `expert`, `disc`,
  `team`, `ltd`, een getal (`2`, `6`, `105` niet — dat is een groepset), of
  letters+cijfer (`sl7`, `r5`). Stop bij het eerste andere woord
  (racefiets, maat, carbon, met, shimano, …; gebruik `NOT_A_MODEL_AFTER_BRAND`
  en de groepsetnamen). Voorbeelden die moeten kloppen:
  - "Giant Defy Advanced 2 maat M" → familie `defy`, uitvoering `advanced 2`
  - "Trek Domane SL6 Gen 4" → `domane`, `sl6`
  - "Trek Domane AL 2 2024" → `domane`, `al 2` (het jaartal is geen uitvoering)
  - "Canyon Aeroad CF SLX 8" → `aeroad`, `cf slx 8`
  - "Cube Attain racefiets" → `attain`, geen uitvoering
- **Sleutels**:
  - `exact` = de eigen koppeling (modelnaam) als die er is; anders het
    referentiemodel uit `reference_bikes.csv` als dat past; anders merk +
    familie + uitvoering (zonder spaties vergeleken: "sl 6" = "sl6"); zonder
    uitvoering = merk + familie.
  - `coarse` = merk + familie (bij een eigen koppeling: die van het model in
    `bike_model`).
  - Toon de modelnaam netjes: "Trek Domane SL6", "Giant Defy Advanced 2".
- **Eigen koppeling gaat altijd voor** de herkenning (`bike_link`). Een jaar
  in `bike_link.year` gaat voor het jaar uit de tekst, en moet ook doorwerken
  in het upgradeoordeel (zet het in de specs vóór `find_upgrades()`, zodat
  het leeftijdsverval meetelt; zonder bekend jaar is een upgrade nu nooit
  groen — zo laten).

### B. De vergelijkingstrap (vervangt `comparables()`)

Minimaal **5** vergelijkbare advertenties per trede; niet genoeg → een stap
grover. Lukt geen enkele trede met 5, loop de trap nog eens met 3 en zet er
"(weinig)" bij. Altijd zonder de fiets zelf.

1. `exact`, bouwjaar ±2 (beide bekend) — "model, ±2 jaar"
2. `exact`, waarvan één van beide geen jaar heeft, plus de ±2 — "model"
3. `coarse`, bouwjaar ±2 — "modelfamilie, ±2 jaar"
4. `coarse`, zelfde tijdperk (`same_era()`: rem bekend en gelijk,
   elektronisch gelijk, versnellingen gelijk als bekend) — "modelfamilie, zelfde tijdperk"
5. ander model, zelfde materiaal + groepsettier + rem, ±2 jaar — "zelfde opbouw, ±2 jaar"
6. alleen als van de fiets zelf jaar én rem onbekend zijn: `coarse`, elk jaar
   — "onzeker" (nooit groen; toon de spreiding min–max)

Daarna: geen schatting ("model niet herkend" / "te weinig vergelijkbare
fietsen"). Nooit een mediaan van alle racefietsen.

### C. Snel verkocht vs. vraagprijs

- Een advertentie in de pool is **snel verkocht** als hij verdween binnen
  **7 dagen** na `first_seen` (`disappeared_at - first_seen ≤ 7 dagen`, of
  `days_online ≤ 7`), of gereserveerd stond (`reserved_at`) en daarna
  verdween. Haal `days_online`, `reserved_at` en `first_seen` mee in
  `racebikes.SELECT` en zet een vlag in het `extra`-tuple van elk
  pool-item.
- Let op: verdwijnen wordt alleen vastgesteld na een **complete** crawl (de
  zondagronde `week` met `--split`, zie README → "Everything in a category").
  De eerste weken zijn er dus weinig snelle verkopen.
- Schatting binnen de gekozen trede:
  - **≥ 3 snel verkochte** → verwachte verkoopprijs = mediaan van hun
    laatste prijs (geen afdingfactor erover: het is al wat er ongeveer
    betaald is; zeg "laatste vraagprijs van snel verkochte" erbij, want de
    echte verkoopprijs ken je niet).
  - anders → mediaan van alle vraagprijzen × afdingfactor (0,875), met
    "(nog geen snelle verkopen)" erbij.
- Op de kaart, bijvoorbeeld: *"Trek Domane SL6 · 6 snel verkocht (≤7 d),
  mediaan €620 · 14 te koop, mediaan €690 — deze €480 (−23%)"*. Het
  percentage t.o.v. de schatting (snel verkocht als die er is). De lijst
  *vergeleken met N fietsen* (bestaat al) markeert welke snel verkocht zijn.

### D. Corrigeren op de kaart

Onder "gekoppeld aan …" op elke kaart:

- **klopt** → `bike_link` met `confirmed = 1` en `model_id` van het huidige
  model (maak het in `bike_model` aan als het een automatisch model is).
  Toon daarna "✓ gecontroleerd".
- **ander model** → klapt een kiezer open: een zoekveld en een
  **scrollbare lijst met alle modellen** (zie E), met per model hoeveel
  advertenties eraan hangen. Kies er een → koppelen. Staat hij er niet in →
  **"nieuw model"**: één veld "merk model uitvoering" (bv. "Koga Kinsei
  Pro"); splits merk/familie/uitvoering zoals in A en sla op in
  `bike_model`.
- **bouwjaar** → klein veld; opslaan zet `bike_link.year`.
- **ontkoppelen** → `set_bike_link(item_id)` zonder iets: terug naar de
  herkenning.

Server: nieuwe acties in `dashboard.py` (live, JSON, net als `/markeer`),
bijvoorbeeld `POST /racefietsen/model` met `item_id`, `model` (naam; nieuw
of bestaand), `year`, `confirm`, `clear`. Valideer: jaar 1970–volgend jaar,
modelnaam 3–80 tekens, minstens merk + één woord.

**Snelheid** (harde eis van de eigenaar: "de website moet snel blijven"):
een correctie mag niet de hele berekening opnieuw laten lopen (met ~14.000
fietsen is `build_base()` ~10 s). Werk de gecachte `Base` incrementeel bij:
herken alleen deze fiets opnieuw, verplaats hem in de `Pool`-indexen
(voeg `Pool.replace(item_id, identity)` toe), reken alleen zijn eigen rij
opnieuw uit en stuur die terug. De andere fietsen van die modellen rekenen
pas bij de volgende ronde opnieuw (zeg dat in de melding:
"de vergelijking van de andere fietsen van dit model wordt na de volgende
ronde bijgewerkt"). `data_stamp()` hoeft `bike_link` niet te kennen; bij
een volledige herberekening leest `build_base()` de koppelingen gewoon uit
de database. Zorg dat twee gelijktijdige klikken elkaar niet raken (een
lock om het bijwerken van de cache).

### E. De lijst met alle fietsmodellen

- Breid de weergave **Modellen** uit tot de volledige lijst: alle modellen
  uit `bike_model` (ook zonder advertenties) plus alle automatische
  modellen die in de pool voorkomen, met per model: te koop, gekoppeld
  (180 dagen), snel verkocht, mediaan snel verkocht, mediaan vraagprijs,
  laagste. Zoekveld erboven, sorteerbaar, scrollbaar (alles in één lijst is
  prima tot een paar duizend rijen; teken in batches zoals de kaarten als
  het traag wordt).
- Bovenaan een veld **"nieuw model toevoegen"** (zelfde als in D).
- Klik op een model → de kaarten van dat model (bestaat al: `modelFilter`).
- De kiezer in D gebruikt dezelfde lijst (stuur hem één keer als JSON mee in
  de pagina, `<script type="application/json" id="models">`, net als
  `bikes`; voeg een nieuw model na aanmaken client-side toe).
- Eigen modellen herkenbaar ("eigen"), automatische en referentiemodellen
  ook.

## Stap 2

### F. Regels leren

- Als de eigenaar ≥ 3 advertenties waarvan de herkende `exact`-sleutel
  gelijk is (bv. automatisch "Trek Domane Al") aan hetzelfde eigen model
  koppelt (bv. "Trek Domane AL 2"), stel dan een regel voor: "advertenties
  die als *Trek Domane Al* herkend worden → *Trek Domane AL 2*?" met
  **toepassen** / **nee**.
- Pas na **toepassen** werkt de regel automatisch (nieuwe tabel, bv.
  migratie 20 `bike_rule (from_key, model_id, created_at)`; een tabel, geen
  kolom — zie CLAUDE.md). Een eigen koppeling per advertentie gaat nog
  steeds voor een regel. "nee" onthouden, zodat hij het niet opnieuw vraagt.
- Toon de voorstellen bovenaan de weergave Modellen.

### G. Bouwjaar ophalen voor kanshebbers

- Na de crawl in een ronde: voor fietsen zonder bekend jaar die op het eerste
  gezicht goedkoop lijken (prijs ≥ 15% onder de schatting van hun trede, of
  in de onzekere trede onder de mediaan), haal de advertentiepagina op en
  zoek het jaar in de volledige omschrijving. Er bestaat al
  `racefiets_jev.lookup_listing_details()` / `--detail-lookup` en
  `db.save_listing_details()`; hergebruik dat (het slaat
  `full_description` op, en `upgrade.listing_specs()` leest daar het jaar
  uit).
- **Maximaal 20 per ronde**, nooit een advertentie twee keer, met dezelfde
  wachttijd als de biedopvraging. Maak het aantal instelbaar per tijdslot in
  `schedule.json` (zoals `views_budget`), standaard 0, en zet het in de
  slots `overdag` en `nacht` op 20. Vraag de eigenaar of dat goed is voordat
  je het hoger zet.

## Harde randvoorwaarden

- **Beleefd tegen Marktplaats.** Op 30-09-2026 gaf Marktplaats een 403 na
  ~120 snelle verzoeken. Stap 1 doet geen enkel verzoek; stap 2 hooguit 20
  per ronde, nooit parallel.
- **Geen marktfeiten verzinnen**: geen generatiejaren, geen nieuwprijzen.
- **Tabellen, geen kolommen** bij een nieuwe migratie (tests rollen terug met
  DROP TABLE; voeg nieuwe tabellen toe aan een tuple zoals `db.MODEL_TABLES`
  en aan de twee rollback-tests in `tests/test_marks.py` en
  `tests/test_bike_comps.py`).
- **JSON in de pagina**: geen NaN/Infinity (`racebikes.page_json()` vangt
  het al af; gebruik die).
- **Niet de rapporten breken**: `racefiets_report.html`, `/fiets` en de
  taxatie gebruiken hun eigen vergelijking; laat die met rust.
- Nederlandse teksten op de pagina, Engelse namen in de code, commentaar
  legt uit *waarom*.

## Tests (minimaal)

- uitvoering: de vijf voorbeelden uit A.
- trap: een fiets met 5 van hetzelfde exacte model ±2 jaar en 5 van een
  ander jaar → alleen de eerste 5; met 3 exacte en 6 van de familie → trede
  "modelfamilie".
- snel verkocht: 3 verdwenen binnen 7 dagen + 5 nog te koop → schatting =
  mediaan van de 3; met 2 snelle → vraagprijzen × 0,875.
- eigen koppeling: koppelen aan een nieuw model maakt `bike_model` aan, de
  fiets hangt daarna aan dat model, het jaar uit `bike_link` gaat voor de
  tekst; ontkoppelen zet hem terug.
- server (zoals `LiveTest`): `POST /racefietsen/model` geeft JSON met de
  bijgewerkte fiets, zonder dat `build_base()` opnieuw draait (tel de
  aanroepen met een mock).
- modellenlijst: een eigen model zonder advertenties staat in de JSON.

## Klaar als

- de tests groen zijn (nu 932) en de nieuwe erbij;
- `/racefietsen` in een browser (Chromium/Playwright staat in de sandbox:
  `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, node-module
  `/opt/node22/lib/node_modules/playwright`) zonder JavaScript-fouten laadt
  op een testdatabase met ~2000 fietsen, een correctie < 300 ms duurt, en de
  modellenlijst scrolt en zoekt;
- README (sectie "Racefietsen — /racefietsen"), `CLAUDE.md` (bestandentabel,
  aantal tests) en `NEXT_STEPS.md` zijn bijgewerkt;
- gecommit op een branch van een verse `main`, gemerged naar `main` en
  gepusht, en je zegt de eigenaar welk commando hij draait (`git pull`,
  `python dashboard.py --serve`).
