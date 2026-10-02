# Prijsonderzoek onderdelen Cube Peloton Pro (02-10-2026)

Voor de opknapbeurt van de Cube Peloton Pro, maat 62 (`/flips`). Opdracht:
`opdrachten/goedkoopste_onderdelen.md`, deel A. Alle prijzen hieronder zijn
op **02-10-2026** op de productpagina zelf gelezen (prijs, voorraad), tenzij
er *niet zelf gecontroleerd* staat. Inlezen als aanbiedingen op `/flips`:

```
python flips.py bijwerken flips_import/cube_aanbiedingen.json
```

Daarna staat bij elk onderdeel onder *Aanbiedingen (n)* wat hieronder staat,
met "kies deze".

## Eerst: twee dingen nakijken op de fiets

**1. Welke achterderailleur: SS (korte kooi) of GS (middellange kooi)?** Op
de lijst staat een cassette **11-32**. Volgens Shimano zelf kan een
RD-5701-**SS** bij 2×10 een grootste tandwiel van **25 tot 30 tanden** aan,
en een RD-5701-**GS** van **27 tot 32** ([Shimano compatibiliteitstabel
2014-2015, p. 13, stand 7 januari 2015](https://productinfo.shimano.com/pdfs/product/archive/2014-2015_Compatibility_v010_en.pdf)).
Een 11-32 hoort dus alleen op een GS. Het staat op de kooi van de
derailleur (of: korte kooi ≈ 5 cm tussen de wieltjes, GS duidelijk langer).
Een verkoopadvertentie van een andere Cube Peloton Pro noemt een
RD-5701GS ([cyclechat, april 2026](https://www.cyclechat.net/threads/sold-cube-peloton-pro-road-bike-shimano-105.310524/)),
maar daar was meer vervangen; kijk het zelf na.
**Is het een SS: neem de CS-HG500-10 in 12-28** (zelfde winkels, zelfde of
lagere prijs). Een koper merkt een derailleur die op het grootste tandwiel
tegen de cassette loopt.

**2. Welke crank, en moet het grote blad echt vervangen?** Het blad op de
lijst is 50T met 110 mm steekcirkel (BCD): dat past op een **FC-5750
(compact, 50-34)** — Mantel zet bij het originele 50T-blad "BCD 110 mm, 5
bouten, compact" ([Mantel](https://www.mantel.com/en/shimano-105-5750-chainring)).
Meten: de afstand tussen de middens van twee naast elkaar liggende
kettingbladbouten × 1,701 is de BCD bij 5 armen: ±64,7 mm → 110, ±76,4 mm →
130 (dan is het een FC-5700 met 52/53-39, en past een 50T niet).
Vervangen alleen als het blad versleten is: tanden die als haaienvinnen
naar één kant overhellen, scherpe of omgebogen punten, of — het zekerst —
een **nieuwe** ketting die op het grote blad onder kracht overslaat. Is dat
niet zo, dan kan het oude blad blijven en scheelt het €30.

## Per onderdeel

Verzendkosten per winkel (gecontroleerd 02-10-2026):

| Winkel | Verzending naar NL | Gratis vanaf | Bron |
| --- | --- | --- | --- |
| FuturumShop | €3,95 | €49 | [bezorgen en levertijd](https://www.futurumshop.nl/klantenservice/bezorgen-en-levertijd) |
| Mantel | €3,99 (PostNL/Budbee), afhalen in een Superstore gratis | €49 | [bezorgen & afhalen](https://www.mantel.com/klantenservice/?category=178) |
| bike-components (DE) | €6,99 | — | [shipping](https://www.bike-components.de/en/service/shipping/) |
| Velondo | €9,90 (DHL, 2-3 werkdagen) | — | [verzending](https://www.velondo.nl/verzending.html) |

bike-components toont zijn prijzen met Duitse btw (19%). Bij een levering in
Nederland rekent hij Nederlandse btw (21%): reken op ~1,7% meer in de
winkelwagen. Bike24 en Decathlon weigerden geautomatiseerde verzoeken (HTTP
403); hun prijzen hieronder komen uit je eigen lijst van 29-09-2026.

### Cassette Shimano Tiagra CS-HG500-10 (10-speed)

| Winkel | Product | Prijs | Voorraad | Link |
| --- | --- | --- | --- | --- |
| bike-components | CS-HG500-10, 11-32 | €23,99 (12-28: €20,99) | op voorraad | [link](https://www.bike-components.de/en/Shimano/CS-HG500-10-10-speed-Cassette-p43864/) |
| Bike24 | CS-HG500-10 11-32T | €22,99 | — *niet zelf gecontroleerd* (jouw lijst 29-09) | [link](https://www.bike24.nl/producten/125069) |
| Mantel | HG500 10 Speed, 11/32 | €29,95 (12/28: €27,95) | op voorraad | [link](https://www.mantel.com/shimano-hg500-cassette) |
| FuturumShop | Tiagra CS-HG500 10 Speed, 11-32T | €29,95 (alle maten) | op voorraad, morgen in huis | [link](https://www.futurumshop.nl/shimano-tiagra-cs-hg500-cassette-10-speed.phtml) |

### Derailleurwieltjes (set, 11 tanden)

| Winkel | Product | Prijs | Voorraad | Link |
| --- | --- | --- | --- | --- |
| bike-components | Shimano 9-/10-speed Derailleur Pulleys - 1 Pair (universal, 11T; past op RD-5701 volgens de winkel) | €4,99 | op voorraad | [link](https://www.bike-components.de/en/Shimano/9-10-speed-Derailleur-Pulleys-1-Pair-p1370/) |
| Bike24 | set 5700 | €5,07 | *niet zelf gecontroleerd* | [link](https://www.bike24.nl/producten/252059) |
| Mantel | Shimano 105 5700 8, 9, 10-speed Derailleurwieltjes | €10,95 | op voorraad | [link](https://www.mantel.com/shimano-derailleurwieltjes-deore) |
| FuturumShop | Derailleurwieltjes 5700 Race en MTB | €11,95 | op voorraad | [link](https://www.futurumshop.nl/shimano-derailleurwieltjes-5700-race-en-mtb.phtml) |
| 12GoBiking | Shimano 105 RD-5700 Derailleurwieltjes | €13,99 | op voorraad | [link](https://www.12gobiking.nl/shimano-105-rd-5700-derailleurwieltjes) |

### Banden: 2× Continental Ultra Sport III 700×25C vouwband (25-622)

| Winkel | Prijs per stuk | Voor 2 | Voorraad | Link |
| --- | --- | --- | --- | --- |
| Velondo | €14,78 | €29,56 + €9,90 verzending | op voorraad | [link](https://www.velondo.nl/continental-ultra-sport-3-e25-25-622-vouwband-zwart.html) |
| bike-components | €16,99 | €33,98 | op voorraad | [link](https://www.bike-components.de/en/Continental/Ultra-Sport-III-28-Folding-Tyre-p74503/) |
| Bike24 | €17,38 | €34,76 | *niet zelf gecontroleerd* | [link](https://www.bike24.nl/producten/359714) |
| Mantel | €19,95 | €39,90 | op voorraad (artikel 0150457) | [link](https://www.mantel.com/continental-ultra-sport-iii-racefiets-band) |
| FuturumShop | €20,95 | €41,90 | op voorraad | [link](https://www.futurumshop.nl/continental-ultra-sport-iii-racefiets-band-zwart.phtml) |

Een set van 2 banden + 2 binnenbanden bij bike-components (€40,99) was
uitverkocht.

### Remrubbers Shimano R55C4 (inserts)

Voor alleen achter is **1 paar** genoeg.

| Winkel | Product | Prijs | Voorraad | Link |
| --- | --- | --- | --- | --- |
| bike-components | R55C4 Brake Pads - 2 Pairs | €5,99 | op voorraad | [link](https://www.bike-components.de/en/Shimano/R55C4-Brake-Pads-for-Dura-Ace-Ultegra-105-2-Pairs-p34057/) |
| Bike24 | 2 paar | €6,09 | *niet zelf gecontroleerd* | [link](https://www.bike24.nl/producten/23208) |
| Mantel | R55C4 Remblokjes, 1 paar (Y8L298060) / 2 paar | €7,95 / €11,90 | op voorraad | [link](https://www.mantel.com/shimano-r55c4-remblokken) |
| 12GoBiking | R55C4 Remrubbers, 1 of 2 paar | €7,99–€15,99 | op voorraad | [link](https://www.12gobiking.nl/shimano-r55c4-remrubbers) |
| FuturumShop | R55C4 Remblokken Inschuif (2 paar) | €12,95 (was €10,95 op je lijst) | op voorraad | [link](https://www.futurumshop.nl/shimano-r55c4-remblokken-inschuif-2-paar.phtml) |

### Ketting KMC X10 (114 schakels, met missing link)

| Winkel | Uitvoering | Prijs | Voorraad | Link |
| --- | --- | --- | --- | --- |
| bike-components | grijs | €15,99 | op voorraad | [link](https://www.bike-components.de/en/KMC/X10-10-speed-Chain-p68898/) |
| Bike24 | zilver/zwart | €17,28 | *niet zelf gecontroleerd* | [link](https://www.bike24.nl/producten/7753) |
| Mantel | zilver | €19,95 | op voorraad | [link](https://www.mantel.com/kmc-x1073-10s-2019-ketting) |
| 12GoBiking | zilver | €19,99 | op voorraad | [link](https://www.12gobiking.nl/kmc-ketting-x10-zilver) |
| FuturumShop | grijs | €22,95 | op voorraad | [link](https://www.futurumshop.nl/kmc-x10-fietsketting-10-speed-grijs.phtml) |
| AliExpress | KMC Official Store | ±€13 *schatting* + invoerrecht (zie onder) | — | zoek in de app op "KMC X10" in de KMC Official Store |

Je lijst ging uit van "in NL €31–41"; dat klopt niet meer: in Nederland is
hij ±€20, en bij bike-components €16.

### Kettingblad 50T, 110 mm BCD, 5 armen (alleen als het oude versleten is)

| Optie | Prijs | Levertijd | Risico | Link |
| --- | --- | --- | --- | --- |
| Origineel Shimano 105 FC-5750 50T | — | **overal uitverkocht** (FuturumShop, Mantel, 12GoBiking) | — | [FuturumShop](https://www.futurumshop.nl/shimano-105-fc-5750-compact-kettingblad-zilver-10-speed-50.phtml), [Mantel](https://www.mantel.com/en/shimano-105-5750-chainring) |
| SRAM Kettingblad Compact Buiten 10-speed 110 mm 50T (voor 50×34) | €31,95 | op voorraad, morgen in huis | laag: merkblad met schakelhulpen voor 10-speed | [FuturumShop](https://www.futurumshop.nl/sram-kettingblad-compact-buiten-10-speed-110-mm-50t-aluminium-zwart.phtml) |
| Stronglight CT2 50T 110 | €69,99 | op voorraad | laag, maar te duur voor een flip | [bike-components](https://www.bike-components.de/en/Stronglight/CT2-Road-Chainring-10-11-speed-5-Arm-110-mm-BCD-p24706/) |
| GOLDIX 50-34T 110BCD (AliExpress, Stone's Store) | vraag ik aan jou (geen link) + invoerrecht | 1-3 weken | zie onder | — |
| Niets vervangen | €0 | — | alleen als het blad niet versleten is (zie boven) | — |

Over de GOLDIX, op de tekst die je plakte:
- **Rond of ovaal?** De tekst zegt eerst "dubbele elliptische
  kettingbladgroep" en daarna "Vorm: Rond". Dat is tegenstrijdig; de
  automatische vertaling van "chainring set" kan "elliptisch" zijn. Zie je op
  de foto's een ronde rand, dan is het rond. Een ovaal blad schakelt anders,
  en een koper merkt dat bij een proefrit.
- Het is een **set van twee** (50 én 34): je hebt alleen een 50 nodig, tenzij
  het 34-blad ook versleten is. Vervang je alleen het grote, dan blijft het
  originele 34-blad, en dat werkt het best met een blad dat bij hetzelfde
  schakelsysteem hoort.
- "9/10/11-speed" en "3 mm dik" op één blad: een no-name blad heeft zelden
  goed uitgelijnde schakelpinnen en ramps zoals Shimano of SRAM. Het
  schakelt naar het grote blad dan trager of rammelt. Voor een fiets die je
  verkoopt is dat het risico niet waard.
- **Advies**: eerst nakijken of vervangen nodig is. Zo ja: het SRAM-blad
  (€31,95, zeker passend en goed schakelend). De GOLDIX alleen als hij
  duidelijk rond is én minder dan ±€15 kost met invoerrecht erbij.

### Stuurlint

| Winkel | Product | Prijs | Link |
| --- | --- | --- | --- |
| FuturumShop | BBB RaceRibbon BHT-01 zwart | €10,95, op voorraad | [link](https://www.futurumshop.nl/bbb-raceribbon-bht-01-stuurlint-zwart.phtml) |
| AliExpress | RockBros / West Biking | ±€5 *schatting* + invoerrecht | zoek in de app op "RockBros bar tape" |

### Binnenbanden (2×, presta, voor 25 mm)

| Winkel | Product | Prijs | Link |
| --- | --- | --- | --- |
| bike-components | Continental Race 28, 2 stuks, 20-25 mm, ventiel 60 mm | €7,99 (42 mm uitverkocht) | [link](https://www.bike-components.de/en/Continental/Race-28-Inner-Tube-2-pieces-p78334/) |
| Decathlon | 2× presta (jouw lijst) | €7,98, click & collect gratis | *niet zelf gecontroleerd* (Decathlon weigert geautomatiseerde verzoeken) |
| FuturumShop | Hutchinson Presta 700x25/30, 48 mm | €5,99 per stuk (€11,98 voor 2) | [link](https://www.futurumshop.nl/hutchinson-presta-binnenband-700x25-30.phtml) |

### Gereedschap (investering): kettingslijtagemeter

| Winkel | Product | Prijs | Link |
| --- | --- | --- | --- |
| bike-components | BBB ChainChecker BTL-125 | €7,99, op voorraad | [link](https://www.bike-components.de/en/BBB/ChainChecker-BTL-125-Chain-Checker-p61475/) |
| bike-components | KMC Chain Checker 10,000km+ | €12,99, op voorraad | [link](https://www.bike-components.de/en/KMC/Chain-Checker-10-000km-Chain-Wear-Gauge-p220920/) |
| AliExpress | — | ±€2 *schatting* + invoerrecht | — |

**Niet nagezocht** (de schattingen op je lijst blijven staan): titanium
boutjes (optioneel, voegt voor de verkoop niets toe), framebescherming,
schroefborg, en de spullen van de Action/Kruidvat/bouwmarkt (wasbenzine,
IPA, autowas, microvezeldoeken, krasverwijderaar, magic sponzen, lakstift,
nagellak). Ook niet op Marktplaats gekeken: geen verzoeken naar Marktplaats
vanuit deze sessie.

## AliExpress: nog een deal?

- **Btw**: bij een bestelling tot €150 betaal je de btw al bij het
  afrekenen (IOSS); aan de deur komt er geen btw bij
  ([Douane](https://www.douane.nl/onderwerpen/online-shoppen-en-pakketpost/shoppen-bij-een-buitenlandse-webwinkel/extra-kosten-bij-bestellen/)).
- **Invoerrecht — nieuw sinds 1 juli 2026**: de vrijstelling voor zendingen
  tot €150 is weg. Er geldt **€3 per productcategorie** in de zending (5
  T-shirts = €3, een T-shirt en een horloge = €6), tijdelijk tot 1 juli 2028
  ([Europese Commissie, 8 juni 2026](https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en);
  [Douane](https://www.douane.nl/onderwerpen/online-shoppen-en-pakketpost/shoppen-bij-een-buitenlandse-webwinkel/extra-kosten-bij-bestellen/)).
  De verkoper of AliExpress betaalt het aan de douane, maar volgens de Douane
  "is het mogelijk dat webshops deze kosten bij u in rekening brengen".
  Fietsonderdelen samen zijn waarschijnlijk één categorie; een ketting en
  gereedschap kunnen aparte categorieën zijn. Wat AliExpress precies rekent,
  zie je pas bij het afrekenen in de app. Daarnaast is er een Nederlandse
  afhandelingsheffing van €2 per product aangekondigd
  ([Kassa](https://www.bnnvara.nl/kassa/artikelen/in-2026-worden-alle-producten-van-buiten-de-eu-3-of-zelfs-5-euro-duurder));
  niet nagegaan of die al geldt.
- **Levertijd**: 1-3 weken (schatting uit je lijst, niet gecontroleerd). Met
  een ketting en een kettingblad die op AliExpress wachten, kan de fiets niet
  af en niet te koop.
- **Namaak**: niet te controleren van hieruit (AliExpress laat geen
  geautomatiseerde bezoekers toe). Een ketting die slecht schakelt of snel
  rekt merkt een koper.
- **Terugsturen**: niet nagezocht.

**Per onderdeel**: de ketting is in Nederland €20 en bij bike-components €16
— met €3 invoerrecht en 1-3 weken wachten is AliExpress (±€13) **geen
voordeel meer**. Het kettingblad: zie boven. Stuurlint (±€5 + €3) tegen
€10,95: scheelt een paar euro, kies wat je wilt. Kleine dingen van €2
(kettingmeter, framebescherming, schroefborg) worden met €3 invoerrecht meer
dan dubbel zo duur: neem de kettingmeter mee in een bestelling hier.

## Drie mandjes

Zonder kettingblad (eerst nakijken, zie boven) en zonder de Action-spullen.
Ter vergelijking: dezelfde regels op je lijst — cassette 29,95 + wieltjes
11,95 + banden 41,90 + remblokken 10,95 + ketting 13 + stuurlint 5 +
binnenbanden 7,98 — kostten **€120,73**, met de ketting en het stuurlint als
AliExpress-schatting zonder het nieuwe invoerrecht.

**1. Goedkoopst — één bestelling bij bike-components, 1-3 werkdagen:**
cassette 11-32 €23,99 + wieltjes €4,99 + 2 banden €33,98 + remrubbers (2
paar) €5,99 + ketting €15,99 + 2 binnenbanden €7,99 = €92,93 + €6,99
verzending = €99,92, plus ±€1,60 voor de Nederlandse btw: **±€101,50**. Met
het stuurlint los (AliExpress ±€8 met invoerrecht, of BBB €10,95 bij
FuturumShop) **±€110–112: ±€8–11 minder dan je lijst, en zonder op
AliExpress te wachten.** Neem de kettingmeter (€7,99) mee in dezelfde
bestelling: geen extra verzending.

**2. Snelst — Mantel + FuturumShop, morgen in huis, gratis verzending:**
Mantel: cassette €29,95 + wieltjes €10,95 + 2 banden €39,90 + remrubbers 1
paar €7,95 + ketting €19,95 = €108,70 (gratis vanaf €49; ophalen in een
Superstore kan ook). FuturumShop: stuurlint €10,95 + 2 binnenbanden €11,98 =
€22,93 + €3,95 verzending = €26,88 (met het kettingblad erbij €54,88 en
gratis verzending). Samen **€135,58** zonder kettingblad, €163,58 met.

**3. Zo min mogelijk bestellingen — alles bij FuturumShop, morgen in huis:**
cassette €29,95 + wieltjes €11,95 + 2 banden €41,90 + remrubbers 2 paar
€12,95 + ketting €22,95 + stuurlint €10,95 + 2 binnenbanden €11,98 =
**€142,63**, gratis verzending; met het SRAM-blad €174,58.

**Advies voor deze flip**: mandje 1 (bike-components) — het goedkoopst, in
een paar dagen binnen, en geen gedoe met invoerrecht. Haast? Mandje 2.
Kijk vóór het bestellen de derailleurkooi na (11-32 of 12-28) en of het
kettingblad echt op is.
