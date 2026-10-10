# Mijn fiets — masterdocument

Alles wat bekend is over de eigen fiets op één plek, om op terug te vallen bij
vragen als "past er een 46T voorblad op?" of "past deze frametas?". Geef dit
bestand aan Claude (of open het zelf) voordat je zo'n vraag stelt.

**Spelregels voor dit document**

- Elke regel heeft een **status**:
  - ✅ **eigenaar** — vastgesteld door de eigenaar zelf (gezien, gemeten, gekocht).
  - 📖 **bron** — opgezocht, met link. Vaak over het *model*, niet over déze
    fiets; onderdelen kunnen sindsdien vervangen zijn.
  - ❓ **onbekend** — nog niet nagekeken. Niet invullen met een gok: meet het
    of zoek het op (zie §8, de meetlijst).
- Verzin geen specs. Een verkeerd getal hier geeft later een verkeerd
  antwoord op een koopvraag.
- `mijn_fiets.md` blijft het intakebestand voor de taxatie (`valuation.py`
  leest het scoringsblok daar). Dit document is breder: onderdelen, maten,
  standaarden, onderhoud en antwoorden op eerdere vragen. Verandert er iets
  aan de fiets dat de taxatie raakt (wielen, groep, schade), werk dan **beide**
  bij.

Laatst bijgewerkt: 10-10-2026.

---

## 1. Identiteit

| Veld | Waarde | Status |
| --- | --- | --- |
| Merk / model | Giant Defy **Composite**, modeljaar 2012 | ✅ eigenaar |
| Uitvoering | Composite 1 of 2 (of 3) — niet vastgesteld | ❓ |
| Frame | Carbon ("Giant Composite Technology", de instap-carbon onder Advanced) | ✅ materiaal / 📖 [1] |
| Framemaat | "56" volgens de eigenaar. Giant gebruikte letters (S/M/ML/L/XL); welke letter dit is, is niet vastgesteld | ✅ / ❓ letter |
| Framenummer | Onder de trapas; niet te koppelen aan modeljaar/uitvoering | ✅ eigenaar |
| Kilometerstand | < 10.000 km | ✅ eigenaar |
| Kleur | | ❓ |
| Gewicht (zoals hij nu is) | | ❓ — weeg hem eens (bagageweegschaal) |

## 2. Onderdelen — wat er nú op zit

Fabrieksspecs van het model staan in §3; die kunnen afwijken van wat er nu op
zit.

| Zone | Onderdeel | Status |
| --- | --- | --- |
| **Groep** | Shimano Ultegra **6700**, mechanisch, **2×10** | ✅ eigenaar |
| Shifters | Ultegra ST-6700 (aangenomen: hoort bij de groep) | ❓ typenummer nakijken |
| Voorderailleur | Ultegra FD-6700 — braze-on of klem? | ❓ |
| Achterderailleur | Ultegra RD-6700 — korte (SS) of middellange (GS) kooi? | ❓ |
| Crankset | Ultegra FC-6750 (compact, 50/34) of FC-6700 (standaard, 53/39)? Cranklengte? | ❓ — **belangrijk voor voorbladvragen**, zie §5 |
| Cassette | 10-speed, vervangen ca. 1500 km geleden. Tandjes (bv. 11-28)? Merk? | ✅ vervangen / ❓ maat |
| Ketting | 10-speed, vervangen ca. 1500 km geleden | ✅ eigenaar / ❓ merk |
| Trapas | Press-fit volgens de modelspecs (BB86) | 📖 [1][2] — ❓ zelf bevestigen |
| Remmen | Velremmen (dual-pivot), welk type? | ✅ velrem / ❓ type |
| **Wielen (gemonteerd)** | **CSC** carbon clincher, 50 mm hoog, 25 mm buiten / 18 mm binnen, naven AS511SB (voor) / FS522SB (achter), velrem. AliExpress, ca. €300 nieuw | ✅ eigenaar |
| Wielen (origineel) | Nog in bezit (welke? waarschijnlijk Giant P-SL1, zie §3) | ✅ in bezit / ❓ type |
| Asstandaard | Snelspanner, 100 mm voor / 130 mm achter (standaard voor een velrem-racefiets uit 2012) | ❓ zelf bevestigen |
| Freehub achter | Shimano HG (past 10- en 11-speed? hangt van de naaf af) | ❓ |
| Banden | Pirelli P Zero Race — breedte? | ✅ merk / ❓ maat, leeftijd |
| Binnenbanden / tubeless | Binnenbanden (clinchervelg) | ✅ clincher |
| Stuur | breedte? | ❓ |
| Stuurpen | lengte, hoek? | ❓ |
| Zadelpen | Giant Vector Composite — **framespecifiek** (aero-vorm, geen ronde 27,2/31,6) | 📖 [2] — ❓ zelf bevestigen |
| Zadel | | ❓ |
| Pedalen | | ❓ |
| Bidonhouders | aantal bevestigingspunten (onderbuis/zitbuis)? | ❓ |
| Fietscomputer | Wahoo Elemnt Roam (v1) — van de eigenaar, **gaat niet mee bij verkoop** | ✅ eigenaar |

## 3. Fabrieksspecificaties van het model (ter referentie)

Er is geen Nederlandse spec-pagina van 2012 gevonden. Wat er wel is:

**Defy Composite 1, 2012, Amerikaanse uitvoering, maat Medium** [2]:
frame carbon, voorvork Advanced-Grade Composite; shifters Ultegra ST-6700;
voor- en achterderailleur Ultegra FD-6700 / RD-6700; crankset **Ultegra
FC-6700, 50/34, 172,5 mm**; cassette SRAM PG-1030 **11-32**; ketting Shimano
CN-4601; remmen **Shimano 105 BR-5700**; stuur Giant Connect SL 42 cm; stuurpen
Giant Connect SL 31,8 × 100 mm, 8°; zadelpen **Giant Vector Composite,
framespecifiek**; wielen Giant P-SL1; banden 700×28 voor / 700×30 achter;
balhoofd geïntegreerd; gewicht 18 lbs 15 oz (≈ 8,6 kg).
Geometrie (Medium): effectieve bovenbuis **545 mm**, zitbuis 500 mm,
zitbuishoek 73,5°, balhoofdhoek 72,5°, balhoofdbuis 165 mm, standover 777 mm.

**Defy Composite 1, 2013, Nederlandse uitvoering** [1] (één jaar later, ter
vergelijking): Ultegra 10-speed, crankset Ultegra compact 50×34, cassette
Shimano 105 11-28, ketting KMC X10L, remmen Ultegra, zadelpen Giant Defy
Vector Composite, wielen Giant P-SL1, banden 700×23c, trapas "Shimano
Integrated", 8,0 kg, adviesprijs €2.299.

**Nieuwprijs 2012** (Spaanse markt, bikezona): Composite 1 €2.199, Composite 3
€1.499 [3]. Zie `reference_bike_catalog.csv`.

Let op: de US-uitvoering van 2012 en de NL-uitvoering van 2013 verschillen
(cassette 11-32 vs 11-28, remmen 105 vs Ultegra, banden). Neem dus niets
blind over voor déze fiets — kijk na wat er echt op zit (§8).

## 4. Maten en standaarden — de compatibiliteitstabel

Dit is het blok om te raadplegen bij "past X?". Vul het aan zodra iets gemeten
is.

| Standaard | Waarde | Status | Waarom het ertoe doet |
| --- | --- | --- | --- |
| Trapas | BB86 press-fit (Shimano) | 📖 [1][2] | Welke cranks passen (24 mm-as Hollowtech II zonder adapter) |
| Crank-BCD | 110 mm (compact) óf 130 mm (standaard) | ❓ | Bepaalt welke voorbladen passen |
| Voorbladen | 50/34 volgens de modelspecs | 📖 [2] / ❓ | |
| Voorderailleur-montage | braze-on of klem (en klemmaat) | ❓ | Hoe ver de derailleur omlaag kan bij een kleiner blad |
| Cassette | 10-speed, ?–? tanden | ❓ | Bereik, en of de achterderailleur het aankan |
| Achterderailleur | SS of GS | ❓ | Grootste krans: 28T volgens oudere Shimano-documentatie, mogelijk 30T [6] |
| Ketting | 10-speed | ✅ | |
| Remmen | velrem, dual-pivot | ✅ | Bereik (reach) bepaalt welke remmen passen |
| Wielmaat | 700c (622) | ✅ | |
| Asstandaard | QR 100 / 130 | ❓ | |
| Max. bandbreedte frame/vork | | ❓ — meet de ruimte in vork en achtervork | 28 mm? Hangt ook af van de remklauw |
| Velg binnenbreedte (CSC) | 18 mm | ✅ eigenaar | 25 mm banden passen goed; 28+ wordt ballonnerig |
| Zadelpen | framespecifiek (Vector Composite) | 📖 [2] | Geen gewone ronde pen; vervanging alleen deze vorm |
| Balhoofd | geïntegreerd; maat lagers ❓ (1⅛" of 1⅛–1¼" taps?) | 📖 [2] / ❓ | Andere vork / stuurpen |
| Stuurklem | 31,8 mm | 📖 [2] (stuurpen) / ❓ | Stuur, opzetstuur, houders |
| Balhoofdbuis | 165 mm (Medium; de eigen maat ❓) | 📖 [2] | |
| Effectieve bovenbuis | 545 mm bij Medium; de eigen maat ❓ | 📖 [2] | Ruwe indicatie frametas |
| Binnenmaten driehoek | | ❓ — **meten**, zie §8 | Frametas |
| Bidonbevestigingen | | ❓ | Frametas vs. bidons |

## 5. Snelle antwoorden op compatibiliteitsvragen

Uitgewerkte antwoorden, met wat er nog onzeker is. Nieuwe vraag beantwoord?
Zet hem erbij.

### Kan er een 46T voorblad op? (10-10-2026)

**Waarschijnlijk wel, met kanttekeningen — eerst de crank nakijken.**

1. **Welke crank?** Staat er "FC-6750" op de binnenkant van de crankarm (of
   zijn het 50/34-bladen), dan is het een compact met **110 mm BCD** [4].
   Daar passen 46T-bladen van andere merken (5-gaats, 110 BCD) gewoon op, met
   34 of 36 binnen. Is het een FC-6700 met 53/39, dan is het **130 mm BCD**
   en kan er binnen niet kleiner dan 38/39 — 46/36 lukt dan niet zonder andere
   crank. (De US-spec noemt "FC-6700, 50/34" [2]; 50/34 is in de praktijk de
   compact-uitvoering — kijk het na.)
2. **De voorderailleur.** FD-6700 heeft een capaciteit van 16 tanden en is
   bedoeld voor een groot blad van **50 tot 56 tanden** volgens de
   verkopersspecs [5]. 46/34 (12T verschil) valt binnen de capaciteit, maar
   46T ligt **onder** het opgegeven bereik: de kooi staat dan te hoog boven
   het blad en het schakelen wordt minder strak. Bij een braze-on derailleur
   kun je hem meestal een paar mm verder omlaag zetten; of dat genoeg is voor
   4 tanden (≈ 8 mm lager) hangt van het frame af. Shimano zelf heeft deze
   combinatie niet gedocumenteerd — dit is het onzekere stuk.
3. **Wat het oplevert.** 46/34 ipv 50/34: de kleinste versnelling blijft
   gelijk, de grootste wordt ~8 % lichter, en je schakelt minder vaak tussen
   de bladen. Het binnenblad bepaalt de klimversnelling, niet het buitenblad.
4. **Shimano-bladen.** De originele FC-6750-bladen zijn een specifiek
   paar (50-34) [4]; een 46T van Shimano voor deze crank bestaat voor zover
   gevonden niet. Het wordt een blad van een ander merk.

Te controleren: crank-type (§8), derailleur braze-on of klem.

### Past deze frametas?

Nog niet te beantwoorden: daarvoor zijn de **binnenmaten van de driehoek**
nodig, en die staan nergens online voor deze fiets (de geometrietabel geeft
buislengtes hart-op-hart, niet de vrije ruimte). Meet ze één keer (§8) en zet
ze in §4; daarna is elke frametas een kwestie van maten vergelijken:

- vrije lengte langs de bovenbuis (van balhoofd tot zitbuis, binnenkant),
- vrije hoogte bij de voorkant (balhoofd → onderbuis) en bij de zitbuis,
- waar de bidonhouders zitten en of je een bidon nog kunt pakken,
- of er kabels over de bovenbuis lopen (velcro om kabels heen gaat meestal).

Een volle-driehoektas bij een compact/sloping frame als de Defy is krap;
een "half-frame" tas of toptube-tasje is meestal de veilige keus.

## 6. Onderhoudslogboek

| Datum | km-stand | Wat | Kosten | Bron |
| --- | --- | --- | --- | --- |
| ≈ (ca. 1500 km vóór 22-09-2026) | ≈ 8.500 | Cassette + ketting vervangen | | ✅ eigenaar |
| | | CSC-wielset gemonteerd (AliExpress, ca. €300) | ~€300 | ✅ eigenaar |

Nog niet bekend: laatste keer remblokken (carbon-specifieke blokken voor de
CSC-velgen!), kabels/buitenkabels, stuurlint, trapas, balhoofdlagers, banden.

## 7. Bezit en accessoires

| Wat | Gaat mee bij verkoop? | Status |
| --- | --- | --- |
| Originele wielen | ja (scenario B: los of erop) | ✅ eigenaar |
| CSC carbon wielset | afhankelijk van de volgende fiets (velrem: meenemen) | ✅ eigenaar |
| Wahoo Elemnt Roam v1 + houder | nee | ✅ eigenaar |
| Pedalen, bidonhouders, verlichting, slot, pomp, tassen | | ❓ |

Waarde en verkoopscenario's: zie `taxatie_2026-09-22.md` en `mijn_fiets.md`.

## 8. Meetlijst — wat de eigenaar nog moet nakijken

Eén keer 15 minuten met een rolmaat en een zaklamp beantwoordt de meeste
toekomstige vragen. In volgorde van nut:

1. **Crank**: typenummer op de binnenkant van de crankarm (FC-6750 / FC-6700),
   tandjes op de bladen (gestempeld), cranklengte (gestempeld, bv. 172.5).
2. **Cassette**: tandjes grootste en kleinste krans (gestempeld op de krans).
3. **Achterderailleur**: SS of GS (sticker/stempel op de kooi; GS heeft een
   duidelijk langere kooi).
4. **Voorderailleur**: braze-on (vastgeschroefd op een plaatje op de zitbuis)
   of klem (band om de zitbuis); en hoeveel ruimte er onder nog is in het
   gleufje.
5. **Driehoek binnenmaten** (voor frametassen): vrije lengte bovenbuis, vrije
   hoogte voor en achter, positie bidonbouten.
6. **Bandenruimte**: breedte van de huidige band (op de zijkant) en hoeveel mm
   er nog vrij is tot frame/vork/rem, aan elke kant.
7. **Framemaat-letter**: sticker op de zitbuis of onder de trapas (S/M/ML/L).
8. **Stuur en stuurpen**: breedte stuur (hart-hart aan de uiteinden), lengte
   stuurpen (gestempeld).
9. **Remmen**: typenummer op de remklauw (BR-6700 / BR-5700 / anders).
10. **Asstandaard**: snelspanner (vrijwel zeker), ter bevestiging.
11. **Gewicht** van de complete fiets met de CSC-wielen.
12. **Foto's**: van elk onderdeel met het typenummer, plus het framenummer.
    Handig voor verkoop en voor vragen.

## 9. Bronnen

1. Giant Nederland, Defy Composite 1 (2013), adviesprijs en specs — archief
   10-02-2013:
   <https://web.archive.org/web/20130210063948/http://www.giant-bicycles.com:80/nl-nl/bikes/model/defy.composite.1/12254/58110/>
   (ook in `reference_bike_catalog.csv`)
2. The Pro's Closet, 2012 Giant Defy Composite 1, Medium (US-uitvoering, specs
   en geometrie), opgehaald 10-10-2026:
   <https://www.theproscloset.com/products/2391309221970-giant-defy-composite-1-medium-bike-2012>
3. bikezona.com (Spaanse markt), catalogusprijzen 2012:
   <https://www.bikezona.com/bicicletas/giant-defy-composite-1/11009>,
   <https://www.bikezona.com/bicicletas/giant-defy-composite-3/11164>
4. SJS Cycles, Ultegra FC-6750 buitenblad 50T, 110 mm BCD — "alleen voor
   FC-6750 10-speed met 50-34":
   <https://www.sjscycles.co.uk/chainrings/shimano-ultegra-fc6750-110mm-bcd-5-arm-outer-chainring-f-type-silver-50t/>
5. FD-6700: capaciteit 16T, groot blad 50-56T (Sigma Sports); geschikt voor
   compact (110) en standaard (130) dubbel (Competitive Cyclist). Verkopers,
   niet de Shimano-handleiding:
   <https://www.sigmasports.com/item/Shimano/Ultegra-6700-Band-on-Front-Derailleur/7UV>,
   <https://www.competitivecyclist.com/shimano-ultegra-fd-6700-front-derailleur>
6. RD-6700 grootste krans: 28T volgens oudere Shimano-serviceinstructies
   (geciteerd op een forum), mogelijk later 30T — niet officieel bevestigd:
   <https://www.roadbikereview.com/threads/confused-trying-to-work-out-if-i-need-a-gs-or-ss-derailleur.262587/>,
   <https://forum.bikeradar.com/discussion/13028977/shimano-6700-rd>

Officiële Shimano-documentatie (si.shimano.com) en een Giant-geometrietabel
van 2012 zijn nog niet gevonden; de Wayback Machine was vanuit deze sessie niet
bereikbaar. Die twee zouden §4 en §5 hard maken.
