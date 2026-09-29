# Marktonderzoek: welke Marktplaats-categorieën passen bij deze koopjesfinder?

*Gemeten op 28 en 29 september 2026. Alle getallen komen rechtstreeks van
Marktplaats (de zoek-API en advertentiepagina's) en zijn niet geschat of
opgezocht. Hoe ze gemeten zijn staat in §8; de volledige lijst van 1.720
subcategorieën staat in `marktonderzoek_subcategorieen.csv`.*

## 1. Conclusie in het kort

- **De interface is bruikbaar buiten de fietsen, en de code is daar al half
  op ingericht.** Crawlen, categoriefilter, dealscore, bieden, prijshistorie
  en de verdwijnmeting zijn categorie-onafhankelijk. `markets.py` maakt van
  "een markt" nu al een referentie-CSV plus een titelindeler plus
  categorieën. Een nieuwe markt is dus vooral onderzoek (een referentiebestand
  met bronnen) en maar een beetje code.
- **Marktplaats is groot, maar de bruikbare markten zijn klein en scherp
  afgebakend.** Er staan 12,6 miljoen advertenties en er komen er ongeveer
  240.000 per dag bij. De meeste waarde voor deze tool zit in subcategorieën
  met **30 tot 700 nieuwe advertenties per dag** en een herkenbaar model in
  de titel. Zo'n instroom is elke nacht bij te houden (1 tot 25 pagina's op
  nieuwste). Vooral dat laatste
  bepaalt of een koopje als koopje te herkennen is.
- **Beste kandidaten voor een volgende markt**, in volgorde. De score (0–100,
  §5) weegt volume, verzendbaarheid, prijsniveau, prijsdata, merk/model-data
  en doorlooptijd.
  1. **Camera-objectieven** (#1): 229 nieuw per dag, 76% verzendbaar,
     mediaan €300, merk en vatting als vaste velden. Modellen zijn exact te
     benoemen ("Canon EF 70-200 f/4L").
  2. **iPhones** (#2): 689 per dag, snelste doorlooptijd van alle grote
     markten (26 dagen). Model, opslag en batterijconditie zijn velden.
     Risico's: iCloud-lock, vervangen schermen, handelaren.
  3. **iPads / MacBooks** (#3, #16): elk ~130 per dag, model in 83–94% van
     de advertenties ingevuld.
  4. **Nintendo Switch-consoles** (#4) en **Switch-games** (#23): smalle
     modellenlijst en snelle markt.
  5. **Digitale camera's** (#6): 316 per dag, merk in 82% ingevuld.
  6. **Drones** (#24): DJI is 45% van het aanbod, en modellen zijn exact.
  7. **Smartwatches** (#44), in `NEXT_STEPS.md` al genoemd. De sporthorloges
     die er sinds kort in zitten staan zelf op **#18**: dat bevestigt de
     scoremethode.
- **Vermijden als flipmarkt**: Boeken (mediaan €11), Cd's/Dvd's en vinyl
  (€6, de helft zonder prijs), Postzegels en Munten (€1,20), Verzamelen (€5),
  Huis en Inrichting en Tuin (grotendeels alleen ophalen, geen merkvelden),
  Auto's (79–86% bedrijven, een ander vak), en alle niet-goederen (Vacatures,
  Diensten, Huizen, Vakantie, Contacten, Tickets).
- **Speciaal geval Lego** (#25): enorm (2.268 nieuw per dag, 129.618 in
  totaal, 88% verzendbaar), met een setnummer als perfecte sleutel. Het
  aanbod is alleen te groot voor één zoekopdracht (plafond ~5.000
  resultaten), dus alleen haalbaar met zoekopdrachten per thema of setnummer.
  Voor Pokémon (3.684 per dag) geldt hetzelfde, en daar staat 43% van de
  advertenties zonder prijs.

## 2. Marktplaats in cijfers

| | |
|---|---|
| Hoofdcategorieën | 36 (waarvan 6 geen tweedehands goederen) |
| Subcategorieën (niveau 2) | 1.949, waarvan 1.720 met goederen |
| Advertenties totaal | 12,6 miljoen |
| Nieuw of opnieuw bovenaan per dag | ~240.000 (gemiddelde van de afgelopen week) |
| Verzendbaar (optie "Verzenden") | 72% van alle goederen |
| Doorlooptijd (mediaan subcategorie) | ~52 dagen (aanbod ÷ instroom; zie §8 voor de vertekening) |
| Subcategorieën met ≤ 5.000 advertenties (één complete crawl) | 1.118 van 1.720, samen maar 15% van het aanbod |
| Subcategorieën met ≥ 10 nieuwe per dag | 1.416 |
| Subcategorieën met een merk- of modelveld | 434; daarin is gemiddeld 45% van de advertenties ingevuld |

Drie dingen vallen op. Ze zijn allemaal belangrijk voor hoe je de tool
uitbreidt:

1. **Het aanbod is scheef verdeeld.** De drie grootste hoofdcategorieën
   (Huis en Inrichting, Boeken, Kinderen en Baby's) hebben samen 3,6 miljoen
   advertenties. Maar een markt van 100 à 300 nieuwe per dag (Sporthorloges,
   iPads, Lenzen) is voor deze tool juist ideaal: groot genoeg voor een
   betrouwbare mediaan per model, klein genoeg om elke nacht compleet te
   crawlen.
2. **Een op de vier advertenties heeft geen prijs.** "Bieden" zonder
   vraagprijs (`FAST_BID`) is 26% van de instroom; per hoofdcategorie
   14–48%, met Auto's (1%) als uitzondering. De dealscore kan
   daar niets mee, de biedopvraging (`--bid-lookup`) wel. In Cd's/Dvd's (48%)
   en Postzegels (45%) is dat een groot gat.
3. **"Vandaag" is niet altijd nieuw.** Van de steekproefadvertenties die in
   de zoekresultaten "Vandaag" heetten, was 19% al meer dan 36 uur eerder
   geplaatst: opnieuw bovenaan gezet of met een betaalde Dagtopper. Bij de
   gesorteerd-op-nieuwste crawl kost dat pagina's, en de "instroom" hieronder
   is daardoor ~20% te hoog.

## 3. Alle hoofdcategorieën

Kolommen: **Aanbod** = alle advertenties nu. **Nieuw/dag** = gemiddelde over
de laatste 7 dagen (filter "Aangeboden sinds"). **Looptijd** = aanbod ÷
nieuw per dag, een ruwe maat voor hoe lang een advertentie blijft staan.
**Verzendbaar** = aandeel met de optie Verzenden. **Direct Kopen** = aandeel
met Marktplaats' eigen betalen-en-verzenden. **Mediane prijs** = van
advertenties met een prijs, gewogen naar instroom per subcategorie, zonder
betaalde Dagtoppers. **Met prijs** = vaste prijs of bieden vanaf een prijs.
**Bieden zonder prijs** = alleen "Bieden". **Nieuw** = conditie Nieuw (– =
de categorie kent geen conditieveld). **Merk/model ingevuld** = aandeel
advertenties met een concreet merk of model in het vaste veld (niet
"Overige"). Kolommen met * komen uit een steekproef van 14
advertentiepagina's per hoofdcategorie en hebben dus een ruime foutmarge
(±25 procentpunt).

| Hoofdcategorie | Aanbod | Nieuw/dag | Looptijd (d) | Verzendbaar | Direct Kopen | Mediane prijs [p25–p75] | Met prijs | Bieden zonder prijs | Nieuw | Merk/model ingevuld | Bedrijf* | Weergaven/dag* |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| Huis en Inrichting | 1.284.141 | 30.632 | 42 | 44% | 12% | €75 [€30–€240] | 69% | 24% | 18% | 3% | 7% | 29 |
| Boeken | 1.201.941 | 19.117 | 63 | 92% | 27% | €11 [€6,00–€25] | 69% | 27% | 9% | 4% | 14% | 12 |
| Kinderen en Baby's | 1.069.110 | 18.555 | 58 | 68% | 27% | €25 [€10–€60] | 73% | 21% | 17% | 22% | 0% | 25 |
| Verzamelen | 902.807 | 14.272 | 63 | 90% | 11% | €5,00 [€2,50–€25] | 68% | 27% | 14% | 2% | 14% | 17 |
| Cd's en Dvd's | 882.332 | 12.317 | 72 | 95% | 15% | €6,00 [€2,75–€25] | 49% | 48% | 0% | 0% | 7% | 10 |
| Auto-onderdelen | 871.326 | 12.507 | 70 | 77% | 3% | €125 [€35–€400] | 75% | 22% | 11% | 75% | 43% | 13 |
| Hobby en Vrije tijd | 767.572 | 13.801 | 56 | 86% | 20% | €35 [€10–€180] | 61% | 32% | 37% | 11% | 14% | 23 |
| Kleding › Dames | 715.196 | 11.498 | 62 | 92% | 38% | €25 [€11–€65] | 81% | 18% | 25% | 20% | 14% | 19 |
| Antiek en Kunst | 624.972 | 11.839 | 53 | 70% | 16% | €45 [€24–€110] | 55% | 40% | – | 0% | 8% | 21 |
| Sieraden, Tassen en Uiterlijk | 380.605 | 6.502 | 59 | 86% | 31% | €45 [€15–€150] | 81% | 16% | 42% | 4% | 0% | 20 |
| Postzegels en Munten | 372.761 | 5.906 | 63 | 97% | 3% | €1,20 [€0,20–€7,50] | 54% | 45% | – | 0% | 7% | 10 |
| Doe-het-zelf en Verbouw | 359.588 | 7.988 | 45 | 48% | 15% | €115 [€38–€350] | 66% | 25% | 36% | 2% | 50% | 26 |
| Fietsen en Brommers | 332.565 | 9.397 | 35 | 39% | 12% | €200 [€50–€849] | 75% | 23% | 12% | 17% | 21% | 30 |
| Tuin en Terras | 297.619 | 5.791 | 51 | 36% | 9% | €50 [€22–€150] | 60% | 24% | 24% | 0% | 21% | 23 |
| Kleding › Heren | 274.652 | 4.859 | 57 | 91% | 40% | €45 [€20–€80] | 75% | 24% | 29% | 21% | 0% | 14 |
| Auto's | 265.190 | 11.011 | 24 | n.v.t. | 0% | €12.500 [€6.945–€23.500] | 99% | 1% | 4% | 98% | 79% | 36 |
| Audio, Tv en Foto | 213.103 | 5.217 | 41 | 65% | 21% | €75 [€30–€250] | 66% | 32% | 17% | 33% | 0% | 25 |
| Auto diversen | 205.249 | 4.084 | 50 | 70% | 12% | €120 [€40–€425] | 71% | 26% | – | 1% | 0% | 10 |
| Sport en Fitness | 202.372 | 3.939 | 51 | 65% | 26% | €90 [€35–€300] | 75% | 21% | 22% | 9% | 21% | 11 |
| Dieren en Toebehoren | 185.121 | 4.512 | 41 | 41% | 16% | €50 [€20–€125] | 56% | 25% | – | 7% | 14% | 66 |
| Motoren | 170.681 | 3.363 | 51 | 54% | 12% | €175 [€50–€2.800] | 82% | 14% | – | 4% | 57% | 16 |
| Witgoed en Apparatuur | 158.630 | 3.945 | 40 | 47% | 18% | €70 [€30–€150] | 67% | 30% | 19% | 27% | 21% | 29 |
| Spelcomputers en Games | 153.675 | 3.593 | 43 | 83% | 26% | €40 [€15–€130] | 75% | 22% | 8% | 11% | 36% | 21 |
| Computers en Software | 152.533 | 3.685 | 41 | 70% | 23% | €95 [€30–€285] | 75% | 22% | 21% | 7% | 21% | 22 |
| Diversen | 100.687 | 2.751 | 37 | 69% | 17% | €100 [€35–€100] | 56% | 37% | 28% | 1% | 14% | 12 |
| Muziek en Instrumenten | 91.181 | 1.893 | 48 | 65% | 16% | €150 [€40–€400] | 68% | 27% | 14% | 7% | 14% | 13 |
| Caravans en Kamperen | 88.581 | 1.835 | 48 | 40% | 14% | €267 [€50–€23.450] | 81% | 16% | – | 17% | 33% | 19 |
| Watersport en Boten | 85.319 | 1.540 | 55 | 58% | 17% | €100 [€38–€475] | 71% | 26% | 25% | 4% | 29% | 34 |
| Telecommunicatie | 75.574 | 1.897 | 40 | 75% | 27% | €200 [€65–€450] | 73% | 25% | 30% | 33% | 14% | 9 |
| Zakelijke goederen | 33.086 | 768 | 43 | 28% | 3% | €3.750 [€1.100–€8.750] | 65% | 14% | – | 4% | 36% | 3 |
| Tickets en Kaartjes | 19.859 | 569 | 35 | – | 0% | €60 [€30–€100] | 55% | 35% | – | 0% | 0% | 30 |
| Diensten en Vakmensen | 18.127 | 123 | 147 | – | 0% | €45 [€20–€88] | 38% | 11% | – | 0% | 36% | 1 |
| Vacatures | 14.993 | 668 | 22 | – | 0% | €20 [€10–€20] | 7% | 6% | – | 0% | 77% | 3 |
| Huizen en Kamers | 4.620 | 80 | 58 | – | 0% | €1.000 [€500–€1.730] | 60% | 19% | – | 0% | 43% | 20 |
| Vakantie | 2.788 | 11 | 250 | – | 0% | €650 [€250–€97.500] | 38% | 9% | – | 0% | 0% | 3 |
| Contacten en Berichten | 590 | 15 | 40 | – | 0% | €169 [€50–€249] | 36% | 9% | – | 0% | 9% | 15 |

\* steekproef van 14 advertentiepagina's per hoofdcategorie. **Looptijd** is een voorraadmaat, geen verkoopduur (§8).

## 4. Oordeel per hoofdcategorie

Per categorie: wat voor markt het is, en de beste subcategorieën met hun rang
van de 1.720 (§5). "Past goed" betekent dat het model in de titel te
herkennen is, dat er verzonden wordt en dat de prijzen hoog genoeg zijn om
na verzending en afdingen iets over te houden.

**Past goed:**

- **Audio, Tv en Foto** (213k aanbod, 5.217 per dag). De sterkste
  hoofdcategorie: lenzen (#1), digitale camera's (#6), koptelefoons (#22),
  drones (#24), flitsers (#28) en analoge camera's (#31). Veel vaste velden
  (merk, vatting, brandpuntsafstand, megapixels). Televisies (#196) juist
  niet: maar 26% verzendbaar. Luidsprekers, waar de tool mee begon, staan op
  #115: 738 per dag, maar maar 52% verzendbaar en het merk is in
  maar 39% van de advertenties ingevuld.
- **Telecommunicatie** (76k, 1.897 per dag). iPhone (#2), oordopjes (#5, 40%
  nieuw: pas op voor namaak-AirPods), Samsung (#26). iPhone-velden: model
  86%, opslag 88%, batterijconditie 43% ingevuld. Doorlooptijd 26 dagen,
  de kortste van alle grote markten.
- **Computers en Software** (153k, 3.685 per dag). iPads (#3), harde
  schijven (#11), MacBooks (#16), processors (#27), RAM (#39). Het
  MacBook-model is in 96% van de advertenties ingevuld, met schermmaat,
  processor, opslag en RAM ernaast. Windows-laptops (#93) scoren
  redelijk, maar zijn te divers om per model te vergelijken.
- **Spelcomputers en Games** (154k, 3.593 per dag). Switch (#4), DS (#14),
  Switch-games (#23), Game Boy (#35), PS5 (#42). Het consolemodel is een
  vast veld met weinig waarden ("Switch OLED", "PS5 Digital"). Games zijn
  goedkoop per stuk (PS5-game mediaan €52), maar 79–87% verzendbaar en
  meestal met prijs (77%).
- **Sieraden, Tassen en Uiterlijk** (381k, 6.502 per dag). Sporthorloges
  (#18, al een markt), herenhorloges (#36, met Rolex en Breitling in de top
  vier: echtheid is een risico dat de tool niet ziet), smartwatches (#44),
  activity trackers (#46).
- **Hobby en Vrije tijd** (768k, 13.801 per dag). Modeltreinen N (#12) en H0
  (#50), modelauto's 1:18 (#13). Merk (Fleischmann, Trix, Märklin, Roco) is
  goed ingevuld; het artikelnummer staat alleen in de tekst.
  Pokémon-kaarten (#235) zijn met 3.684 per dag de subcategorie met de
  meeste nieuwe advertenties van heel Marktplaats, maar 43% staat zonder prijs.
- **Sport en Fitness** (202k, 3.939 per dag). Hardloop- en atletiekspullen
  (#15), tennis (#21), ski (#30), padel (#43). Merk vaak
  ingevuld, maar modellen zijn minder scherp dan bij elektronica.

**Past met beperkingen:**

- **Auto-onderdelen** (871k, 12.507 per dag). Scoort hoog op papier: remmen
  (#10), brandstof (#17), spiegels (#19). Het "merk" is hier echter het
  **automerk**, niet het onderdeel. Een koopje is alleen te herkennen met een
  onderdeelnummer (OEM-nummer), en de doorlooptijd is lang (55–118 dagen).
  Volgens de steekproef zijn 43% bedrijven (sloperijen).
- **Kinderen en Baby's** (1,07 mln, 18.555 per dag). Alleen Lego (#25) is
  interessant: setnummers maken het vergelijkbaar, maar het aanbod is te
  groot voor één zoekopdracht (§1). Kinderwagens (#431) zijn maar 25%
  verzendbaar.
- **Kleding Dames en Heren** (990k samen, 16.357 per dag). Scoort
  verrassend hoog (winterjassen dames #7, truien heren #9): enorm volume,
  ~90% verzendbaar, bijna altijd met prijs. Maar het merk is maar in 19–24%
  ingevuld, en "Zara-jas maat M" is geen model met een vaste marktprijs. Dit
  is Vinted-terrein (Direct Kopen 38–40%, het hoogste van Marktplaats).
- **Muziek en Instrumenten** (91k, 1.893 per dag). Effecten (#90),
  synthesizers (#105), microfoons (#83). Modellen zijn scherp (een Boss
  DS-1 is een Boss DS-1), maar er is geen merkveld bij effecten: het merk
  moet uit de titel komen, zoals nu bij de fietscomputers.
- **Witgoed en Apparatuur** (159k, 3.945 per dag). Koffiezetapparaten (#49,
  467 per dag, maar 49% verzendbaar) en stofzuigers (#79). Het "model"-veld
  zegt alleen "Koffiemachine" of "Espresso apparaat", dus het echte model
  moet uit de titel komen.
- **Fietsen en Brommers** (333k, 9.397 per dag). De huidige
  thuisbasis. Racefietsen staan op #433, en dat is terecht voor een landelijke
  flipmarkt: maar 23% verzendbaar. Voor de eigen fiets taxeren maakt dat
  niet uit. Fietsonderdelen (#103, 660 per dag, 74% verzendbaar),
  fietscomputers (#130) en scooteronderdelen (#40) passen beter bij het
  flipmodel.
- **Motoren** (171k, 3.363 per dag). Motorkleding (#78) en helmen (#99)
  zijn verzendbaar. In de steekproef van Motoren is 57% van bedrijven.
  32% staat in een "Overige"-subcategorie, de hoogste van alle categorieën,
  dus op categorie filteren lukt slecht.
- **Antiek en Kunst** (625k, 11.839 per dag). Niet-westerse kunst (#89),
  etsen (#149). Geen merken en geen modellen; een koopje herkennen vraagt
  kennis die niet in de titel staat. 40% bieden zonder prijs.
- **Postzegels en Munten**. Alleen Edelmetalen en Baren (#8) valt op:
  93% verzendbaar, 90% met prijs, doorlooptijd 29 dagen. De waarde volgt de
  goud- en zilverprijs, dus hier zou een externe koers als referentie dienen
  in plaats van een mediaan. De rest (postzegels €1,20) is te goedkoop.

**Past niet:**

- **Huis en Inrichting** (1,28 mln, 30.632 per dag, de grootste). 44%
  verzendbaar, 3% met merk. Meubels zijn ophalen en uniek.
- **Tuin en Terras** (298k). 36% verzendbaar, 0% met merk. Bovenaan staat
  Haardhout (#301).
- **Doe-het-zelf en Verbouw** (360k). Handgereedschap (#145) is op zich
  interessant (grootste merken Gedore, Stanley, Makita, Bosch), maar het
  merkveld is maar in 11% ingevuld en de helft van de steekproef is van
  bedrijven.
- **Boeken** (1,2 mln), **Cd's en Dvd's** (882k), **Verzamelen** (903k):
  mediaan €5–11, verzending kost ongeveer evenveel als het artikel. Vinyl
  scoort per genre 40–78, met Hiphop (#87) als uitschieter.
- **Auto's** (265k, 11.011 per dag). 86% van het aanbod is van bedrijven
  (filter "Adverteerder": 226.029 van 261.497). 99% met prijs en volledig
  gestructureerd (bouwjaar, km-stand, brandstof), maar niet verzendbaar,
  en de dealers prijzen al scherp. Een koopjesfinder voor auto's is een
  ander product.
- **Caravans en Kamperen**, **Watersport en Boten**, **Zakelijke goederen**:
  grote bedragen, ophalen, weinig volume per model. Alleen
  kampeergereedschap (#116) en kitesurfen (#133) komen in de buurt.
- **Dieren en Toebehoren**: paardrijkleding (#59) scoort redelijk. Levende
  dieren zijn om voor de hand liggende redenen buiten beschouwing gelaten.
- **Auto diversen**, **Diversen**: allegaartjes. Bij Auto diversen staat
  20% in "Overige", Diversen is voor 35% Kerst.
- **Niet-goederen**: Vacatures (77% bedrijf, 7% met prijs), Diensten,
  Huizen en Kamers, Vakantie, Contacten, Tickets. Uitgesloten van de score.
  Tickets zou technisch werken (56 per dag in Concerten › Pop), maar
  doorverkoop boven de nominale prijs ligt juridisch gevoelig.

## 5. De top 50 van alle subcategorieën

De score (0–100) is een gewogen som van zes deelscores, elk 0–1:

| Deelscore | Gewicht | 0 bij | 1 bij | Waarom |
|---|---:|---|---|---|
| Volume (nieuw/dag, log) | 20% | 3 | 60+ | onder de 3 per dag is er geen mediaan per model |
| Verzendbaar | 20% | 30% | 90% | landelijke markt, zowel bij inkoop als verkoop |
| Prijsniveau (mediaan) | 20% | €8 (en €10.000) | €40–€1.500 | onder de €40 eet de verzending de marge op, boven de €1.500 zit het risico |
| Prijsdata (met prijs) | 15% | 40% | 90% | de dealscore heeft een vraagprijs nodig |
| Structuur (merk/model ingevuld + velden) | 15% | – | merk ≥70% + 3 velden | een model moet te herkennen zijn |
| Doorlooptijd | 10% | 75 dagen | ≤ 25 dagen | een snelle markt verkoopt ook snel weer door |

De gewichten zijn een keuze, geen meting. De CSV heeft alle ruwe kolommen,
dus met andere gewichten kun je zelf opnieuw sorteren. Ter controle: de twee
markten die de eigenaar zelf al koos, staan hoog. Sporthorloges #18 (85),
fietscomputers #130 (76).

| # | Subcategorie | Hoofdcategorie | Score | Nieuw/dag | Aanbod | Verzendbaar | Looptijd (d) | Mediane prijs | Met prijs | Merk/model ingevuld | Grootste merken |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Fotografie › Lenzen en Objectieven | Audio, Tv en Foto | 90 | 229 | 8.798 | 76% | 38 | €300 | 87% | 59% | Canon, Nikon, Sigma |
| 2 | Mobiele telefoons › Apple iPhone | Telecommunicatie | 89 | 689 | 18.025 | 61% | 26 | €300 | 87% | 80% | iPhone 13, iPhone 11, iPhone 15 |
| 3 | Apple iPads | Computers en Software | 89 | 131 | 4.442 | 67% | 34 | €312 | 83% | 83% | Apple iPad, Apple iPad Air, Apple iPad Pro |
| 4 | Spelcomputers › Nintendo Switch | Spelcomputers en Games | 88 | 224 | 7.751 | 67% | 35 | €225 | 83% | 75% | Switch Original, Switch OLED, Switch 2019 Upgrade |
| 5 | Mobiele telefoons › Oordopjes | Telecommunicatie | 87 | 72 | 3.130 | 84% | 44 | €35 | 93% | 45% | Apple, Samsung, JBL |
| 6 | Fotocamera's Digitaal | Audio, Tv en Foto | 86 | 316 | 11.452 | 71% | 36 | €375 | 73% | 82% | Canon, Sony, Nikon |
| 7 | Jassen › Winter | Kleding › Dames | 86 | 713 | 26.945 | 88% | 38 | €100 | 87% | 19% | Zara, H&M, Only |
| 8 | Edelmetalen en Baren | Postzegels en Munten | 86 | 101 | 2.945 | 93% | 29 | €80 | 90% | – |  |
| 9 | Truien en Vesten | Kleding › Heren | 86 | 549 | 24.869 | 94% | 45 | €40 | 87% | 24% | Tommy Hilfiger, Nike, Jack & Jones |
| 10 | Remmen en Aandrijving | Auto-onderdelen | 86 | 291 | 34.332 | 88% | 118 | €60 | 93% | 89% | Volkswagen, BMW, Mercedes-Benz |
| 11 | Harde schijven | Computers en Software | 86 | 130 | 4.623 | 86% | 36 | €100 | 87% | – |  |
| 12 | Modeltreinen › N-Spoor | Hobby en Vrije tijd | 86 | 130 | 4.929 | 95% | 38 | €150 | 60% | 52% | Fleischmann, Trix, Arnold |
| 13 | Modelauto's › 1:18 | Hobby en Vrije tijd | 85 | 289 | 18.915 | 94% | 66 | €140 | 80% | 59% | Norev, Bburago, OttOMobile |
| 14 | Spelcomputers › Nintendo DS | Spelcomputers en Games | 85 | 23 | 719 | 83% | 31 | €50 | 73% | 86% | DS Lite, Dsi, DS Original of Phat |
| 15 | Loopsport en Atletiek | Sport en Fitness | 85 | 133 | 6.833 | 80% | 51 | €90 | 83% | 43% | Nike, Asics, Adidas |
| 16 | Apple Macbooks | Computers en Software | 85 | 126 | 4.113 | 58% | 33 | €325 | 80% | 94% | MacBook Pro, MacBook Air, MacBook |
| 17 | Brandstofsystemen | Auto-onderdelen | 85 | 105 | 10.136 | 88% | 96 | €89 | 87% | 84% | BMW, Volkswagen, Mercedes-Benz |
| 18 | Sporthorloges | Sieraden, Tassen en Uiterlijk | 85 | 89 | 3.251 | 86% | 37 | €195 | 83% | – |  |
| 19 | Spiegels | Auto-onderdelen | 85 | 252 | 16.425 | 88% | 65 | €130 | 80% | 76% | Volkswagen, BMW, Mercedes-Benz |
| 20 | Uitlaatsystemen | Auto-onderdelen | 84 | 202 | 11.192 | 72% | 55 | €150 | 90% | 89% | Volkswagen, Mercedes-Benz, BMW |
| 21 | Tennis | Sport en Fitness | 84 | 121 | 5.943 | 75% | 49 | €50 | 77% | 57% | Wilson, Babolat, Head |
| 22 | Koptelefoons | Audio, Tv en Foto | 84 | 281 | 12.014 | 79% | 43 | €72 | 70% | 52% | Apple, JBL, Sony |
| 23 | Games › Nintendo Switch | Spelcomputers en Games | 83 | 337 | 11.303 | 87% | 34 | €120 | 77% | – |  |
| 24 | Drones | Audio, Tv en Foto | 83 | 90 | 3.554 | 77% | 40 | €172 | 70% | 49% | DJI, Parrot, Potensic |
| 25 | Speelgoed › Duplo en Lego | Kinderen en Baby's | 83 | 2.268 | 129.618 | 88% | 57 | €250 | 57% | 82% | Lego, Duplo, Lego Primo |
| 26 | Mobiele telefoons › Samsung | Telecommunicatie | 83 | 266 | 6.992 | 63% | 26 | €350 | 67% | 65% | Galaxy A, Galaxy S24, Galaxy S23 |
| 27 | Processors | Computers en Software | 83 | 61 | 2.399 | 84% | 40 | €50 | 87% | – |  |
| 28 | Fotografie › Flitsers | Audio, Tv en Foto | 83 | 54 | 2.234 | 81% | 42 | €50 | 63% | 55% | Canon, Metz, Nikon |
| 29 | Instrumenten › Onderdelen | Muziek en Instrumenten | 82 | 69 | 2.988 | 88% | 43 | €150 | 100% | – |  |
| 30 | Skiën en Langlaufen | Sport en Fitness | 82 | 268 | 7.921 | 68% | 30 | €90 | 73% | 44% | Atomic, Salomon, Head |
| 31 | Fotocamera's Analoog | Audio, Tv en Foto | 82 | 213 | 10.315 | 82% | 48 | €50 | 73% | 49% | Canon, Minolta, Kodak |
| 32 | Jassen › Winter | Kleding › Heren | 82 | 424 | 14.937 | 86% | 35 | €375 | 77% | 19% | PME Legend, Jack & Jones, The North Face |
| 33 | Carrosserie en Plaatwerk | Auto-onderdelen | 82 | 3.023 | 199.076 | 82% | 66 | €350 | 67% | 81% | Mercedes-Benz, Volkswagen, BMW |
| 34 | Besturing | Auto-onderdelen | 82 | 278 | 22.144 | 82% | 80 | €200 | 83% | 76% | Mercedes-Benz, BMW, Volkswagen |
| 35 | Spelcomputers › Nintendo Game Boy | Spelcomputers en Games | 82 | 31 | 869 | 81% | 28 | €99 | 67% | 61% | Game Boy Color, Game Boy Advance, Game Boy Classic |
| 36 | Horloges › Heren | Sieraden, Tassen en Uiterlijk | 82 | 288 | 12.386 | 78% | 43 | €175 | 77% | 28% | Rolex, Seiko, Casio |
| 37 | Verlichting | Auto-onderdelen | 82 | 1.117 | 75.993 | 86% | 68 | €150 | 73% | 86% | Mercedes-Benz, Volkswagen, BMW |
| 38 | Klein materiaal | Auto-onderdelen | 82 | 93 | 5.685 | 82% | 61 | €118 | 73% | 91% | BMW, Volkswagen, Volvo |
| 39 | RAM geheugen | Computers en Software | 81 | 166 | 6.792 | 85% | 41 | €100 | 77% | – |  |
| 40 | Brommeronderdelen › Scooters | Fietsen en Brommers | 81 | 457 | 20.145 | 77% | 44 | €200 | 67% | 59% | Piaggio, Vespa, Peugeot |
| 41 | Games › Sony PlayStation 5 | Spelcomputers en Games | 81 | 287 | 8.893 | 79% | 31 | €52 | 77% | – |  |
| 42 | Spelcomputers › Sony PlayStation 5 | Spelcomputers en Games | 81 | 83 | 1.779 | 61% | 21 | €500 | 80% | 53% | Playstation 5, Playstation 5 Digital |
| 43 | Padel | Sport en Fitness | 81 | 51 | 1.693 | 85% | 33 | €80 | 87% | – |  |
| 44 | Smartwatches | Sieraden, Tassen en Uiterlijk | 81 | 271 | 10.962 | 72% | 40 | €187 | 90% | – |  |
| 45 | Mobiele telefoons › Overige merken | Telecommunicatie | 81 | 97 | 3.643 | 72% | 38 | €275 | 80% | 24% | Klassiek of Candybar, Inklapmodel, Schuifmodel |
| 46 | Activity trackers | Sieraden, Tassen en Uiterlijk | 81 | 35 | 1.270 | 84% | 37 | €89 | 87% | – |  |
| 47 | Android Tablets | Computers en Software | 81 | 67 | 1.846 | 67% | 28 | €120 | 87% | – |  |
| 48 | Fotografie › Fototassen | Audio, Tv en Foto | 81 | 60 | 2.635 | 78% | 44 | €40 | 63% | 49% | Lowepro, Case Logic, Vanguard |
| 49 | Koffiezetapparaten | Witgoed en Apparatuur | 81 | 467 | 18.050 | 49% | 39 | €175 | 80% | 88% | Koffiemachine, Espresso apparaat, Combi |
| 50 | Modeltreinen › H0 | Hobby en Vrije tijd | 81 | 523 | 24.404 | 92% | 47 | €200 | 37% | 70% | Märklin, Fleischmann, Roco |

De volledige ranglijst (1.720 rijen) staat in `marktonderzoek_subcategorieen.csv`.

## 6. De kandidaten van dichtbij

Alle getallen zijn gemeten. "Velden" is het aandeel advertenties waarin
Marktplaats' eigen filterveld is ingevuld; dat komt gratis mee in elk
zoekresultaat.

| Markt | Aanbod | Nieuw/dag | Verzendbaar | Looptijd | Prijs p25–mediaan–p75 | Bieden zonder prijs | Nieuw | Velden |
|---|---:|---:|---:|---:|---|---:|---:|---|
| Lenzen en objectieven | 8.798 | 229 | 76% | 38 d | €153 – €300 – €800 | 13% | 5% | merk 71%, vatting 62%, type 92% |
| Apple iPhone | 18.025 | 689 | 61% | 26 d | €195 – €300 – €700 | 13% | 8% | model 86%, opslag 88%, batterij 43% |
| Apple iPads | 4.442 | 131 | 67% | 34 d | €88 – €313 – €553 | 13% | 12% | model 86%, scherm 81%, opslag 77% |
| Apple MacBooks | 4.113 | 126 | 58% | 33 d | €173 – €325 – €775 | 20% | 4% | model 96%, processor 84%, RAM 65% |
| Nintendo Switch (console) | 7.751 | 224 | 67% | 35 d | €175 – €225 – €405 | 13% | 11% | model 75%, controllers 70% |
| Digitale camera's | 11.452 | 316 | 71% | 36 d | €231 – €375 – €530 | 27% | 6% | merk 94%, type 71% |
| Drones | 3.554 | 90 | 77% | 40 d | €104 – €173 – €358 | 30% | 22% | merk 65% (DJI 1.601) |
| Smartwatches | 10.962 | 271 | 72% | 40 d | €81 – €187 – €324 | 10% | 23% | besturingssysteem 88% |
| Samsung-telefoons | 6.992 | 266 | 63% | 26 d | €200 – €350 – €513 | 33% | 14% | model 81%, opslag 81% |
| Modeltreinen N | 4.929 | 130 | 95% | 38 d | €111 – €150 – €200 | 13% | 19% | merk 96% |
| Lego | 129.618 | 2.268 | 88% | 57 d | €13 – €250 – €433 | 27% | 30% | merk 82%, thema 58% |
| Sporthorloges *(bestaat al)* | 3.251 | 89 | 86% | 37 d | €80 – €195 – €300 | 17% | 30% | – |
| Fietscomputers *(bestaat al)* | 2.793 | 82 | 81% | 34 d | €43 – €73 – €145 | 30% | 23% | – |

**Wat dit per kandidaat betekent voor de tool:**

- **Lenzen.** Het beste profiel: duur genoeg (mediaan €300), goed
  verzendbaar, weinig nieuw (5%, dus vooral particulieren die tweedehands
  verkopen) en een scherpe modelnaam. De vatting (EF, RF, E, Z, F, M4/3)
  moet mee in de referentierij; een "50mm f/1.8" bestaat voor elke vatting.
  Past direct in het `markets.py`-patroon (merk, model, pattern,
  nieuwprijs, bron).
- **iPhone.** De meeste volume en de snelste markt. Model plus opslag
  bepalen de prijs; batterijconditie en "scherm vervangen" staan in de
  tekst. Ook handelaren en reparateurs adverteren hier (14% handelaar in
  de steekproef van Telecommunicatie). De flip-berekening moet dan ook de conditie wegen, anders is elk toestel met barst "een
  koopje". 2,7% staat als "Niet werkend" in het conditieveld: dat veld
  gebruiken als filter.
- **iPad / MacBook.** Model is bijna altijd ingevuld, maar "MacBook Pro"
  omvat vele jaargangen. Het jaartal of de chip (M1/M2/M3, Intel) moet uit de
  titel komen, zoals `title_variant()` nu Solar/Sapphire doet bij de
  horloges.
- **Nintendo Switch.** Het modelveld heeft maar een handvol waarden
  (Original, OLED, 2019 Upgrade, …). Klein en overzichtelijk: het snelste
  pad naar een werkende derde markt. Let op bundels ("+ 5 games"); die zijn
  te vangen zoals `computers.classify_title()` nu bundels en accessoires
  apart zet.
- **Digitale camera's en drones.** Als lenzen, met als aandachtspunt de
  sluitertelling of vlieguren die alleen in de tekst staan.
- **Lego.** Alleen met zoekopdrachten per thema (Technic, Star Wars,
  Creator Expert, …) blijf je onder het plafond van ~5.000 resultaten per
  zoekopdracht. Het setnummer (4–6 cijfers) is een perfecte sleutel.
  Compleetheid ("100% compleet", "zonder doos") bepaalt de prijs en staat
  alleen in de tekst.

## 7. Wat er in de code moet gebeuren

| Onderdeel | Nu | Voor een nieuwe markt |
|---|---|---|
| Crawlen, paginering, categoriefilter, `--sort newest`, 403-/paginastructuur-meldingen | categorie-onafhankelijk | niets |
| Dealscore (mediaan, 2e-hands gemiddelde, nieuwprijs) | categorie-onafhankelijk | niets |
| Biedopvraging, minimumbod, MIN_BID-regel | categorie-onafhankelijk | niets |
| Verdwijnmeting, `koopjes.db`, prijshistorie, Patronen | categorie-onafhankelijk | niets |
| `markets.py` + flipberekening (`computers.apply_computer_signals()`) | twee markten | een `Market(...)` erbij, plus een `classify_unknown()` |
| Referentiebestand per model | per markt een CSV met bron | **het echte werk**: per model een rij met patroon, nieuwprijs en bron-URL, zonder te gokken (CLAUDE.md) |
| Varianten (`title_variant()`, `VARIANT_WORDS`) | horloge-woorden | eigen woorden per markt (opslag "128GB", vatting "RF", chip "M2") |
| `site_specs()` | leest uit de zoekresultaten alleen framemateriaal en remtype | per markt andere sleutels lezen (`brandLens`, `lensMount`, `storage`, `battery health`, `model`, …): die staan al in elk zoekresultaat en maken titelherkenning deels overbodig |
| Framemaat-filter, groepset, framemateriaal, `scoring.py`, `valuation.py`, `upgrade.py`, `sleepers.py` | fiets-specifiek | blijven bij de fietsen; niet nodig voor een flipmarkt |
| `computer_scoring.json` (afdingfactor 0,875, €3 kosten) | gedeeld door beide markten | per markt meten (tab Patronen, vanaf n=20). Voor duurdere spullen (iPhone, lens) de verzendkosten per markt instellen: zoek het tarief voor verzekerd verzenden op in plaats van €3 aan te houden |

Twee verbeteringen zouden elke nieuwe markt helpen:

1. **Een generiek attribuutfilter** naast `--min-frame-height`, zoals
   `"attributes": {"condition": ["Gebruikt", "Zo goed als nieuw"]}` in
   `schedule.json`. De API ondersteunt dat server-side
   (`attributesByKey[]=condition:Gebruikt`; getest, het filter werkt). Zo
   gaat een crawl niet op aan "Niet werkend" en "Nieuw"; dat laatste is bij
   oordopjes 40% van het aanbod.
2. **Weergaven en favorieten van de advertentiepagina bewaren.** De pagina
   die de biedopvraging al ophaalt, bevat `viewCount`, `favoritedCount`,
   `since` (echte plaatsingsdatum) en `sellerType` (particulier of
   handelaar). Dat is gratis extra vraaginformatie: een advertentie met 40
   favorieten na een dag is waarschijnlijk te goedkoop. `sellerType` scheidt
   bovendien de handelaren af, zodat je kunt nagaan of die de mediaan
   vertekenen.

## 8. Hoe het gemeten is: dataverzameling en wat de bron wel en niet geeft

**Werkwijze.** Voor elk van de 36 hoofdcategorieën en elk van de 1.949
subcategorieën één verzoek aan de zoek-API (`/lrp/api/search`, dezelfde als
`--sort`/`--category` gebruiken), gesorteerd op nieuwste, met 30
advertenties. Per hoofdcategorie daarnaast 4 pagina's en een telling met het
filter Direct Kopen. Daarna 504 advertentiepagina's (14 per hoofdcategorie,
zonder betaalde Dagtoppers). In totaal ~2.650 verzoeken, één tegelijk, met
1,6–3,5 seconden pauze. Marktplaats weigerde tussendoor enkele reeksen met
HTTP 403; een tweede ronde met langere pauzes haalde die op. 37
subcategorieën ontbreken nog steeds; die staan niet in de ranglijst.

**Wat de zoek-API per categorie gratis geeft** (in de `facets` van het
antwoord, zonder alle pagina's te hoeven lezen):

- het totaal aantal advertenties, en het aantal per subcategorie;
- "Aangeboden sinds": Vandaag, Gisteren, Een week. Daaruit komen de
  instroom en de looptijd;
- Levering: Ophalen / Verzenden (samen meer dan het totaal, omdat "Ophalen
  of Verzenden" in beide telt);
- Conditie (Nieuw, Refurbished, Zo goed als nieuw, Gebruikt, Niet werkend),
  in 1.467 van de 1.720 subcategorieën;
- de categorie-eigen filtervelden met tellingen per waarde, zoals merk,
  model, opslag, vatting, bouwjaar en km-stand. Daaruit komen de "Velden"-
  percentages;
- bij Auto's ook Adverteerder (Particulier/Bedrijf).

**Wat alleen op de advertentiepagina staat** (één verzoek per advertentie,
dus alleen in een steekproef): weergaven, favorieten, echte
plaatsingsdatum, particulier of handelaar, Marktplaats-kopersbescherming,
verzendopties met prijs, de biedingen en het minimumbod.

**Uitkomsten van de pagina-steekproef (504 advertenties):**

- 78% particulier, 14% handelaar, 7% onbekend. Per hoofdcategorie loopt het
  aandeel handelaren uiteen van 0% (Kleding Heren, Sieraden, Audio) tot 77%
  (Vacatures) en 79% (Auto's). Met 14 per categorie is dat een grove
  indicatie.
- Mediaan 9–36 weergaven per dag per advertentie in goederencategorieën
  (Dieren 66 is een uitschieter). Favorieten zijn zeldzaam, meestal
  gemiddeld 0–2. Hoger bij grote spullen: motoren 6, zakelijk 9, boten 19,
  auto's 23, woningen 26, vakantie 40.
- Kopersbescherming stond aan bij 48%. Dat is meestal Direct Kopen, dus
  bij Verzenden.
- 19% van de "Vandaag"-advertenties was ouder dan 36 uur (zie §2).
- **Verkoopsnelheid is hiermee niet te meten.** Van de 504 waren er na
  gemiddeld 1,5 uur (maximaal 10 uur) maar 6 weg (410/404). Voor een
  verkoopsnelheid per categorie is de bestaande verdwijnmeting
  (`db.sweep_disappeared`, tab Patronen) over dagen tot weken de goede
  bron. De looptijd in de tabellen is een voorraadmaat (aanbod ÷
  instroom), geen verkoopduur: een advertentie verdwijnt ook als ze
  verloopt of wordt ingetrokken.

**Beperkingen en vertekeningen.**

- De mediane prijzen komen uit maximaal 30 advertenties per subcategorie
  (de nieuwste, zonder Dagtoppers). Dat is ruim genoeg voor een ordegrootte,
  niet voor een taxatie. Enkele medianen zijn door rare advertenties
  opgeblazen (Hand-tuingereedschap €838: daar staan trekkers tussen).
- "Nieuw per dag" is het weekgemiddelde op één moment, dus seizoen
  (winterjassen, ski's in september) telt mee.
- De "Velden"-percentages tellen wat de verkoper in het filterveld koos.
  Een merk dat alleen in de titel staat, telt niet mee, dus de titel-
  herkenning van de tool kan meer vinden.
- Het plafond van ~5.000 resultaten per zoekopdracht (`maxAllowedPageNumber`
  167) geldt ook hier. Een subcategorie met meer aanbod is niet in één
  crawl volledig te zien, alleen op nieuwste gesorteerd bij te houden.

**Opnieuw meten.** De scripts staan in `marktonderzoek/`. Draai ze vanuit
een lege map, zoals bij `catalog_tools/`: ze schrijven ~270 MB ruwe JSON in
de werkmap. Een volledige meting duurt ~3 uur, vooral door de beleefde
pauzes.

## Bijlage: bestanden

- `marktonderzoek_subcategorieen.csv`: alle 1.720 subcategorieën met goederen,
  gesorteerd op score. Kolommen: aanbod, nieuw per dag, looptijd,
  verzendbaar, mediaan/p25/p75, aandeel met prijs en bieden zonder prijs,
  het merkveld met vulgraad en de vijf grootste merken, conditie, en de
  beschikbare filtervelden.
- `marktonderzoek/`: de meetscripts (`collect.py`, `vip.py`, `analyze.py`,
  `score.py`, `gen.py`).
