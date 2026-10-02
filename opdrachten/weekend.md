# Weekendwerk: vrijdag 02-10 tot zaterdag 03-10-2026 13:00

De eigenaar is weg en kan niets beantwoorden. Hij koos op 02-10-2026 (03:30)
wat er mag gebeuren; dit bestand is de werklijst. Een routine stuurt elk uur
"ga door" naar dezelfde sessie; dit bestand zegt waar je bent.

## Zijn keuzes (02-10-2026)

| Vraag | Antwoord |
| --- | --- |
| Welke blokken? | Alle vier, in deze volgorde: fietsmodellen stap 2, goedkoopste onderdelen (A en B), controle en opruimen, telefoon. |
| Waarheen pushen? | **Alleen** naar `claude/claude-fietsmodellen-stap-1-80kp1n`. Niet naar `main`; de eigenaar merget zaterdag zelf. |
| Stap 1: referentiemodel | Zo laten: een vangnet-referentiemodel ("Trek Domane") wijkt voor model + uitvoering uit de titel. |
| Lijst eerder af? | Zelf kleine verbeteringen (bugs, snelheid, tests, documentatie), zonder nieuwe verzoeken naar Marktplaats en zonder nieuwe functies die zijn keuze vragen; ideeën als voorstel in `NEXT_STEPS.md`. |
| Onderdelen deel B | Het voorstel uit `opdrachten/goedkoopste_onderdelen.md` (tabel `flip_offer`, klapblok Aanbiedingen, "kies deze") mag zo gebouwd worden. Migratie 18 en 19 zijn inmiddels bezet: het wordt de eerstvolgende vrije. |
| Later op 02-10: "elke pagina minimaal dezelfde functies" | **Zelfde knoppen en weergaven** op `/racefietsen`, fietscomputers (`/`) en horloges (`/horloges`): Te beoordelen / Favorieten / Mijn biedingen / Mijn flips / Alle / Weggezet / Patronen, favoriet/weg/notitie/bod/controleer, afstand, filters — wat ergens ontbreekt komt erbij. Plus **snel verkocht overal**: ook bij computers en horloges vergelijken met wat binnen 7 dagen wegging. Niet gekozen (dus niet doen): sneltoetsen en Modellen/corrigeren bij computers en horloges. |
| Later op 02-10: knop voor onderdelen als reserve | Een **reservelijst op `/racefietsen`**: een weergave Onderdelen met "hier wil ik reserves van" (cassette, ketting, zadel, pedalen, banden, ...), aan/uit per soort, en per soort de goedkoopste advertenties met prijs, afstand en favoriet/weg/bod. **Alleen wat al binnenkomt**: geen nieuwe zoekopdrachten (dus weinig treffers; zeg in README hoe hij er later een toevoegt). Niet per flip op /flips en geen donorfiets-knop. |

## Regels die er bovenop gelden

- `CLAUDE.md` blijft gelden: tests groen (nooit een test weghalen of
  uitzetten), README en CLAUDE.md bijwerken in dezelfde commit, Nederlandse
  teksten, geen nieuwe dependencies, tabellen en geen kolommen bij een
  migratie.
- **Geen enkel verzoek naar Marktplaats vanuit de sandbox.** Code die
  verzoeken doet (stap 2 G) test je met `FakeSession`, niet tegen de site.
- Niet bieden, niet reageren, geen marktfeiten verzinnen. Prijzen bij de
  onderdelen alleen met directe URL en datum; AliExpress alleen als schatting.
- Na elk punt: tests groen, punt afvinken hieronder met een regel wat er is
  gedaan en wat bleef liggen, commit, **push naar de branch**. Een container
  kan verdwijnen; wat niet gepusht is, is weg.
- Een punt dat halverwege blijft steken: commit wat werkt (tests groen),
  noteer hieronder waar je bent, en ga verder bij de volgende ronde.
- Na zaterdag 03-10-2026 13:00 (Europe/Amsterdam) niets nieuws beginnen.

## Werklijst

- [x] **1. Fietsmodellen stap 2 F — regels leren** (`opdrachten/fietsmodellen.md` → F)
- [x] **2. Fietsmodellen stap 2 G — bouwjaar ophalen voor kanshebbers** (→ G; `schedule.json`: 20 in `overdag` en `nacht`, standaard 0)
- [x] **3. Onderdelen B — link plakken met prijs op /flips** (`opdrachten/goedkoopste_onderdelen.md` → B)
- [x] **4. Onderdelen A — prijsonderzoek Cube Peloton Pro** (→ A; resultaat als rapport in `opdrachten/` en, nu B er is, als aanbiedingen in een importbestand dat de eigenaar zelf inleest — niet in zijn database schrijven)
- [x] **4b. Reservelijst onderdelen op /racefietsen** (keuzes hierboven)
- [x] **4c. Zelfde knoppen en weergaven** op racefietsen, fietscomputers, horloges (keuzes hierboven)
- [x] **4d. Snel verkocht** ook bij fietscomputers en horloges
- [x] **5. Controle en opruimen** — review van de grote wijzigingen van 29-09 t/m 03-10 (racebikes, bike_identity, flips, dashboard), bugs fixen met een test erbij; README/CLAUDE.md nalopen op wat niet meer klopt
- [x] **6. Telefoon** — `/racefietsen` en `/flips` op 390 px breed: geen horizontaal scrollen, balk bovenaan inklapbaar, knoppen groot genoeg; nagemeten met Playwright
- [ ] **7. Daarna** — kleine verbeteringen (zie keuzes), elk als eigen commit

## Logboek

(per punt: datum, commit, wat er is gedaan, wat bleef liggen)

- **02-10, 615f347 — punt 1 (F) af.** Migratie 20 `bike_rule`; voorstel na 3
  dezelfde correcties bovenaan Modellen (en op de knop: "Modellen (1
  voorstel)"), toepassen / nee (onthouden) / weghalen; `bike_identity`
  gesplitst in `recognize()` + `resolve()` zodat een regel ook verdwenen
  fietsen in de pool raakt zonder ze opnieuw te lezen. In Chromium op 2000
  testfietsen: regel toepassen 76 ms (35 fietsen). Onderweg: een test in
  `test_dashboard.py` verkocht op de vaste datum 01-10-2026 en faalde sinds
  02-10 (aparte commit, de test verkoopt nu op de aankoopdag).
- **02-10, 0bd5b20 — punt 2 (G) af.** `python racebikes.py jaar N` (en `plan
  N`): actieve racefietsen zonder bouwjaar, met prijs, niet gereserveerd of
  weggezet, nooit eerder opgehaald, ≥ 15% onder de schatting (of in de
  onzekere trede onder de mediaan); goedkoopste eerst, hooguit 20,
  `recheck._get()` (1,5 s ertussen), stopt bij 403 / gewijzigde pagina / 3
  mislukte. Bewaart de volledige omschrijving (`db.save_listing_details()`)
  en lift weergaven/likes mee. `koopjes.py`: `year_budget` per tijdslot
  (0-20, standaard 0), in `schedule.json` 20 bij `overdag` en `nacht`.
  Niet tegen Marktplaats getest (geen verzoeken vanuit de sandbox); de
  eigenaar ziet het eerste resultaat in `logs/koopjes.log` ("Bouwjaren
  opzoeken: …").
- **02-10, ef1dfc8 — punt 3 (onderdelen B) af.** Migratie 21 `flip_offer` (met
  `source`: gecontroleerd/schatting); per onderdeel "Aanbiedingen (n)" op
  /flips: link plakken + prijs + verzending + winkel + notitie, goedkoopste
  eerst, "kies deze" (zet winkel, link, geschat = prijs + verzending, bron),
  weg; winkel en link van de regel zelf aan te passen. `flips.clean_url()`
  haalt volgcodes weg en maakt van een lange AliExpress-link
  `/item/<nr>.html`. `python flips.py bijwerken` leest ook "aanbiedingen"
  in (voor punt 4). Sheet: alleen-lezen tabblad Aanbiedingen; de eigenaar
  moet `flips_sheets.gs` één keer opnieuw plakken (SHEETS.md). In Chromium
  op 1300 en 390 px: geen JS-fouten, geen horizontaal scrollen.
- **02-10, 44b2f79 — tussendoor: fout van de eigenaar opgelost.** "database is
  locked" bij wegzetten op /racefietsen (traceback in zijn terminal). WAL-modus
  + 30 s wachten in `db.connect()`, `racebikes.find_listing()` leest één fiets
  in plaats van alle, en een nette melding (`dashboard.DB_BUSY`) als het toch
  bezet is. De eigenaar is gezegd hoe hij het nu al in main
  krijgt.
- **02-10, 8181bfa — punt 4 (onderdelen A) af.** `flips_import/cube_prijsonderzoek.md`
  + `cube_aanbiedingen.json` (21 aanbiedingen, in te lezen met `flips.py
  bijwerken`). Belangrijkste: (1) 11-32 cassette alleen op een RD-5701-**GS**
  (Shimano: SS 25-30T), anders 12-28; (2) origineel 105 FC-5750 50T-blad
  overal uitverkocht, SRAM 50T/110 €31,95 als het oude echt op is; (3) KMC
  X10 in NL ±€20, bike-components €16 — AliExpress (±€13) geen voordeel meer
  met **€3 invoerrecht per productcategorie sinds 1-7-2026** (EC + Douane);
  (4) goedkoopste mandje bike-components ±€101,50 voor cassette, wieltjes,
  banden, remrubbers, ketting, binnenbanden. Bike24 en Decathlon weigeren
  geautomatiseerde verzoeken (403): hun prijzen komen uit de lijst van de
  eigenaar. Niet nagezocht: Action/bouwmarkt-spullen, AliExpress-retour,
  Marktplaats (geen verzoeken).
- **02-10, 120cd4e — punt 4b (reservelijst) af.** `spares.py` + weergave
  Onderdelen op /racefietsen: 16 soorten herkend op de titel, aan/uit per
  soort (bewaard in `setting`, eerst cassettes/kettingen/zadels/pedalen),
  per soort de 40 goedkoopste met foto, prijs, plaats, afstand, favoriet,
  weg en bod (dezelfde acties; `/markeer` vindt nu ook een onderdeel buiten
  de racefietsen). Geen nieuwe zoekopdracht (keuze eigenaar): er zijn er
  weinig; README zegt hoe er een bij kan. In Chromium op 1300 en 390 px
  zonder JS-fouten.
- **02-10, 23797d3 — punt 4c (zelfde knoppen en weergaven) af.** Fietscomputers
  en horloges kregen **Te beoordelen** en **Weggezet** (tabknoppen die Alle
  openen met Toon op dat filter: geen tweede tabel van duizenden rijen; ook
  via `#beoordelen`/`#weggezet` en live bijgewerkt na favoriet/weg), Toon
  "te beoordelen" en een filter **Max €** in Alle. `/racefietsen` kreeg
  **Mijn flips** (de fietsen van /flips: fase, gekocht, erin, doel, winst;
  bewerken op /flips). Wat er al overal was: Favorieten, Mijn biedingen,
  Alle, Patronen, favoriet/weg/notitie/bod/controleer, afstand. Niet gedaan
  (keuze eigenaar): sneltoetsen en Modellen bij computers/horloges. In
  Chromium op 1300 en 390 px zonder JS-fouten of horizontaal scrollen.
- **02-10, 654b754 — punt 4d (snel verkocht bij computers en horloges) af.**
  `computers.comparable_rows()` geeft nu per vergelijkingsprijs of hij snel
  verkocht is (`is_fast_sold()`: ≤ 7 dagen weg, of gereserveerd en weg —
  dezelfde regel als `racebikes.sold_fast()`). Vanaf 3 snel verkochte (binnen
  de uitvoering of het model waarmee vergeleken wordt) is de verkoopschatting
  hun mediaan zonder × 0,875, de band hun kwartielen; anders zoals het was,
  met "nog maar N snel verkocht" in de onderbouwing. Ook in
  `market_resale()` (voorraad in Mijn flips, Marktprijzen, Vinted), en
  Marktprijzen kreeg een kolom Snel verkocht. Zolang de nachtrondes nog
  weinig verdwenen advertenties hebben, verandert er in de praktijk weinig.
- **02-10, 95d327f t/m f6566fb — punt 5 (controle en opruimen) af.** Gevonden en
  gerepareerd, elk met een test: (1) links die de eigenaar zelf invult (of
  via de Google Sheet) kwamen ongecontroleerd in een href — een
  `javascript:`-link werd code op een pagina met het token; nu alleen
  http(s) (`dashboard.web_link()`); (2) `/racefietsen/reserves` gaf bij een
  bezette database een traceback; (3) een fout uit 4c: Alle zette Toon terug
  op de standaard ook na controleer, de eigen keuze ging verloren. Verder:
  CLAUDE.md miste vier bestanden, de uitleg boven Flips en onder `python
  watches.py` kende snel verkocht nog niet, NEXT_STEPS.md kreeg een blok over
  het weekend. Alle pagina's en tabs/weergaven in Chromium op 1300 en 390
  px: geen JS-fouten, geen 5xx, geen horizontaal scrollen; de commando's
  uit de README zonder netwerk draaien. Bleef liggen (voor punt 7):
  `bike_identity.reference_model()` is ~1/4 van `build_base()` (339
  patronen per advertentie).
- **02-10, 60215fc — punt 6 (telefoon) af.** Onder 700 px: de balk bovenaan
  elke live pagina klapt in tot één knop "☰ <pagina>" (een vinkje, geen
  JS); rijen tabknoppen (`/`, `/horloges`) en weergaven (`/racefietsen`)
  scrollen zijwaarts, de gekozen weergave schuift in beeld; knoppen en
  velden minstens 40 px hoog, vinkjes 20 px, klapblokken op /flips 40 px;
  op `/racefietsen` de filters achter **Filters ▾** naast het zoekvak en
  geen sneltoetsen. Gemeten in Chromium op 390 × 844 (touch): plakkende
  balk 477 → 107 px, geen horizontaal scrollen op /racefietsen, /flips, /,
  /start; op /flips geen knop meer onder 40 px; op /racefietsen alleen nog
  tekstlinks in lopende tekst. Desktop (1300 px) ongewijzigd.
- **02-10 — punt 7 (daarna), tussenstand.** Elk een eigen commit, met test:
  - Sneller (14.000 testadvertenties, uitvoer byte voor byte gelijk):
    opbouw `/racefietsen` 6,5 → 4,1 s (2c677df, 37914a7, d061da1,
    b649b18: beginwoorden van de referentiepatronen, `fold()` voor ASCII,
    de vergelijkingstrap zonder functieaanroepen); een paginaweergave
    0,95 → 0,5 s (77abb4d) en de pagina 19,2 → 7,9 MB, herladen 1,7 →
    0,6 s (628948b: de vergelijkingslijst komt bij openklappen).
  - Mijn flips werkt meteen bij na "geaccepteerd", op /racefietsen
    (131f3c6) en op de dashboards (0637076).
  - Fout: spatie opende de vergelijking in plaats van de beschrijving
    (6cc7626).
  - `u` in Te beoordelen maakt de laatste markering ongedaan (3d4e303).
  - Alle 992 tests ook groen op Python 3.14 (rc2; de eigenaar draait 3.14),
    ook met DeprecationWarning als fout.
  - Fuzzen (4.000 onzin-formulieren op elke POST, 20.000 rare titels, GET
    met pad-trucs): geen 5xx of traceback, geen pad buiten /bestanden; wel
    gevonden en gerepareerd: "1e309"/"nan" werden als bedrag opgeslagen
    (oneindige aankoopprijs) en "€ 12,50" als modelnaam (b22a813).
  - De server rekent vooruit na het starten en na elke ronde; eerste bezoek
    aan /racefietsen 4,5 → 0,3 s (2393e41).
  - Duidelijke meldingen in plaats van tracebacks: `flips.py import/bijwerken`
    met een verkeerd of ontbrekend bestand (5230c7e); `valuation.py` en
    `upgrade.py` maakten bij een tikfout in `--db` stil een lege database
    (4bc9aac).
  - Meer tests waar de dekkingsmeting gaten liet: bouwjaar opzoeken bij
    netwerk- en serverfouten (0db92eb); een open sqlite-verbinding in een
    test (5f9edf1); een ronde weergaven/likes meten (9dde511); de knoppen
    op een flipkaart en per regel door de server heen (d0a92d4, 6b6d275).
    Nu 1004 tests.
  - Generale repetitie van de merge: een database gemaakt met de code van
    `main` (versie 19, markering, weg, bod, flip met klus) en die geopend
    met deze branch: migratie 20 en 21 lopen, de database gaat naar WAL,
    alles staat er nog, en /start, /, /horloges, /racefietsen, /flips,
    /fiets en de tab Alle laden zonder fout.
- **02-10 — de eigenaar zag "database is locked" opnieuw.** Zijn regelnummers
  (dashboard.py 3962/3485, db.py 1427) zijn die van `main`: daar zit de fix
  (44b2f79, op de branch) nog niet in. Hem gezegd de branch nu al te mergen
  (main is niet verder gegaan, dus een fast-forward) of de branch uit te
  checken. Let op: na de branch heeft koopjes.db migratie 21, en de oude
  `main` weigert dan een nieuwere database ("werk de code bij").
- **02-10 — de eigenaar heeft gemerged.** `main` staat op 3da1e49 (gelijk
  aan de branch). Verder werk gaat weer op de branch; aan het eind opnieuw
  een fast-forward. Rookproef op die commit: alle pagina's en tabs in
  Chromium op 1300 en 390 px zonder fouten; alleen de browser vroeg om
  `/favicon.ico` en kreeg een 404 (nu 204).
- **02-10, 7618afb — eigen werk nagelopen.** `LiveCache.comps()` rekende
  nog onder het slot van de hele cache; met het vooruitrekenen op de
  achtergrond liet dat een verzoek naar een dashboard dat al klaarstond
  wachten (gemeten 0,6 s in een test, nu direct).
- **02-10 — reservelijst nagelopen** op 31 soorten titels: houders,
  schoenen en gereedschap direct achter een onderdeel tellen niet meer
  (zie de commit hierboven).
- **02-10 — koppelen, regel en ontkoppelen samen nagelopen.** Het gedrag
  klopte (een regel blijft gelden na ontkoppelen), de melding niet; die is
  aangepast, met een test.
