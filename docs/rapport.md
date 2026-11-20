# Het rapport per zoekopdracht

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

Elke ronde schrijft per zoekopdracht een `racefiets_report*.html` (zie
[rondes.md](rondes.md)); met de hand doet `python racefiets_jev.py --query
... ` hetzelfde (zie [zoeken.md](zoeken.md)). Open het in een browser, of via
`/start` → *bestanden*. Het rapport is gesorteerd op de **dealscore**: de beste
deal staat bovenaan. De tabs bovenin filteren (Nieuw / Koopjes / Topdeals /
Bieden / Prijsverlaging / ...); de tabs ernaast tonen de slapers, de
biedadvertenties, de upgrades en je eigen fiets.

Het rapport heeft geen knoppen en toont alleen die ene ronde; voor markeren en
bieden zijn de live pagina's er ([live.md](live.md)).

## Dealscore

Elke advertentie krijgt één score van 0-100 die elk prijssignaal combineert
dat het script ervoor heeft, zodat je de losse kolommen niet zelf hoeft te
wegen. De consoletabel en het HTML-rapport zijn er allebei op gesorteerd (beste
eerst), het rapport heeft een sorteerbare kolom `Score` met een label
(Topdeal / Goede deal / Redelijk / Aan de prijs / Duur) en een filtertab
`Topdeals`, en met de muis op een score zie je precies welke signalen hem
maakten. `--min-score 70` laat alles onder die score weg uit het rapport.

Drie prijssignalen, elk de vraagprijs tegen een maatstaf, zo geschaald dat
precies op de maatstaf 50 scoort:

| Signaal | Maatstaf | Gewicht |
| --- | --- | --- |
| % van de mediaan | de mediane prijs van alles wat deze zoekopdracht vond | 1 |
| % van het 2e-hands gemiddelde | wat dit model in je eigen eerdere runs vroeg (vanaf 2 waarnemingen) | 2 |
| % van de nieuwprijs | wat het model nieuw kostte, uit `reference_prices.csv` | 0,75 |

Het 2e-hands gemiddelde weegt het zwaarst omdat het de eerlijkste maatstaf is:
wat dit specifieke model echt vraagt, zelf waargenomen. De nieuwprijs weegt het
lichtst — bij alles wat ouder is, ligt elke advertentie er ver onder, dus hij
onderscheidt een goede deal nauwelijks van een slechte.

Alleen signalen die er echt zijn tellen, en de gewichten worden daarover
herverdeeld, dus een advertentie zonder referentiegegevens wordt gescoord op
wat bekend is in plaats van bestraft voor de lege kolommen. Een score kan dan
op één signaal rusten; daarom komt elke score met de lijst signalen erachter.
Bovenop het gemiddelde komen twee bonussen: tot +10 voor een prijsverlaging
(naar hoe groot die was) en +8 voor een referentiematch met
`better_than_baseline`.

Wat de score met opzet niet doet: hij zegt niets over staat, compleetheid of
hoe ver de verkoper woont — het is een prijssignaal, geen oordeel. Alles op of
boven 1,7× de mediaan scoort 0, zodat hij "duur" niet tegen "absurd"
rangschikt. En de prijs van een biedadvertentie is waar het bieden nu staat,
niet waarvoor hij weggaat, dus zijn score is een bovengrens — de uitsplitsing
zegt dat bij die advertenties. De code: `dealscore.py`.

## Slapers — advertenties waarvan de tekst niets over de fiets zegt

De dealscore heeft een prijs nodig en, om iets te zeggen, een herkend model.
Sommige van de beste koopjes hebben geen van beide. Het geval waar dit op
gebouwd is: een Cannondale CAAD10 (23-09-2026) met als titel "Heren
racefiets", als omschrijving "Moet weg wegens verhuizing!", merkveld "Overige
merken", bieden zonder minimum — twee uur na plaatsing weg voor een bod van
€45. Niets in de tekst zei Cannondale; de foto's wel. Wie op merk zoekt vindt
zo'n advertentie niet, en een verkoper die vijf woorden schrijft, wacht niet op
de hoogste prijs.

`sleepers.py` zoekt precies dat, met alleen wat de zoekresultaten al bevatten
(geen extra verzoeken aan Marktplaats):

| Signaal | Punten |
| --- | --- |
| titel van alleen algemene woorden — soort, geslacht, maat, materiaal, kleur, staat ("Heren racefiets", "Racefiets 56cm") | 35, **vereist** |
| omschrijving van 15 woorden of minder, of Marktplaats' eigen vlag `thinContent` | 20 |
| een zinsnede die zegt dat hij weg moet: "moet weg", verhuizing, opruimen, zsm, weg=weg, plaatsgebrek, nalatenschap, … | 20 |
| een biedadvertentie waarop nog niemand bood, of een vraagprijs op of onder 60% van de mediaan van de zoekopdracht | 15 |
| deze run voor het eerst gezien | 10 |

Vanaf 70 punten is een advertentie een **slaper**. Helemaal uitgesloten: een
titel met een woord buiten de lijst algemene woorden (een merk, een groepset,
een modelnaam), een omschrijving die een merk noemt (de merken in
`reference_bike_catalog.csv` plus een korte lijst in `sleepers.py`), en een
advertentie die Marktplaats als gereserveerd markeert. Een lopende FAST_BID
krijgt geen prijspunten: zijn prijs is het bieden tot nu toe. Op een crawl van
240 racefietsen (8 pagina's, nieuwste eerst, 23-09-2026) kwamen 13 titels door
de test op algemene woorden, noemden 8 daarvan een merk in de omschrijving, en
werd één advertentie een slaper.

Het rapport heeft een tab **Slapers** met een kaart per advertentie — de
foto's (tot drie, zo groot als de zoekresultaten ze geven), prijs, plaats, de
redenen en de omschrijving — de console print een blok `SLAPERS` na het
bied-overzicht, en `overzicht.html` noemt de nieuwe van deze run. Dit is geen
taxatie en geen dealscore: het zegt alleen "kijk naar de foto's". Snelheid
telt bij deze, en bieden blijft iets wat je zelf doet.

De rapport-CSV (`--output`) krijgt vijf kolommen achteraan: `thin_content`,
`reserved`, `image_urls`, `sleeper_score`, `sleeper_reasons`. Bestaande
kolommen houden hun plaats.

De lijst algemene woorden is geschreven voor racefietsen; bij andere
zoekopdrachten (hifi bijvoorbeeld) komt er bijna geen titel door, dus dan zijn
er gewoon geen slapers.

## Prijsverlagingen

Komt een advertentie die je eerder zag terug met een lagere prijs, dan krijgt
hij een `v` in de console en een oranje label `-€X` in het rapport (met een
eigen filtertab "Prijsverlaging") — vaak een sterker koopsignaal dan "nieuw".
Geen extra instelling nodig; het komt uit hetzelfde geschiedenisbestand dat
"nieuw" bijhoudt.

## Melding bij een referentiematch — `--no-notify-better`

Past een nieuwe advertentie op een referentiemodel met
`better_than_baseline`, dan speelt het script een systeemgeluid (Windows) of
de terminalbel (elders) en print een gemarkeerde samenvatting — los van het
algemene "iets nieuws" van `--open-browser`, zodat dit juist meldt waar je naar
op jacht bent. Uit met `--no-notify-better`.

## De tabs Slapers, Fietscomputers, Biedpaneel, Upgrade en Mijn fiets

Naast de advertentietabel (met zijn rijfilters en sorteerbare kolommen) heeft
het rapport meer tabs: **Slapers** (zie boven), **Fietscomputers** (alleen als
de run er heeft; zie [fietscomputers.md](fietscomputers.md)) en de drie
hieronder (PLAN_FIETSWAARDE.md fase 6). De gekozen tab staat in de URL
(`#upgrade`), dus het rapport herladen na een nieuwe run komt op dezelfde uit.

- **Biedpaneel** — elke biedadvertentie, gesorteerd op speelruimte (geschatte
  waarde min wat het kost om binnen te komen, dezelfde getallen als de kolom
  `RUIMTE` in de console): eerst die gewaardeerd op een referentiemodel of
  vergelijkbare fietsen, dan de grove (`grof`), dan de onbekende, die
  `onbekend` lezen, nooit €0.
- **Upgrade** — de kandidaten die `upgrade.py` zou printen, voor de
  advertenties van deze run: gerangschikt op upgrade per euro, met vraagprijs,
  effectieve prijs, budget, het maatoordeel en de uitsplitsing per dimensie
  (muis op een dimensie voor de redenen). Wat afviel staat onder `Afgevallen`,
  met de reden.
- **Mijn fiets** — de taxatie van je eigen fiets per scenario (A en B) als
  band laag–midden–hoog met n, het budget dat dat de upgrade-finder geeft, de
  volledige bewijslijst met links naar de vergelijkingen, en de
  kwaliteitsscore als basislijn.

De laatste twee lezen `mijn_fiets.md` (`--mijn-fiets`) en taxeren de fiets op
de vergelijkingen in `koopjes.db` — alleen lezen, er wordt niets bewaard;
`valuation.py` blijft degene die taxaties schrijft. De vergelijkingen zijn de
advertenties die je op `/fiets` meenam (zie [eigen-fiets.md](eigen-fiets.md)).
Met `--no-db`, zonder intakebestand of zonder meegenomen advertenties zeggen
die tabs waarom in plaats van een getal te tonen.

**Waardescore.** De tabs Upgrade en Biedpaneel hebben een kolom
`Waardescore`: geschatte waarde gedeeld door effectieve prijs, waar 1,00×
betekent dat de prijs is wat hij waard is, en hoger goedkoper. Met opzet een
aparte kolom naast de dealscore, en een andere maat — de dealscore scoort de
prijs tegen de mediaan, het 2e-hands gemiddelde en de nieuwprijs op 0-100. De
waarde is het waargenomen 2e-hands gemiddelde van het model (vanaf twee
waarnemingen) of anders de mediaan van de zoekopdracht, beide gecorrigeerd van
vraagprijs naar verkoopprijs; de deler is de effectieve prijs, niet de kale
vraagprijs, dus een advertentie met vaste prijs op de mediaan scoort 1,00× en
een bod wordt gemeten tegen wat het kost om binnen te komen. Muis op het getal
voor de som.
