# Fietscomputers — `dashboard.html` (`dashboard.py`, `computers.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
python koopjes.py run nacht        # met de zoekopdracht "fietscomputer": de hele categorie, alle pagina's
python koopjes.py run computers    # overdag: alleen de nieuwste 2 pagina's; opent het dashboard bij een nieuwe flip
python dashboard.py --open         # dashboard.html opnieuw uit koopjes.db en openen
python dashboard.py --serve        # alles live vanaf http://127.0.0.1:8765/start (Ctrl+C stopt)
python computers.py                # functiescore per model, met het verschil met de jouwe
python computers.py --merk wahoo
```

Open de tab **Flips** voor wat onder zijn verwachte verkoopprijs staat, of
**Te beoordelen** om de lijst af te werken. Markeren, controleren en je eigen
aan- en verkopen vastleggen gaat in de live versie: zie [live.md](live.md).
De sporthorloges werken net zo: [horloges.md](horloges.md).

**`dashboard.html`** is de ene pagina voor fietscomputers: alles wat de
zoekopdracht `fietscomputer` vond, over alle merken en eerdere rondes, uit
`koopjes.db`. `koopjes.py` bouwt hem na elke ronde opnieuw; `python
dashboard.py` (of `python koopjes.py dashboard`) doet het met de hand.
**Actief** betekent: niet verdwenen en gezien binnen 3 dagen van de nieuwste
advertentie in de categorie (`dashboard` in `computer_scoring.json`).

## De tabs

| Tab | Wat |
| --- | --- |
| **Flips** | elke computer onder zijn verwachte verkoopprijs, grootste winst eerst; gereserveerde staan er niet in (wel in Alle computers, met "gereserveerd"), en wat je zelf wegzette ook niet tot de prijs zakt. Per advertentie: de winst, de band eromheen, wat hij kost en wat voor prijs dat is (vaste prijs / vraagprijs, bieden kan / huidig bod, loopt nog op), de verwachte verkoopprijs met n, en een foto. Daaronder: advertenties zonder prijs, met het **maximale bod** waarbij je bij de lage schatting nog quitte speelt |
| **Te beoordelen** | Alle computers met **Toon** op *te beoordelen*: geen markering, geen bod van jou, niet gekocht, niet gereserveerd — markeer er een en hij verdwijnt uit deze weergave, zoals op `/racefietsen`. Een tabknop, geen tweede tabel: hij opent Alle computers met dat filter |
| **Favorieten** | wat je ★ favoriet maakte, met je notitie en de prijs van toen als die veranderd is; daaronder favorieten die niet meer online zijn ("verdwenen" of "laatst gezien") |
| **Mijn biedingen** | de biedingen die je zelf op Marktplaats deed, lopende eerst (zie "Eigen biedingen" in [live.md](live.md)), met de advertentie, of "verdwenen" als hij weg is |
| **Mijn flips** | wat je zelf kocht en verkocht: gerealiseerde winst, wat er op voorraad is en wat dat nu zou moeten opbrengen, gemiddelde dagen tot verkoop, hoe ver de schatting van het dashboard ernaast zat, en winst per maand. Invoeren in de live versie |
| **Upgrades** | computers die meer kunnen dan de jouwe, met de punten die ze toevoegen, de **netto** kosten (prijs min wat je eigen computer opbrengt) en wat je wint of inlevert ("plannen op het apparaat: volledig i.p.v. beperkt", "touch i.p.v. knoppen") |
| **Alle computers** | alles, ook computers waarvan het model niet in het bestand staat ("model onbekend": Van Rysel GPS 500, Sigma BC 509, ...) — zoekveld (zoekt ook in je notities), merkfilter, "alleen nieuw", sorteerbare kolommen (ook Afstand), **Max €**. **Toon** verbergt standaard wat je wegzette; zet hem op *te beoordelen*, *favorieten*, *weggezet* (om er een terug te zetten), *met notitie* of *alles* |
| **Weggezet** | Alle computers met **Toon** op *weggezet*. Net als Te beoordelen een tabknop; de tab Alle computers zelf zet Toon terug op de standaard |
| **Marktprijzen** | per model: hoeveel te koop, laagste en mediane vraagprijs, hoeveel snel verkocht (met hun mediaan), verwachte verkoopprijs, nieuwprijs, score; per model ook de uitvoeringen die te koop staan met hun mediane vraagprijs |
| **Vinted** | zodra je een Vinted-export inlas (zie onder; tot dan zegt de tab hoe, en welke database hij leest): Vinted-advertenties die je met winst op Marktplaats zou kunnen verkopen, en per model de Vinted-vraagprijzen naast die van Marktplaats |
| **Patronen** | lange-termijnpatronen uit alles wat de crawl ooit zag, verdwenen meegerekend (`patterns.py`): per model hoe lang advertenties online blijven, hoeveel binnen 14 dagen weg zijn, de mediane vraagprijs, de laatste prijs van de snelle, en hoe vaak de prijs zakte; de **gemeten afdingfactor** (laatste prijs van wat binnen 14 dagen weg was ÷ de mediane vraagprijs van het model, getoond vanaf 20 zulke advertenties — dan kun je hem in `computer_scoring.json` zetten in plaats van de aangenomen 0,875); of wat bij de eerste blik een flip was sneller wegging dan de rest; de mediane vraagprijs per maand; en nieuwe advertenties per weekdag. Daaronder **Weergaven en likes** (zie [live.md](live.md)) |
| **Uitgefilterd** | houders, hoesjes, onderdelen, kapotte en gezocht-advertenties, elk met de reden, om te controleren dat er geen echte computer tussen zit |

Over Patronen: verdwenen is niet verkocht (een advertentie kan ingetrokken
zijn), en alleen een volledige nachtcrawl markeert iets als verdwenen, dus
dit heeft een paar weken `python koopjes.py run nacht` nodig. Verdwenen
advertenties die gereserveerd waren toen een ronde ze voor het laatst zag,
tellen apart ("eerst gereserveerd"): die zijn vrijwel zeker verkocht. Alleen
reserveringen die een ronde echt zag tellen, dus het is een ondergrens. Het
uur van plaatsen staat niet in de zoekresultaten: Marktplaats zegt alleen
"Vandaag"/"Gisteren".

Foto's komen uit de zoekresultaten (bewaard sinds migratie 6); een
advertentie van daarvoor toont een grijs vlak tot de volgende ronde hem ziet.

## Hoe de winst berekend wordt

**Winst** = verwachte verkoopprijs − prijs − `costs_eur` (€3 verzending,
keuze van de eigenaar, 28-09-2026; verhoog hem als je ook brandstof of
verpakking wilt meetellen). De kosten gaan ook van het maximale bod af.

- **De verkoopprijs** is de mediaan van wat andere advertenties voor
  hetzelfde model vragen (deze en eerdere rondes, laatste 180 dagen, verkochte
  meegerekend), × 0,875 voor afdingen (dezelfde vuistregel als
  `valuation.py`); de band gebruikt het onderste en bovenste kwartiel. Alleen
  met minstens 3 andere advertenties; een lopend bod is nooit
  vergelijkingsmateriaal.
- **Snel verkocht eerst** (sinds 02-10-2026, zoals op `/racefietsen`): zijn
  minstens 3 daarvan **snel verkocht** — verdwenen binnen 7 dagen na de eerste
  keer gezien, of gereserveerd en daarna verdwenen (`computers.is_fast_sold()`)
  — dan is de verkoopprijs de mediaan van *hun* laatste vraagprijs, zonder de
  0,875: ongeveer wat betaald is, al weet je nooit wat er echt betaald werd.
  De band zijn hun kwartielen. Met minder: de vraagprijzen × 0,875 zoals
  hierboven, en de regel onder de verkoopprijs zegt dat ("nog maar 2 snel
  verkocht"). Dezelfde regel geldt voor beide dashboards, voor de voorraad in
  Mijn flips, voor Marktprijzen (kolom **Snel verkocht**) en voor de
  Marktplaats-verkoopprijs op de tab Vinted. Het duurt een paar weken
  nachtrondes voor modellen er 3 hebben.
- **Per uitvoering eerst.** Uitvoeringen delen een rij in het
  referentiebestand ("Edge 530" is ook de sensorbundel, "Fenix 7" ook de 7S en
  de 7X Sapphire Solar), dus één mediaan zou ze mengen.
  `computers.title_variant()` leest de uitvoering uit de titel: een
  maatletter direct na het modelnummer (7S, 7X, 6S Pro, 265S), een kastmaat in
  mm (35-55 mm; "22mm" is een bandje), en de woorden Solar, Sapphire,
  Titanium, AMOLED (ook "OLED"), MicroLED, Music, LTE, bundle en de
  MARQ-edities (Athlete, Aviator, Captain, ...). Een flip wordt vergeleken met
  advertenties van dezelfde uitvoering als er minstens 3 zijn — een titel die
  er geen noemt is de gewone uitvoering, en een ontbrekende mm-maat past bij
  elke maat — en anders met het hele model. Het dashboard zegt welke, onder de
  verkoopprijs ("n=6, zelfde uitvoering: X · Solar · Sapphire" of "n=12, hele
  model; S: 1"; "4 snel verkocht" in plaats van n= als de snelle de prijs
  zetten). Op de volledige Garmin-horlogecrawl van 28-09-2026 hadden 778 van
  1229 horloges genoeg van hun eigen uitvoering: een gewone Fenix 7 op +€3 en
  een Fenix 8 AMOLED 47 mm op +€29 bleken geen flip, een Fenix 6 Sapphire
  Titanium ging van −€7 naar +€63. Mijn flips en de modelrijen in
  Marktprijzen rekenen nog met het hele model.
- **Gratis** (priceType FREE, €0) heeft geen prijs in plaats van een prijs van
  €0: nooit een flip of vergelijking, en het staat onder de maximale biedingen
  als "gratis of ruilen, prijs onbekend" — bij de sporthorloges was het een
  ruilaanbod dat de flips aanvoerde met +€559.
- **Twijfel bij een goedkope titel.** Een titel met een accessoirewoord
  direct na het model en alleen een apparaatwoord ertussen, zonder
  "met"/"incl."/"+" ("Garmin Venu Smartwatch bandjes en beschermhoezen", €25),
  wordt aan de prijs getoetst: onder 40% van de mediaan van hetzelfde model
  (`max_share_of_median`) is het een accessoire. Met een koppelwoord ("Venu Sq
  - Inclusief Oplaadkabel", €40) blijft het het apparaat — een goedkoop.

**De waarde van je eigen computer.** "Netto" in Upgrades is de prijs min wat
je eigen computer opbrengt: `eigen_verkoopprijs_eur` onder `baseline` in
`computer_scoring.json`, op €75 (een zwarte vlek rechtsonder op het scherm,
verder goed; een onbeschadigde Roam v1 werd op ±€109 geschat). Zet hem op
`null` om weer de marktschatting te gebruiken.

## Twee maten, los van elkaar

Geen van beide is de dealscore.

- **Upgrade** — de functiescore van het model (0-100) min die van je eigen
  computer (`baseline` in de JSON: de Wahoo ELEMNT ROAM v1). De gewichten koos
  de eigenaar (28-09-2026): navigatie 35 (rerouting, routeerbare kaarten,
  automatische Strava/Komoot-sync), plannen op het apparaat zelf 20, training
  25 (ANT+, Di2/AXS, workouts, klimfunctie), bediening 10 (knoppen boven
  touch), accu 10. Een model zonder updates meer verliest 15 punten, een
  waarvan de maker gestopt is maar dat nog ondersteund wordt 5. Een leeg veld
  is niet nagezocht en levert niets op — het dashboard zegt per model hoeveel
  velden onbekend zijn, dus een lage score kan "onbekend" betekenen in plaats
  van "slecht".
- **Flipwinst** — zie hierboven.

Een gewoon rapport (`racefiets_jev.py`) van een run met fietscomputers krijgt
nog een kleine tab **Fietscomputers** met de flips, upgrades en wat
uitgefilterd is; een run zonder toont de tab niet.

## Wat telt als computer

Alleen de titel telt, en elke titel met een bekend model krijgt één soort:
`computer`, `accessoire`, `onderdeel`, `defect` of `gevraagd` (een fiets, of
een advertentie in een fietscategorie, valt helemaal buiten). Uit de volledige
crawl van de categorie (28-09-2026, 361 advertenties):

- Een echte computer noemt het apparaat of een koppelwoord vóór het houder- of
  hoesjeswoord — "Garmin Edge 530 + stuurmount", "Garmin Edge Explore
  fietscomputer met houder en doos", "Garmin 840 Sensor Bundle" — terwijl een
  los accessoire dat woord vóór het model heeft ("Hoesje voor Garmin 1000",
  "K-Edge ... Bolt ... mount") of er direct achter zonder iets ertussen
  ("Hammerhead Karoo 3 houder nieuw").
- Dat laatste geval beslist de prijs: onder 40% van de mediaan van het model,
  of zonder mediaan onder 20% van de nieuwprijs, of zonder beide onder €30
  (`filter` in `computer_scoring.json`), is het een accessoire. Een twijfelachtige
  titel zonder prijs blijft een computer, met "kijk op de foto" — liever een
  houder die erdoor glipt (de foto laat het zien) dan een computer die
  verdwijnt.
- Titels zonder bekend model gaan door dezelfde soort regels: displays van
  e-bikes en fatbikes (Bosch, Sparta, Gazelle, Batavus, H6C, Shimano SC-E…,
  "display", "scherm") zijn `e-bike`, een houder of sensor zonder computer
  ervoor is `accessoire`, en een titel die geen fietscomputer en geen merk
  dat ze maakt noemt, is `overig`. Wat overblijft heet "model onbekend".
- Altijd eruit: reparaties en defecten ("scherm vervangen", "defect", "voor
  onderdelen", "batterij vervangen"), onderdelen ("LCD", "color kit",
  "koord"), gezocht-advertenties ("ik zoek ...") en — de enige regel die de
  omschrijving leest — een advertentie waarvan de omschrijving zegt dat de
  computer er niet bij zit ("accessoires zonder de fietscomputer"). Op die
  crawl hield dit 277 computers met bekend model over en zette het precies de
  18 accessoires, onderdelen, reparaties en gezocht-advertenties in
  Uitgefilterd.

Schrijfwijzen van verkopers worden vóór het matchen rechtgezet: meerdere
spaties worden één ("Garmin Edge  1030 Plus"), een streepje tussen naam en
nummer wordt een spatie ("EDGE-530"), en "Egde" leest als "Edge". "520+",
"Explorer 2", "Garmin Explore 2" en "Wahoo Element Ace/Mini/Bolt/Roam" vinden
hun model. Houder- en hoesjeswoorden tellen ook in het Frans, Spaans,
Italiaans en Duits (support, soporte, supporto, Halterung, staffa, capa,
coque, funda, housse, étui, protection), net als de koppelwoorden "mit",
"inkl", "avec" en "con". "For", "voor", "pour", "para" of "für" direct voor
de modelnaam maakt het een accessoire ("Wahoo bike computer for Element
ROAM"). Al deze kwamen uit een Vinted-export van 867 Garmin- en Wahoo-titels
(28-09-2026).

De zoekopdracht `fietscomputer` dekt de **hele categorie**: met de categorie
ingesteld geeft "fietscomputer" alles wat erin staat (2800 advertenties op
28-09-2026, evenveel als zonder query). Ongeveer 95 pagina's per nacht in
plaats van ~360 advertenties voor 17 merknamen, maar hij vond 87 computers
met bekend model meer — titels als "Garmin 830" of "Garmin 1030 incl.
stuurmontage" die "garmin edge" niet vindt. Op die crawl waren 1734
advertenties e-bike-displays (naar Uitgefilterd), en ging geen computer
verloren die de merkzoekopdrachten wel hadden gevonden.

## Het referentiebestand — `reference_bike_computers.csv`

Vaste woorden per kolom, zodat de score het kan lezen: `rerouting` is `ja`,
`via_telefoon` of `nee`; `kaarten` `routeerbaar`, `los_te_koop`,
`basiskaart` of `nee`; `planning_op_apparaat` `volledig`, `beperkt` of `nee`;
`bediening` `knoppen`, `touch+knoppen` of `touch`; `ondersteund` `ja`,
`beperkt` of `nee`. Iets anders stopt het inlezen met het rijnummer. Getallen
met een punt. De volgorde in het bestand is de matchvolgorde, dus "Edge 1030
Plus" komt vóór "Edge 1030". Net als de andere referentiebestanden staat hij
erin met `git add -f`.

## Vinted naast Marktplaats — `vinted.py`

Vinted wordt hier niet gecrawld: je exporteert zelf een Vinted-zoekopdracht
(een CSV met de kolommen "Item Title", "Item Price", "Item Service Fee", "Item
Total Price", "Item Currency", "Item URL", ...) en leest die in. Het tijdstip
van de export komt uit de bestandsnaam
(`productsList_2026-09-28T14-57-35-028Z.csv`), of `--at`. Een bestand zonder
die kolommen stopt met de naam van de ontbrekende. Het schrijft altijd naar de
`koopjes.db` naast het script (die `koopjes.py` gebruikt), in welke map je het
commando ook typt, print welk bestand dat is, en waarschuwt als het hem moest
aanmaken — zo komt een import uit je map Downloads toch in het dashboard.
`--db` kiest een andere.

```bash
python vinted.py import productsList_2026-09-28T14-53-37-277Z.csv productsList_2026-09-28T14-57-35-028Z.csv
python vinted.py                   # per model Vinted tegen Marktplaats, en wat je op Vinted koopt
python dashboard.py                # hetzelfde in de tab Vinted
```

- De advertenties gaan in hun eigen tabellen (`vinted_listing`,
  `vinted_price`, migratie 8), nooit in `listing`: een Vinted-prijs is nooit
  vergelijkingsmateriaal voor een Marktplaats-flip, en een advertentie die uit
  een latere export wegvalt is niet als verkocht gemarkeerd (een export is één
  zoekopdracht, geen volledige crawl).
- Wat je betaalt is de vraagprijs plus de kopersbescherming uit de export
  (€0,70 + 5% op 28-09-2026) plus `vinted.shipping_eur` in
  `computer_scoring.json` (€4,50, de bovenkant van een klein pakket binnen
  Nederland; meer vanuit het buitenland — de export zegt niet waarvandaan). De
  winst is de Marktplaats-verkoopprijs van Flips min dat en min `costs_eur`.
- Titels worden met dezelfde regels ingedeeld als op het dashboard, plus wat
  alleen Vinted teruggeeft omdat het niet binnen een categorie zoekt:
  horloges (Wahoo Rival, Forerunner, "montre", "reloj"), trainers, pedalen,
  autonavigatie, en alles boven `vinted.max_price_eur` (€1000: een fiets met
  een computer erbij). Twijfelachtige titels worden aan de
  Marktplaats-mediaan getoetst.

Een vergelijking van beide sites op 28-09-2026 (Garmin en Wahoo, 562
computers op Vinted, 254 op Marktplaats): voor de modellen die veel verkopen
(Edge 530, 830, Explore, Explore 2, 540, 840, 1040, 1050) ligt de mediane
vraagprijs op beide sites binnen 10%, dus kopen op Vinted loont alleen per
advertentie. Oudere modellen vragen op Vinted veel meer (Edge 1000 twee keer
zoveel), maar de meeste van die advertenties staan er al lang, dus dat is
geen hogere verkoopprijs.
