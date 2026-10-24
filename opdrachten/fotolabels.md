# Fotolabels — ontwerp van de dataset (concept, 24-10-2026)

Doel: een eigen beeldmodel (DINOv3 bevroren + kleine koppen, zie onderaan) dat
op Marktplaats-foto's van racefietsen ziet **welke onderdelen** erop zitten en
**in welke staat** ze zijn. De labels zijn het duurste en langstlevende deel;
dit document legt vast hoe ze eruitzien vóórdat er één gezet wordt.

Status: concept. Nog niets gebouwd. Wijzigingen hierin gaan vóór het labelen.

## De vier regels die je later niet meer kunt herstellen

Bijna alles is later te veranderen (een schemaversie en een migratie), behalve
deze vier. Daarom staan ze voorop.

1. **Bewaar de foto zelf, op `$_57`, op het moment dat je hem ziet.**
   Advertenties verdwijnen; een link is na een paar weken dood. Opslaan onder
   de sha256 van het bestand (`fotos/ab/abcd....jpg`), met de oorspronkelijke
   link en datum ernaast. Elk getal behalve 14/82/83/85/86 gaf op 24-10-2026
   dezelfde grootste versie (1600 px aan de lange kant); `$_57` is de vaste.
2. **Label wat je ziet, niet wat je concludeert.** "Tanden van het voorblad:
   puntig" is een waarneming; "slijtagescore 62" of "moet vervangen" is een
   conclusie. Conclusies worden later uit de waarnemingen berekend en mogen dan
   eindeloos veranderen. Wie alleen conclusies labelt, moet alles opnieuw doen
   zodra de formule verandert.
3. **"Niet te beoordelen" is een eigen waarde, nooit hetzelfde als "goed".**
   Op een foto van de hele fiets van opzij is een cassette niet te beoordelen.
   Wordt dat "goed", dan leert het model dat elke fiets op afstand in orde is.
4. **De splitsing train/validatie/test is per advertentie, en ligt vast.**
   Foto's van dezelfde fiets in training én test laten het model veel beter
   lijken dan het is. De split volgt uit een hash van het advertentienummer
   (vast, niet willekeurig per run). De testset wordt opnieuw opgebouwd (zie
   "De testset"); de 100 advertenties uit de zip zijn daar kandidaten voor,
   hun oude labels niet. Wat in de testset zit, komt nooit in de training.

## Drie niveaus

```
advertentie  (wat de fiets is: uit tekst, eigenaar, of samengevoegd uit de foto's)
  └─ foto     (wat voor foto het is en of hij bruikbaar is)
      └─ onderdeel-op-foto  (welk onderdeel, wat het is, in welke staat — hier zit het werk)
```

### 1. Advertentie

| Veld | Waarden | Opmerking |
| --- | --- | --- |
| `item_id` | `m2123...` | sleutel; koppeling met `koopjes.db` |
| `split` | `train` / `val` / `test` | vast, zie regel 4 |
| `groepset_tekst` | zelfde boom als hieronder | wat de verkoper schrijft (`detect_groupset()`), los bewaard |
| `groepset_waar` | zelfde boom | wat het echt is, na kijken; leeg = onbekend |
| `frame_materiaal`, `remtype` | bestaande woorden uit `racefiets_jev.py` | idem: tekst en waarheid apart |

De tekst van de verkoper is een **zwak label**, geen waarheid: verkopers
vergissen zich of noemen alleen de derailleur. Daarom twee velden.

#### Herkomst: geen foto zonder advertentie

Elke foto hoort bij een bron, anders is hij later niet meer te gebruiken
(geen tekst, geen jaar, niet te splitsen). Bij het binnenhalen wordt de hele
advertentie bewaard zoals ze toen was — een **momentopname**, want de
advertentie verandert of verdwijnt:

| Veld | Waarom |
| --- | --- |
| `item_id`, `url`, `opgehaald_op` | sleutel en herkomst |
| titel, volledige omschrijving, Kenmerken (alles), prijs en prijstype | de tekstlabels en de jaar-/catalogusregel hieronder komen hieruit |
| `bouwjaar` (als bekend: tekst, `bike_link`, eigen correctie) | idem |
| alle foto-links in volgorde, plus de sha256 van elk bestand | zelfde foto in twee advertenties (doorverkoop, herplaatsing) herkennen |

Drie manieren om iets toe te voegen, alle drie met die momentopname:

1. **Link plakken** op de labelpagina (of `python fotoset.py toevoegen <url>`):
   één verzoek naar de advertentiepagina, zoals controleer (`recheck.py`):
   pagina, alle foto's op `$_57`, tekst. Zo kan de eigenaar zelf zoeken.
2. **Uit `koopjes.db`**: advertenties die een ronde al zag, met een budget per
   ronde voor de paginaverzoeken.
3. **Eigen foto's** (gekochte flips, bezichtigingen, de eigen fiets): geen
   Marktplaats-id, wel een eigen sleutel (`flip:<id>`, `eigen:defy`) en zo
   mogelijk het id van de advertentie waar de fiets vandaan kwam — dan hangen
   de echte close-ups en de advertentiefoto's aan dezelfde fiets.

Dezelfde fiets die opnieuw geplaatst wordt (zelfde foto-hashes, ander id) telt
als één fiets voor de split: anders lekt hij van training naar test.

### 2. Foto

| Veld | Waarden |
| --- | --- |
| `soort` | `fiets_heel`, `aandrijving_achter`, `aandrijving_voor`, `cockpit`, `frame_detail`, `wiel`, `schade_closeup`, `los_onderdeel`, `geen_fiets` (bon, doos, tekst), `anders` |
| `bruikbaar` | `goed` / `matig` (wazig, donker, ver weg) / `onbruikbaar` |
| `kant` | `aandrijfzijde` / `andere_zijde` / `voor` / `achter` / `boven` / `nvt` |

Eén soort per foto: de hoofdzaak. Wat er verder op staat volgt uit de
onderdelen hieronder.

### 3. Onderdeel op een foto

Eén regel per onderdeel dat je op die foto **zou kunnen** beoordelen. Vaste
lijst (uitbreiden kan, hernoemen niet):

`achterderailleur`, `voorderailleur`, `shifters`, `crankstel`, `cassette`,
`ketting`, `remmen`, `remschijf`, `velg_voor`, `velg_achter`, `band_voor`,
`band_achter`, `frame`, `voorvork`, `stuurlint`, `zadel`, `pedalen`.

Per onderdeel:

| Veld | Waarden | Opmerking |
| --- | --- | --- |
| `zichtbaar` | `helemaal` / `deels` / `klein` (te ver weg voor details) | `klein` = herkennen mag, staat niet |
| `vak` | rechthoek in pixels, **optioneel** | twee klikken in de labelpagina; maakt later uitsnijden en een detector mogelijk. Kost weinig, dus doen waar het snel gaat |
| `fabrikant` | `Shimano`, `SRAM`, `Campagnolo`, `overig`, `onbekend` | |
| `serie` | uit `GROUPSET_CATALOG` (`Dura-Ace`, `Ultegra`, `105`, `Tiagra`, ...), `onbekend` | |
| `generatie` | bijv. `6700`, `4700`; `onbekend` | **alleen uit een tabel met bron** (zie hieronder) |
| `onderdeelnummer` | bijv. `RD-6700`, alleen als het **leesbaar** is | het sterkste label dat er is |
| `staat_*` | zie de tabel per onderdeel | elk met `niet_te_beoordelen` |
| `zekerheid` | `zeker` / `waarschijnlijk` / `gok` | over dit onderdeel als geheel |

**Waarom een boom (fabrikant → serie → generatie → nummer):** elk niveau mag
los `onbekend` zijn. Een wazige Ultegra waarvan de generatie niet te zien is,
is nog steeds een goed voorbeeld voor "Ultegra tegen Tiagra". Het model leert
dan per niveau wat het kan, in plaats van dat zo'n foto weggegooid wordt.

### Identiteit: het label komt uit bewijs, niet uit het oog

Het hele punt van het model is dat het verschillen leert die een mens niet
bewust ziet — 6600 tegen 6700 aan de bouw, niet aan een opschrift. Dan kan het
label van zo'n foto **niet** uit iemands blik op die foto komen: dan leert het
model hooguit zo goed te kijken als de labeler. Het label moet van buiten de
pixels komen, en het model zoekt zelf uit waaraan het te zien is.

Let op het onderscheid: het **model** kijkt alleen naar de foto — vorm,
geometrie, details — en heeft bij het voorspellen geen tekst nodig. Het gaat
hier alleen om waar het **antwoord bij de trainingsfoto's** vandaan komt: dat
moet kloppen, anders leert het model de verkeerde vorm bij het verkeerde
antwoord. Hetzelfde geldt voor de fiets zelf: een Defy van 2010 en een van
2020 uit elkaar houden aan de geometrie leert het model van honderden
Defy-foto's waarvan het **bouwjaar uit de advertentie** bekend is (veld
`model` en `bouwjaar` bij de advertentie, ook met `bewijs`), niet van foto's
waarvan iemand het jaar heeft geschat.

Daarom heeft elk identiteitsveld (fabrikant, serie, generatie, nummer) een
`bewijs`, en voor de generatie telt `oog` niet mee bij het trainen:

| `bewijs` | Wat | Sterkte |
| --- | --- | --- |
| `in_het_echt` | de eigenaar heeft het onderdeel in handen gehad | goud |
| `nummer_hier` | onderdeelnummer leesbaar op deze foto | goud |
| `nummer_elders` | leesbaar op een andere foto van dezelfde advertentie ("FC-6750" op de crank) | sterk — maar alleen voor dát onderdeel, niet voor de hele fiets |
| `tekst_onderdeel` | verkoper noemt het onderdeel zelf ("achterderailleur Ultegra 6700") | redelijk |
| `tekst_groepset` | verkoper noemt alleen de groepset | zwak: geldt voor de onderdelen die erbij horen, met lager gewicht |
| `catalogus` | model + bouwjaar → standaardopbouw uit `reference_bike_catalog.csv` (met bron) | zwak: fietsen worden omgebouwd |
| `oog` | iemand herkent het op de foto | alleen voor fabrikant/serie, en als controle |

Het oog heeft wel een taak: **tegenspraak** melden. "Tekst zegt Ultegra, dit
is duidelijk een zwarte 105" zet het label op `spreekt_tegen` en haalt het uit
de training. Dat vangt de verkoperfouten zonder dat het oog de generatie hoeft
te raden.

Gemengde groepsets zijn gewoon: 6700-shifters met een 6600-derailleur, een
andere cassette. Daarom staat de identiteit **per onderdeel**, en loopt een
groepsetnaam uit de tekst alleen door naar onderdelen die er niet mee in
tegenspraak zijn.

Ruis in deze labels is onvermijdelijk (een verkoper die 6700 schrijft bij een
6600). Met honderden voorbeelden per generatie leert een model daar doorheen,
zolang de fouten willekeurig zijn. Daarom zijn veel zwakke labels hier meer
waard dan weinig "zekere" labels van het oog.

#### Valkuil: het model leert de verkeerde aanwijzing

6600-fietsen zijn ouder dan 6700-fietsen: ander frame, andere wielen, andere
foto's. Een model kan dan "oude fiets" leren in plaats van "6600-derailleur",
en op de testset toch hoog scoren. Drie controles, vast in de evaluatie:

- **Uitsnede:** het model krijgt alleen het `vak` van het onderdeel, niet de
  hele foto. Zakt de score daar sterk, dan keek het naar de rest.
- **Losse onderdelen:** een aparte testgroep van losse derailleurs en shifters
  uit fietsonderdelen — geen fiets, geen frame, geen jaar om op te leunen.
- **Jaar-baseline:** hoe goed raadt alleen het bouwjaar de generatie? Het model
  moet daar duidelijk boven zitten, anders heeft het niets geleerd wat het
  jaar niet al zei.

Of het "beter dan het blote oog" is, wordt zo ook meetbaar: dezelfde testfoto's
blind door de eigenaar (en door Claude) laten raden, en die score naast die van
het model zetten.

**Generaties komen uit een bestand met bron, niet uit het hoofd.** Een nieuw
bestand `reference_groupset_generations.csv` (merk, serie, generatie,
versnellingen, jaren, kenmerken om aan te herkennen, `source_url`), zoals de
andere referentiebestanden. Zonder bron geen rij — de regel uit `CLAUDE.md`
geldt hier dubbel, want een verkeerde generatie wordt duizend keer geleerd.

### Staat per onderdeel

Alle schalen zijn **waarnemingen**, met een geschreven definitie per stap en
twee of drie **ankerfoto's** per stap (echte foto's uit de set, vastgezet in de
labelpagina). Zonder ankers schuift "licht" in een maand ongemerkt op.

| Onderdeel | Kenmerk | Waarden |
| --- | --- | --- |
| ketting | `roest` | `geen` / `oppervlakkig` (oranje waas) / `zwaar` (bruin, schilferig) |
| ketting | `vuil` | `schoon` / `vuil` / `zwart_aangekoekt` |
| cassette | `tanden` | `normaal` / `licht_puntig` / `haaientand` |
| cassette | `roest` | `geen` / `oppervlakkig` / `zwaar` |
| crankstel | `tanden` | `normaal` / `licht_puntig` / `haaientand` / `tand_kapot` |
| crankstel | `roest` | idem |
| crankstel, derailleurs, shifters | `schaafplekken` | `geen` / `licht` / `duidelijk` (valschade-aanwijzing) |
| remmen | `blokjes` | `vol` / `half` / `op` (alleen als het profiel zichtbaar is) |
| remschijf | `slijtage` | `normaal` / `rand_zichtbaar` / `blauw_of_krom` |
| velg | `remvlak` | `normaal` / `hol_gesleten` (velgrem; slijtindicator weg) |
| band | `slijtage` | `nieuw` / `gebruikt` / `plat_of_vierkant` |
| band | `scheurtjes` | `geen` / `haarscheurtjes` / `diep` |
| frame, voorvork | `lak` | `geen_schade` / `krasjes` / `chips` / `diep_tot_materiaal` |
| frame, voorvork | `scheur_of_deuk` | `nee` / `vermoeden` / `ja` — plus `plek` (bovenbuis, onderbuis, trapas, liggende achtervork, staande achtervork, balhoofd, zitbuis) |
| stuurlint | `staat` | `goed` / `versleten` / `gescheurd` |

Aanvullend, voor schoonmaken: `vuil` (`schoon` / `vuil` / `zwart_aangekoekt`)
ook bij cassette, crankstel, achterderailleur (wieltjes) en frame; en
`zadel.staat` (`goed` / `slijtplek` / `gescheurd`), `band.zijwand`
(`normaal` / `verkleurd_of_uitgedroogd`).

Bewust **niet** gelabeld, omdat het op een foto niet te zien is: kettingrek,
lagerspeling, de staat van kabels in het frame, en de echte leeftijd. Liever
een gat dan een gok die eruitziet als een meting.

Reflecties: een glimstreep die op een kras lijkt is `geen_schade` met
`zekerheid: waarschijnlijk`, niet `krasjes`. Juist die foto's zijn goud als
tegenvoorbeeld; markeer ze met de vlag `lastig`.

## Van waarneming naar actie: vervangen, schoonmaken, niets

Het doel van de eigenaar (alleen racefietsen): per fiets zien **wat er
vervangen en wat er schoongemaakt moet worden**. Dat is een conclusie, dus geen
label (regel 2), maar een tabel die de waarnemingen omzet, in
`fotolabels_acties.json` — met de hand aan te passen, en elke wijziging geldt
meteen voor alle gelabelde foto's zonder iets opnieuw te labelen:

| Waarneming | Actie |
| --- | --- |
| ketting `roest: zwaar` | ketting vervangen |
| ketting `roest: oppervlakkig` of `vuil: zwart_aangekoekt` | aandrijving schoonmaken |
| cassette `tanden: haaientand` | cassette + ketting vervangen |
| crankstel `tanden: haaientand` of `tand_kapot` | blad vervangen (+ ketting) |
| band `slijtage: plat_of_vierkant`, `scheurtjes: diep` of `zijwand: verkleurd_of_uitgedroogd` | band vervangen |
| stuurlint `versleten` / `gescheurd` | stuurlint vervangen |
| remmen `blokjes: op` | remblokjes vervangen |
| velg `remvlak: hol_gesleten` | velg/wiel vervangen |
| frame `scheur_of_deuk: ja` of `vermoeden` | **niet kopen zonder bezichtiging** |

Dit is een eerste voorzet; de eigenaar bepaalt de regels. Een prijs per actie
komt uit de echte prijzen van de klussenlijsten op `/flips`, niet uit het
hoofd. Het resultaat heet `opknaplijst` / `opknapkosten` en is iets anders dan
`deal_score` en de waardescore.

## Het schema zelf is een bestand

De lijsten hierboven (onderdelen, kenmerken, waarden, definities, ankerfoto's)
staan in `fotolabels_schema.json`, niet in de code. De labelpagina leest dat
bestand: een waarde of kenmerk erbij is één regel erbij. Hernoemen of samenvoegen
van een bestaande waarde gaat via een `hernoem`-lijst in hetzelfde bestand, zodat
oude labels mee verhuizen in plaats van te verweesen; verwijderen kan niet
(alleen "niet meer tonen"), zodat geen werk verloren gaat.

## Wie wat zette: bron en controle

Elk label (elk veld, niet per foto) heeft:

| Veld | Waarden |
| --- | --- |
| `bron` | `eigenaar` / `claude` / `tekst` (uit de advertentie) / `model` (voorspelling) |
| `gecontroleerd` | `ja` als de eigenaar het heeft gezien en laten staan of aangepast |
| `schema` | versie van dit document (begint bij 1) |
| `tijd` | wanneer |
| `notitie` | vrij |

Wijzigingen overschrijven niets: elke wijziging is een nieuwe regel, de
nieuwste geldt. Zo is altijd te zien wat Claude zei en wat de eigenaar ervan
maakte — en hoe vaak die het oneens waren, wat precies de betrouwbaarheid van
Claude-labels meet.

Een veld is **geverifieerd** zodra de eigenaar het heeft aangepast of met
"klopt" heeft bevestigd; dat is het enige wat `gecontroleerd: ja` zet. Een
latere wijziging door Claude of het model haalt die status er niet af — die
komt dan als voorstel in de wachtrij *oneens met geverifieerd*.

**Trainen:** standaard op alles behalve `bron: model`; gewicht hoger voor
`gecontroleerd: ja`. **Testen:** alleen op `gecontroleerd: ja` uit de testset.

## Opslag

- `fotoset/` naast de repo (niet in git: auteursrecht van de verkopers en
  ~300 KB per foto): `fotos/` op hash, `kenmerken/` (de DINOv3-uitvoer).
- `fotoset/labels.db` (SQLite, stdlib): tabellen `advertentie`, `foto`,
  `label` (één rij per veld per wijziging, zie hierboven). Los van
  `koopjes.db`: andere levensduur, en zo kan een test de rondes nooit raken.
- Een export `labels.jsonl` (alleen labels, geen foto's) kan in git, zoals
  `reference_prices.csv` met `git add -f`: daar zit het echte werk in.

## De labelpagina (`/fotolabels` in `dashboard.py --serve`)

- Per advertentie alle foto's, één groot met **zoom tot 100%** (de details
  zijn het punt), de rest als strook; de titel en omschrijving ernaast.
- Rechts het formulier van het gekozen onderdeel, met de ankerfoto's van de
  gekozen stap ernaast ter vergelijking.
- Sneltoetsen voor de vaste lijsten; vak trekken met twee klikken.
- Wachtrijen: *nog niet gecontroleerd*, *Claude en tekst oneens*, *model en
  label oneens* (na de eerste training), *vlag lastig*, *testset*.
- Knop "klopt" zet alle Claude-labels van een foto op gecontroleerd zonder te
  typen; aanpassen kan per veld.
- Lokaal, 127.0.0.1, met het bestaande token, zoals de andere pagina's.

## Model (ter oriëntatie; komt na de labels)

DINOv3 ViT-L/16 (32 GB RAM: H+/16 kan ook) bevroren, één keer over alle foto's
op ~768-1024 px; de kenmerken per beeldvlak bewaard (fp16). Daarop kleine
koppen per veld (attention-probe over de vlakken), te trainen op de laptop in
minuten. Per advertentie samenvoegen over alle foto's. Fine-tunen van de
laatste blokken pas als de probe niet meer beter wordt, op Kaggle.
Snelheid gemeten op 4 cores (24-10-2026, willekeurige gewichten, zelfde
architectuur): ViT-B/16 0,5 s per foto op 448 px, 2,3 s op 768 px.

## Hoeveel foto's

Niet het totaal telt, maar het aantal voorbeelden **per waarde, waar het
onderdeel te beoordelen is**. Richtgetallen voor een bevroren backbone met een
kleine kop (vuistregels, geen meting — de leercurve hieronder beslist):

| Per waarde | Wat je dan krijgt |
| --- | --- |
| ~50 | het werkt, maar wankel |
| 200-500 | goed; hier vlakt het meestal af |
| > 1.000 | alleen nog winst bij de lastige gevallen |

Begin met **~300-500 advertenties (~2.000-3.000 bruikbare foto's)**. De gewone
waarden (`normaal`, `geen`) zijn dan ruim gehaald; de zeldzame (`haaientand`,
`zwaar` roest, `scheur`) niet — die worden gericht gezocht: losse cassettes en
kettingbladen uit fietsonderdelen ("versleten", "aan vervanging toe"), en
fietsen die de tekst al als opknapper beschrijven.

**Meet het, raad het niet:** train op 25%, 50% en 100% van de set en kijk op
de testset of het nog stijgt. Stijgt het tussen 50 en 100% nog duidelijk, dan
helpen meer foto's; zo niet, dan zitten de fouten in de labels of het model.

**Ook de testset moet genoeg hebben:** met 100 advertenties zitten er per
zeldzame waarde misschien een handvol in, en dan zegt de score op die waarde
niets. Streef naar ≥ 20-30 per waarde in de test; vul de testset daarvoor
gericht aan (vóór het trainen, en daarna niet meer).

## De testset: hoe hij te vertrouwen wordt

De oude set van 100 advertenties is door Claude gelabeld en gerankt, zonder
vastgelegd schema of controle. Die labels tellen als `bron: claude`,
ongecontroleerd — bruikbaar als voorstel, niet als waarheid. Een testset is
alleen iets waard als het antwoord er **onafhankelijk** van het model in komt.
Drie soorten bewijs, van sterk naar zwak, en bij elk label staat welke:

| Bewijs | Waar het vandaan komt | Waarde |
| --- | --- | --- |
| `in_het_echt` | de eigenaar zag het onderdeel zelf: de eigen fiets, gekochte flips (`/flips`), bezichtigingen | goud |
| `leesbaar` | onderdeelnummer of serie op de foto te lezen, of de verkoper noemt het en de foto spreekt het niet tegen | sterk |
| `oordeel` | wat op de foto te zien is, beoordeeld met de ankerfoto's | gewoon |

Werkwijze:

1. **Blind labelen.** Voor de testset ziet de eigenaar Claude's labels níet
   vooraf (labelpagina in testmodus, geen "klopt"-knop). Wie eerst het antwoord
   ziet, klikt het meestal goed — dat meet dan niets.
2. **Twee keer, los van elkaar.** Claude labelt dezelfde foto's apart. Waar ze
   het eens zijn: vastgezet. Waar niet: de eigenaar beslist met de ankerfoto's
   ernaast, en de foto krijgt de vlag `lastig`. Het percentage overeenstemming
   is meteen de bovengrens die een model op die waarde redelijkerwijs haalt.
3. **Eerst ijken, dan tellen.** De eerste ~20 foto's samen doorlopen en waar
   het schuurt de definitie in `fotolabels_schema.json` aanscherpen. Die 20
   gaan daarna opnieuw blind, en pas dan begint de echte testset.
4. **Goud uit de eigen handen.** Elke fiets die de eigenaar koopt of bezichtigt:
   de advertentiefoto's bewaren én zelf close-ups maken van aandrijving,
   banden, stuurlint en frame, met de echte staat erbij. Dat is de enige plek
   waar de waarheid niet van een foto komt — ook de eigen Defy (Ultegra 6700,
   `fiets_master.md`) hoort erin.
5. **Gericht vullen.** Per waarde ≥ 20-30 in de test (zie "Hoeveel foto's");
   wat ontbreekt gericht zoeken vóór het trainen. Daarna gaat de testset op slot.

Tijd: met sneltoetsen ruwweg 20-40 s per foto, dus 1.000 testfoto's is een
werkdag of twee — eenmalig, en het is wat alle latere getallen betekenis geeft.

## Volgorde

1. Dit document goedkeuren / aanpassen. **Daarna** pas labelen.
2. `reference_groupset_generations.csv` met bronnen (eerst de generaties die
   in de testset voorkomen).
3. Foto's van de 100 testadvertenties binnenhalen op `$_57` (uit de zip, en
   waar nodig één paginaverzoek per advertentie, met `--delay`).
4. Labelpagina; Claude doet een eerste ronde, de eigenaar controleert.
5. Pas daarna de trainingsset uitbreiden en het model.

## Open vragen voor de eigenaar

- Wat zit er in de zip: foto's, links, of alleen advertentienummers met een
  rangorde? En waarop is gerankt?
- ~~Fietscomputers en horloges?~~ Nee: alleen racefietsen (eigenaar, 24-10-2026).
- Mist er een kenmerk dat jij bij een bezichtiging altijd checkt?
