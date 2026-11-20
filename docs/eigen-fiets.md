# De eigen fiets — taxatie, kwaliteitsscore en upgrades

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

1. Vul `mijn_fiets.md` in (de intake: maat, onderdelen, budget).
2. Kies op `/fiets` welke advertenties met je fiets vergelijkbaar zijn
   (**✓ meenemen** of **✗ niet**). Alleen die tellen in de taxatie.
3. Leg op `/upgrade` vast wat voor jou een upgrade is; de regel volgt jou.
4. Kijk wat eruit komt:

```bash
python valuation.py --db koopjes.db    # wat is mijn fiets waard
python upgrade.py --db koopjes.db      # welke betere fiets kan ik daarvoor kopen
python scoring.py                      # de kwaliteitsscore van mijn eigen fiets
python upgrade_test.py                 # hoe de upgraderegel het doet op mijn oordelen
```

Hetzelfde staat in de tabs Mijn fiets en Upgrade van het rapport, in het
overzicht en op `/racefietsen`.

Het vergelijkingsmateriaal verzamelt de nachtronde (de zoekopdrachten
`giant-defy`, `giant-defy-composite` en `ultegra-6700`; meteen: `python
koopjes.py run defy`). Met de hand kan het ook:

```bash
python racefiets_jev.py --query "giant defy" --pages 0 --sort newest --reference-file reference_bikes.csv
python racefiets_jev.py --query racefiets --pages 0      # kandidaten voor upgrade.py
```

## `valuation.py` — wat is mijn fiets waard?

Taxeert de fiets uit `mijn_fiets.md` tegen de advertenties die de crawler
verzamelde, en schrijft de uitkomst in de tabellen `valuation` /
`valuation_evidence` (PLAN_FIETSWAARDE.md fase 3). De nachtronde draait hem
vanzelf (`"valuation": true`).

Drie schatters, gemengd tot één band:

- **E1 — vergelijkbare advertenties.** Voor je eigen fiets: precies de
  advertenties die je op `/fiets` meenam (zie onder), met hun vraagprijs; vijf
  of meer is een hard getal, minder is `indicatief`. Niets meegenomen is geen
  taxatie. Voor al het andere (en in de tests) een ladder met afnemend
  vertrouwen: hetzelfde model + modeljaar ±2 + hetzelfde groepsetniveau
  (hoog), dezelfde modelfamilie + jaar ±3 (midden), hetzelfde segment —
  framemateriaal, remtype, versnellingen, jaarbereik (laag). De hoogste trede
  met minstens 5 vergelijkingen wint; daaronder heet de schatting
  `indicatief` en zegt dat in een eigen bewijsregel. Op elke trede moet een
  vergelijking een complete racefiets zijn (een advertentie in de categorie
  racefietsen — een frame of crankstel uit een onderdelen-watchlist niet) en
  mag hij geen ander framemateriaal hebben (uit de tekst, of uit het
  referentiemodel dat paste). Alleen vraagprijzen tellen: een vaste prijs, en
  ook een "bieden vanaf" (MIN_BID), want dat vraagt de verkoper — meer dan de
  helft van de Defy-advertenties is MIN_BID. Een biedadvertentie waarop al
  geboden is valt af, omdat de prijs dan het hoogste bod kan zijn.
- **E2 — vraagprijs → verkoopprijs.** Marktplaats publiceert vraagprijzen,
  geen verkoopprijzen. Zodra minstens 20 advertenties binnen twee weken
  verdwenen en 20 andere 60+ dagen online stonden — verdwenen *of* nog online,
  beide tellen, gemeten vanaf de eerste keer dat wij hem zagen, niet de
  plaatsingsdatum — wordt de verhouding tussen die twee medianen een gemeten
  correctiefactor per categorie; tot dan geldt een vuistregel van 10-15%, met
  dat label. Verdwenen is niet verkocht — dat voorbehoud staat in de uitvoer.
- **E3 — som der delen.** Onderdeelprijzen uit `component_price` maal een
  bundelfactor. Zolang die tabel leeg is (en niets vult hem nog) telt hij niet
  mee, en elk onderdeel zonder waarnemingen krijgt een bewijsregel die dat
  zegt.

Elk getal is terug te voeren op een bewijsregel, met een klikbare link per
vergelijking. Opties: `--scenario a|b` (compleet met de carbon wielset, of met
de standaardwielen en de wielset los verkocht — herhaalbaar, standaard
beide), `--query` om de vergelijkingen tot één zoekopdracht te beperken,
`--window-days` voor hoe ver terug ze tellen (standaard 180), `--dry-run` om
te printen zonder in de database te schrijven.

Wat hij **niet** doet: getallen verzinnen. Geen vergelijkbare advertenties
betekent geen taxatie, geen gok — neem er eerst een paar mee op `/fiets`
(exitcode 2; de nachtronde logt het als uitkomst, niet als fout). De
onderhandelingsmarge van 10-15%, de bundelfactor en het deel van een upgrade
dat een koper van een complete fiets betaalt zijn vuistregels, geen metingen,
en elk staat als eigen regel in de uitvoer zodat duidelijk is wat hij
bijdroeg.

## Met welke advertenties je fiets vergeleken wordt — `/fiets` (`bike_comps.py`)

"Giant Defy" is een modellijn, geen model: sinds 2009 verkocht Giant
aluminium (Aluxx, Defy 0-5), instap-carbon (Composite), Advanced, Advanced
Pro, Advanced SL en vanaf 2015 schijfremfietsen onder die naam, en de meeste
verkopers schrijven gewoon "Giant Defy carbon". Geen regel op titelwoorden
onderscheidt die zo goed als jij door te kijken, dus jij beslist per
advertentie.

De pagina toont elke advertentie van de laatste 180 dagen met de
modelfamilie uit `mijn_fiets.md` ("defy") in de tekst, of gevonden door een
zoekopdracht met dat woord ("giant defy", "giant defy composite"),
verdwenen meegerekend (verkocht of ingetrokken — "weg sinds 12 sep, 9 dagen
online").

- **De zoekopdracht telt** omdat de zoekresultaten alleen de eerste 200
  tekens van een omschrijving geven, en Marktplaats Defy's vindt die nooit
  "defy" zeggen ("Giant racefiets maat L"); zo'n rij zegt *gevonden door de
  zoekopdracht*.
- **Elke categorie** behalve onderdelen en accessoires (`fietsonderdelen`,
  `fietsaccessoires-*`): een Defy onder *heren sportfietsen* of *omafietsen*
  zegt dat ("in dames omafietsen"). Beide Defy-zoekopdrachten 's nachts draaien
  hiervoor met `category: alle` (zie `--category` in [zoeken.md](zoeken.md)).
- **Elk framemateriaal** (sinds 29-09-2026): het materiaal staat erbij maar
  filtert niet — uit het referentiemodel (`reference_bikes.csv`: Defy 0-5 en
  Aluxx zijn aluminium, Composite en Advanced carbon), uit de tekst, of
  *volgens de verkoper* als alleen de kenmerken van de verkoper het zeggen (die
  kunnen fout zijn: een Defy met "COMPOSITE" op zijn liggende achtervork stond
  als aluminium). Een advertentie die niets over zijn materiaal zegt, heet
  *materiaal onbekend*.

Per advertentie: **✓ meenemen** of **✗ niet**; nog eens op de gekozen knop
zet hem terug naar "te beoordelen". De pagina opent op **Te beoordelen** (nieuw
of nog niet bekeken), zodat een gekozen advertentie uit beeld gaat en je de
lijst afwerkt; het filter toont de andere.

Alleen wat je meeneemt telt, met zijn vraagprijs. Een biedadvertentie waarop
al geboden is, staat er met zijn hoogste bod maar telt niet (de prijs loopt
nog op); een "bieden vanaf" (MIN_BID) telt wel. Bovenaan de taxatie van je
fiets met de originele wielen (scenario B, zoals de tab Mijn fiets van het
rapport hem rekent), n en vertrouwen, bijgewerkt bij elke klik zonder
herladen; "Hoe dit bedrag ontstaat" toont de bewijsregels. Tot je minstens één
advertentie met vraagprijs meenam is er geen taxatie, en gebruikt de
upgrade-finder `verkoopprijs_handmatig` uit `mijn_fiets.md`; onder de vijf is
hij `indicatief` en wint die handmatige prijs nog. De keuzes gaan in
`koopjes.db`, tabel `comp_choice` (migratie 16); `valuation.py`, `upgrade.py`,
de tabs Mijn fiets en Upgrade van het rapport en het overzicht gebruiken ze
allemaal.

## `scoring.py` — hoe goed is een fiets, los van de prijs?

De **kwaliteitsscore** uit PLAN_FIETSWAARDE.md fase 4, niet te verwarren met
de dealscore ([rapport.md](rapport.md)): die zegt of een *prijs* goed is, deze
of een *fiets* goed is. Vijf dimensies — frame, aandrijving, remmen, wielen,
extra's — elk 0-100 met de signalen die erin zaten uitgeschreven, gewogen tot
één totaal. De gewichten en scoretabellen staan in `scoring_config.json`, dus
veranderen wat je belangrijk vindt is een wijziging in dat bestand, niet in de
code.

Dezelfde functie scoort een advertentie en je eigen fiets; daardoor is
"beter dan de mijne" een vergelijking en geen mening. Ontbrekende informatie
scoort neutraal en zegt dat, in plaats van gegokt te worden.

Vier sleutels in `scoring_config.json` horen bij de upgradetest hieronder en
staan standaard uit, zodat zonder opgeslagen regel alles scoort als voorheen:

- `drivetrain.age_decay_per_year` / `age_decay_max` — leeftijd telt ook op de
  aandrijving: "Ultegra" is een 10-speed in 2010 en een 12-speed in 2022, en
  het jaar is wat een advertentie meestal wel zegt;
- `wheels.eigen_wielen` — een vaste score voor je eigen wielen; zonder scoort
  de CSC-set als merk-carbon, omdat CSC in de lijst wielmerken staat;
- `upgrade.marge` / `upgrade.onbekend` — de marge, en of een onbekend
  onderdeel het vaste neutrale getal scoort of hetzelfde als je eigen fiets.

De regel die je op `/upgrade` opslaat gaat voor het bestand, voor alles wat
fietsen scoort.

**Wat er gelezen wordt.** Naast de tekst dragen de zoekresultaten een deel van
wat de verkoper zelf aanklikte ("Kenmerken" op de advertentiepagina): het
framemateriaal bij ongeveer de helft van de racefietsen, soms het remtype. Dat
wordt ook gelezen en bewaard in `spec` met bron `marktplaats`; waar de tekst
iets over hetzelfde zegt, wint de tekst (die is specifieker — "hydraulische
schijfrem" waar het kenmerk "Schijfrem" zegt). Op 240 racefietsen gaf dit het
framemateriaal voor 114 advertenties waarvan de tekst het niet noemde.

**De volledige omschrijving voor kanshebbers.** De groepset is het grotere
gat, en die staat zelden in de eerste 200 tekens. Dus voor de paar
advertenties die een upgrade kunnen zijn — een complete racefiets, niet de
verkeerde maat, een effectieve prijs binnen het grootste van je twee budgetten
— haalt de run de advertentiepagina zelf op (`--detail-lookup budget`, de
standaard): de volledige omschrijving en de lijst "Kenmerken" (materiaal, rem,
framehoogte). Hooguit 10 per run, de beste kanshebbers eerst, en nooit twee
keer dezelfde: de tekst wordt bewaard in `koopjes.db`
(`listing.full_description`) en bij latere runs teruggezet. De kwaliteitsscore,
de upgrade-finder en de taxatie lezen de volledige tekst; het herkennen van
referentiemodellen en de slapers blijven op het fragment uit de
zoekresultaten, want een slaper gaat over wat de *zoekopdracht* toont. Heeft
de database en een budget nodig (`mijn_fiets.md`); zonder doet hij niets. Twee
regels werden strenger met de langere tekst: een gelabelde groepsetregel
("Groepset: Ultegra") wint van een onderdeel van een hoger niveau verderop
("Cassette: Dura Ace"), en "Garmin houder" of "Wahoo Kickr" is geen
fietscomputer.

**Afkortingen.** Een advertentie geeft alleen de titel en de eerste ~200
tekens, dus een paar korte vormen worden ook gelezen: "Disc" in een modelnaam
("Emonda SL5 Disc") telt als schijfrem (maar "disc wiel" is een dicht wiel,
geen rem), en een wielmerk zonder materiaal ("Roval Rapide CLX", "Newmen
wielen") scoort `wheels.merk_materiaal_onbekend` — boven onbekend, onder
merk-carbon, omdat hetzelfde merk ook aluminium wielen maakt. Een merknaam
gevolgd door cockpit/stuur/zadel/vork telt niet.

## `upgrade.py` — welke betere fiets kan ik daarvoor kopen?

De andere helft van de vraag die `valuation.py` beantwoordt: de taxatie is het
budget, de kwaliteitsscore uit `scoring.py` de basislijn, en hij rangschikt de
advertenties in `koopjes.db` op hoeveel fiets elk er per euro bij geeft
(PLAN_FIETSWAARDE.md fase 5).

Een advertentie is een kandidaat als alle vier gelden: het is een complete
racefiets (in de categorie racefietsen — onderdelen uit een
powermeter-watchlist zijn geen kandidaat), de framemaat past, hij scoort meer
dan de basislijn plus een marge, en zijn effectieve prijs valt binnen het
budget. Alles wat afvalt komt terug met een reden (`--show-rejected`).

**Zonder taxatie** (te weinig vergelijkingen) is er geen budget. Daarvoor heeft
`mijn_fiets.md` een regel `verkoopprijs_handmatig` in zijn scoreblok: zet daar
je eigen verwachte verkoopprijs — de fiets met zijn standaardwielen, want de
carbon wielset wordt per route apart begroot — en de upgrade-finder (en de tab
Upgrade van het rapport) gebruiken die, en zeggen dat bij de herkomst van het
budget. Hij wint ook van een `indicatief`e taxatie (minder dan 5
vergelijkingen): één verdwaalde vergelijking mag je budget niet stil
verschuiven. Een taxatie op 5+ vergelijkingen wint van hem. Leeg laten = niet
gebruikt.

- **Framemaat is een poort, geen score.** Een fiets buiten de doelmaat
  verschijnt nooit, wat hij ook scoort. Een fiets waarvan Marktplaats de maat
  niet meldt is iets anders — die blijft in de lijst met `maat onbekend`,
  omdat op Marktplaats de maat vaak alleen in de omschrijving staat en die
  allemaal weggooien meer kandidaten kost dan oplevert. `--strict-size` gooit
  ze ook weg; `--size` en `--size-tolerance` overschrijven de doelmaat
  (standaard: de regel `size_cm` in `mijn_fiets.md`, ±2 cm).
- **Het budget hangt af van de kandidaat.** De carbon wielset is een
  velgremset. Bij een velgremkandidaat verhuist hij mee naar de nieuwe fiets:
  dan is het geen geld om uit te geven maar punten om te scoren — de kandidaat
  wordt met die wielen gescoord als ze beter zijn dan de zijne. Bij een
  schijfremkandidaat kan hij niet mee en moet hij verkocht worden, dus dan is
  de opbrengst budget. Een kandidaat waarvan het remtype niet te lezen is,
  krijgt het (lagere) velgrembudget en geen wielenbonus: tot vaststaat dat de
  wielset verkocht kan worden, is de opbrengst niet uit te geven.
  `--budget-extra` zet het geld bovenop de verkoop (standaard: de regel
  `budget_extra` in `mijn_fiets.md`).
- **Effectieve prijs.** Een vraagprijs maal de onderhandelingsfactor, of wat
  het kost om een bod binnen te komen (zie `RUIMTE` onder "Biedadvertenties" in
  [zoeken.md](zoeken.md)). De vraagprijs staat ernaast, zodat een gecorrigeerd
  getal er nooit voor wordt aangezien.
- **Modeljaar.** Een gelabeld jaar in de tekst ("bouwjaar 2016") wint; zonder
  dat wordt een los jaar in de titel ("Giant Defy 2012") gebruikt — dezelfde
  regel als de vergelijkingsladder van de taxatie — en de kandidaat zegt dat
  (`bouwjaar 2012 uit de titel`). Een jaar dat alleen ongelabeld in de
  omschrijving staat telt niet ("sinds 2018 in bezit" is geen modeljaar).
  Zonder jaar krijgt het frame geen leeftijdsverval, dus een fiets met
  onbekend jaar scoort nog iets hoger dan dezelfde fiets met bekend jaar.
- **Gerangschikt op upgrade per euro** — `(score − basislijn) / effectieve
  prijs`, geprint als punten per €100. Geen remtype valt vooraf af: een echt
  koopje op een schijfremfiets is waarom dit gereedschap bestaat, dus de
  rangschikking doet het werk in plaats van een filter.

Elke kandidaat print zijn volledige uitsplitsing per dimensie, en het budget
zijn eigen som. Opties: `--margin` (punten boven de basislijn voor iets als
upgrade telt; standaard: de marge van je regel op `/upgrade`, anders 5),
`--query`, `--window-days`, `--limit`, `--config` voor de scoregewichten (met
je eigen bestand wordt de opgeslagen regel niet toegepast), `--show-rejected`.
Met de standaardconfig gebruikt hij de regel die je op `/upgrade` opsloeg en
print "Jouw regel van /upgrade (opgeslagen …)".

Zolang `component_price` leeg is, zijn er geen waarnemingen van wat een losse
wielset opbrengt, dus komen de twee budgetten gelijk uit en zegt de uitvoer
dat in plaats van een getal te gokken. Hij biedt nergens op en neemt geen
contact op met een verkoper: met opzet buiten het doel.

## De upgradetest — `/upgrade` (`upgrade_test.py`)

Jij bepaalt wat een upgrade is, en de score volgt jou in plaats van andersom.
Open `http://127.0.0.1:8765/upgrade` in `python dashboard.py --serve`
("Upgrade" in de balk bovenaan):

- **Test** — één fiets tegelijk (foto's, prijs, specs, omschrijving): "is dit
  een upgrade van jouw fiets — los van prijs en maat?" Ja, nee of twijfel
  (toetsen `j`, `n`, `t`; `s` slaat over, `u` maakt ongedaan). Het oordeel van
  de regel verschijnt pas na je antwoord, met per onderdeel waarom, zodat het
  je niet stuurt (vink het vakje aan om het eerst te zien). De volgorde spreidt
  over het hele scorebereik, zodat ook de fietsen die de score laag waardeert
  langskomen. Antwoorden worden bewaard in `koopjes.db` (`upgrade_label`,
  migratie 22) en blijven als een fiets verkocht is.
- **Uitslag** — hoeveel van je antwoorden de regel goed heeft, en de fietsen
  waar jij en de regel het oneens zijn, met het verschil per onderdeel. Twijfel
  telt niet mee.
- **Jouw regel** — elke knop van de kwaliteitsscore op één plek: gewichten,
  marge, wat "onbekend" telt, materiaal en leeftijd, groepsetniveaus, remmen,
  wielen (ook een score voor je eigen wielen), extra's. Elke wijziging wordt
  meteen doorgerekend op je antwoorden en op de fietsen die nu te koop staan;
  niets wordt bewaard tot **Opslaan**. **Zoek** probeert gewichten (stappen van
  0,1, dan 0,05 rond de beste), de marge en een paar opties (onbekend = als je
  fiets, leeftijd op de aandrijving, een steilere frameleeftijd, je eigen
  wielen als merkloos carbon) en stelt de regel voor die de meeste antwoorden
  goed heeft; bij gelijkspel de regel die het minst verandert. Hij heeft
  minstens 10 antwoorden nodig met 3 ja en 3 nee, en zegt hoeveel je hem kunt
  vertrouwen. **Terug naar de standaard** haalt je regel weg.
- **Uitdraai** — elke fiets met zijn score per onderdeel, het verschil met je
  fiets, totaal, winst, of hij beter is dan de jouwe en of hij een upgrade is
  op `/racefietsen` (ook maat en budget); sorteren, filteren (te koop,
  beoordeeld, oneens, beter, upgrade), een antwoord per rij wijzigen, en
  **Alles als CSV** voor Excel (puntkomma's, decimale komma's).

Een opgeslagen regel staat in `setting` (`upgrade_regel`) en wordt gebruikt
door `/racefietsen`, het rapport, het overzicht en `upgrade.py`;
`scoring_config.json` blijft de standaard. "Beter dan je fiets" op deze pagina
is alleen de kwaliteitsvraag (winst boven de marge); het upgradeoordeel op
`/racefietsen` eist ook de maat en het budget.

```bash
python upgrade_test.py                  # hoe de regel het doet op je antwoorden, in de console
python upgrade_test.py uitdraai         # elke fiets als CSV: lijsten/upgrade_uitdraai.csv (--uit voor een ander pad)
python upgrade_test.py zoek             # de regel die het best bij je antwoorden past (bewaart niets)
```
