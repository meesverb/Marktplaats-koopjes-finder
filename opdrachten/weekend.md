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
- [ ] **4. Onderdelen A — prijsonderzoek Cube Peloton Pro** (→ A; resultaat als rapport in `opdrachten/` en, nu B er is, als aanbiedingen in een importbestand dat de eigenaar zelf inleest — niet in zijn database schrijven)
- [ ] **5. Controle en opruimen** — review van de grote wijzigingen van 29-09 t/m 03-10 (racebikes, bike_identity, flips, dashboard), bugs fixen met een test erbij; README/CLAUDE.md nalopen op wat niet meer klopt
- [ ] **6. Telefoon** — `/racefietsen` en `/flips` op 390 px breed: geen horizontaal scrollen, balk bovenaan inklapbaar, knoppen groot genoeg; nagemeten met Playwright
- [ ] **7. Daarna** — kleine verbeteringen (zie keuzes), elk als eigen commit

## Logboek

(per punt: datum/tijd, commit, wat er is gedaan, wat bleef liggen)

- **02-10 ~04:00 — punt 1 (F) af.** Migratie 20 `bike_rule`; voorstel na 3
  dezelfde correcties bovenaan Modellen (en op de knop: "Modellen (1
  voorstel)"), toepassen / nee (onthouden) / weghalen; `bike_identity`
  gesplitst in `recognize()` + `resolve()` zodat een regel ook verdwenen
  fietsen in de pool raakt zonder ze opnieuw te lezen. In Chromium op 2000
  testfietsen: regel toepassen 76 ms (35 fietsen). Onderweg: een test in
  `test_dashboard.py` verkocht op de vaste datum 01-10-2026 en faalde sinds
  02-10 (aparte commit, de test verkoopt nu op de aankoopdag).
- **02-10 ~04:45 — punt 2 (G) af.** `python racebikes.py jaar N` (en `plan
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
- **02-10 ~05:45 — punt 3 (onderdelen B) af.** Migratie 21 `flip_offer` (met
  `source`: gecontroleerd/schatting); per onderdeel "Aanbiedingen (n)" op
  /flips: link plakken + prijs + verzending + winkel + notitie, goedkoopste
  eerst, "kies deze" (zet winkel, link, geschat = prijs + verzending, bron),
  weg; winkel en link van de regel zelf aan te passen. `flips.clean_url()`
  haalt volgcodes weg en maakt van een lange AliExpress-link
  `/item/<nr>.html`. `python flips.py bijwerken` leest ook "aanbiedingen"
  in (voor punt 4). Sheet: alleen-lezen tabblad Aanbiedingen; de eigenaar
  moet `flips_sheets.gs` één keer opnieuw plakken (SHEETS.md). In Chromium
  op 1300 en 390 px: geen JS-fouten, geen horizontaal scrollen.
