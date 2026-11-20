# Zoeken op Marktplaats — `racefiets_jev.py`

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
pip install -r requirements.txt
python racefiets_jev.py --pages 10
python racefiets_jev.py --query luidsprekers --pages 10
python racefiets_jev.py --pages 0 --max-price 150 --min-frame-height 54 --max-frame-height 60
```

Wie de rondes laat draaien (zie [rondes.md](rondes.md)) typt deze commando's
zelden zelf: `koopjes.py` start `racefiets_jev.py` met de instellingen uit
`schedule.json`.

`racefiets_jev.py` zoekt op [Marktplaats](https://www.marktplaats.nl) naar
advertenties bij een zoekopdracht — standaard racefietsen ("racefiets"), maar
`--query` werkt voor alles (`--query luidsprekers`, `--query "canon eos"`,
...) — en markeert wat ver onder de mediaan van de gevonden prijzen staat. Elke
advertentie krijgt ook één **dealscore** van 0-100 uit alle prijssignalen die
het kent, en het rapport is erop gesorteerd, dus de beste deal staat bovenaan
(zie "Dealscore" in [rapport.md](rapport.md)). Framemaat en groepset zijn
fietsspecifiek en vinden bij andere zoekopdrachten gewoon niets, wat geen
kwaad kan.

Kies een zoekterm die echt specifiek is voor wat je zoekt: de eigen
categoriegegevens van Marktplaats filteren ongerelateerde resultaten weg (zie
"Resultaten buiten het onderwerp"), maar dat werkt alleen als je zoekopdracht
één duidelijke hoofdcategorie heeft. `luidsprekers` werkt goed; `boxen` niet —
op Marktplaats vindt dat woord veel vaker babyboxen dan speakers.

## Wat een run doet

- **Meerdere termen** met een komma (`--query "racefiets,luidsprekers"`) draaien
  in één keer; elke term krijgt een eigen HTML/CSV-rapport (naar de zoekterm
  genoemd), de geschiedenis-, log- en referentiebestanden zijn gedeeld. Doe dit
  alleen als dezelfde filters voor beide zinnig zijn — vooral
  `--min-frame-height`/`--max-frame-height` zouden elk resultaat van een niet-fiets
  wegvegen, want die hebben nooit een framemaat. Anders: per zoekopdracht
  apart, of als watchlist (zie onder) — een watchlist heeft zijn eigen filters.
- **Koopjes** krijgen een `*` als ze op of onder `--bargain-ratio` (standaard
  `0.6`, dus 60%) van de mediane prijs van alles wat gevonden is staan. Die
  mediaan (en het gemiddelde ernaast) gaat over advertenties met een echte
  vraagprijs: een zonder prijs en een "gratis" op €0 tellen niet, want geen van
  beide zegt iets over wat het ding kost. Elke advertentie met prijs toont ook
  `% v. mediaan` — `24%` betekent een kwart van de mediaan — zodat je goedkoop
  op een schaal ziet en niet alleen als `*`. In het rapport is dat een
  sorteerbare kolom, en het telt mee in de dealscore.
- **Het rapport** `racefiets_report.html`: open het in een browser voor een
  sorteerbaar, filterbaar overzicht (Nieuw / Koopjes / Topdeals / Bieden / ...)
  met klikbare links en het gemiddelde/de mediaan van wat gevonden is. Het
  wordt gebouwd uit `report_template.html`, dat naast het script moet staan
  (`--no-html` als je geen rapport wilt). Zie [rapport.md](rapport.md).
- **Nieuw** gaat via `seen_listings.json` (vanzelf aangemaakt): wat je in een
  eerdere run al zag, is niet elke keer "nieuw". Zijn er nieuwe, dan opent het
  rapport vanzelf in je browser (zie `--open-browser`).
- **Het koopjeslogboek** `bargains_log.csv`: elk nieuw gevonden koopje wordt
  erachter gezet — anders dan `--output`, dat elke run overschreven wordt,
  groeit dit, zodat je een geschiedenis van elk koopje hebt.
- **De database** `koopjes.db` krijgt alles, zie [database.md](database.md).

## Vlaggen

| Vlag | Wat | Standaard |
| --- | --- | --- |
| `--query` | zoekopdracht | `racefiets` |
| `--pages` | aantal resultaatpagina's (30 per pagina). `0` = alles wat Marktplaats laat doorbladeren (zie "De eerste keer") | `1` |
| `--min-price` / `--max-price` | filter op prijs in euro | geen |
| `--min-frame-height` / `--max-frame-height` | filter op framemaat in cm; fietsen zonder maat blijven staan (zie onder) | geen |
| `--strict-frame-height` | met het maatfilter ook fietsen zonder maat weglaten | uit |
| `--sort` | `optimized` (Marktplaats' eigen "Standaard") of `newest` (nieuwste eerst — gebruik dit voor geplande runs, zie onder) | `optimized` |
| `--category` | alleen in deze categorieën zoeken (komma-gescheiden sleutel of nummer, bijv. `fietsonderdelen`), door Marktplaats zelf gefilterd, of `alle` voor elke categorie (zie onder) | geen |
| `--split` | een volledige crawl van een categorie met meer dan ~5000 advertenties in delen (zie "Alles in een categorie") | uit |
| `--bargain-ratio` | fractie van de mediaan op of onder welke een advertentie gemarkeerd wordt | `0.6` |
| `--delay` | seconden tussen paginaverzoeken | `1.5` |
| `--output` | resultaten naar een CSV-bestand | geen |
| `--html` | pad voor het HTML-overzicht | `racefiets_report.html` |
| `--no-html` | geen HTML-overzicht | uit |
| `--history-file` | het bestand dat onthoudt welke advertenties al gezien zijn | `seen_listings.json` |
| `--reference-file` | CSV van bekende modellen om vraagprijzen mee te vergelijken (zie [referentiedata.md](referentiedata.md)) | `reference_prices.csv` |
| `--open-browser` | `auto` (alleen bij nieuwe advertenties), `always` of `never` | `auto` |
| `--log-file` | CSV waar nieuwe koopjes achter gezet worden | `bargains_log.csv` |
| `--no-log` | het koopjeslogboek niet bijwerken | uit |
| `--price-history-file` | CSV met waargenomen prijzen van advertenties die op een referentiemodel passen (je eigen marktprijsdatabase) | `reference_price_history.csv` |
| `--no-price-history` | waargenomen 2e-handsprijzen niet bijhouden of gebruiken | uit |
| `--no-notify-better` | geen geluid/melding als een advertentie de referentie verslaat | uit |
| `--bid-lookup` | van welke biedadvertenties de biedingen opgehaald worden: `fast` (alleen FAST_BID), `all` (ook MIN_BID), `none` | `fast` |
| `--no-bid-lookup` | hetzelfde als `--bid-lookup none` | uit |
| `--detail-lookup` | `budget`: de advertentiepagina ophalen (volledige omschrijving, "Kenmerken") voor complete racefietsen binnen je maat en budget — hooguit 10 per run, elke advertentie één keer, alleen met `--db` (zie [eigen-fiets.md](eigen-fiets.md)). `none` slaat het over | `budget` |
| `--bids-only` | alleen biedadvertenties in het rapport | uit |
| `--min-score` | alleen advertenties met minstens deze dealscore (0-100) | geen |
| `--db` | pad naar de SQLite-database (zie [database.md](database.md)) | `koopjes.db` |
| `--no-db` | niet naar de database schrijven | uit |
| `--summary-file` | één JSON-regel per rapport erachter (aantallen, pad, interessantste nieuwe) — wat het overzicht van `koopjes.py` leest | geen |
| `--mijn-fiets` | intake van je eigen fiets, voor de tabs `Mijn fiets` en `Upgrade` van het rapport (zie [rapport.md](rapport.md)) | `mijn_fiets.md` |
| `--watchlist` | opgeslagen zoekopdrachten op naam draaien (komma-gescheiden, of `all` voor elke actieve), elk met eigen filters en rapport (zie onder) | geen |
| `--watchlist-add NAAM` | `--query` plus de filtervlaggen op deze regel opslaan als watchlist `NAAM` (vervangt een bestaande); crawlt niet | geen |
| `--watchlist-remove NAAM` | een watchlist weghalen; crawlt niet | geen |
| `--watchlist-list` | de opgeslagen watchlists tonen; crawlt niet | uit |

## De eerste keer: alles ophalen

Gebruik één keer `--pages 0` om `seen_listings.json` te vullen met alles wat
Marktplaats nu heeft, zodat je eerste geplande run niet alles tegelijk als
"nieuw" markeert. Een volledige crawl duurt een paar minuten (Marktplaats houdt
op na een paar honderd pagina's, hoeveel resultaten een zoekopdracht ook
heeft, dus "alles" is alles wat je mag doorbladeren — meestal de paar duizend
meest relevante of recente, niet letterlijk elke advertentie die ooit paste).
Draai daarna met een kleine `--pages` op je vaste schema — nieuwe advertenties
zijn waar je naar zoekt, en die staan op de eerste pagina('s).

## Framemaat

Marktplaats geeft geen exacte framemaat — verkopers kiezen uit vaste
bakjes ("53 tot 57 cm", "57 tot 61 cm", enz.). `--min-frame-height`/
`--max-frame-height` nemen elk bakje mee dat je bereik overlapt, dus een fiets
in een bakje dat maar deels overlapt ("53 tot 57 cm" bij `--min-frame-height
54`) kan er nog tussen staan.

Een fiets zonder maat **blijft staan** — dat zijn de meeste: op een crawl van
40 pagina's "racefiets" (september 2026) had 76% geen maat ingevuld, vaak
omdat de verkoper "maat 56" in de tekst schreef. Die weglaten verborg drie op
de vier fietsen. `--strict-frame-height` laat ze toch weg.

## Sortering — `--sort newest`

De standaardvolgorde van Marktplaats ("Standaard", `--sort optimized`) is niet
op datum. Op een crawl van 40 pagina's "racefiets" stonden de advertenties van
vandaag verspreid over alle 40 pagina's — 83 van de 314 op de eerste drie — en
de 1200 plekken hielden maar 951 verschillende advertenties: de
standaardvolgorde toont sommige op meerdere pagina's en slaat andere over.
`--sort newest` haalt nieuwste eerst op via de zoek-API van Marktplaats
(dezelfde die het menu "Sorteer op" van de site gebruikt), zodat een geplande
run van een paar pagina's alles ziet wat sinds de vorige nieuw is. De
standaard blijft `optimized`, zodat een bestaande opzet zich blijft gedragen
zoals hij deed.

## Categorieën — `--category`

Marktplaats markeert de categorie waar een zoekopdracht echt over gaat (zie
"Resultaten buiten het onderwerp"), en het script houdt alleen die over.
Sommige zoekopdrachten hebben er twee: "powermeter" is dominant in zowel
*fietsonderdelen* (losse powermeters) als *fietsen-racefietsen* (fietsen met
een powermeter erop); dan houdt het script de grootste en zegt het dat.

- `--category fietsonderdelen` kiest de categorie (of categorieën) zelf, en
  Marktplaats filtert aan zijn kant, dus er gaan geen pagina's naar de rest. Gebruik
  de sleutel uit de URL op marktplaats.nl of het nummer; een onbekende toont
  de categorieën die wel resultaten hebben. Meerdere categorieën moeten onder
  dezelfde hoofdcategorie vallen (bijv. `fietsonderdelen,fietsen-racefietsen`,
  beide onder *fietsen-en-brommers*). Heeft er één vandaag geen resultaten,
  dan wordt hij met een waarschuwing overgeslagen ("let op: categorie ...
  heeft nu geen resultaten"); alleen als geen enkele resultaten heeft, is het
  een fout. Veelgebruikt voor fietsen: `fietsen-racefietsen`, `fietsonderdelen`,
  `fietsaccessoires-fietscomputers`.
- `--category alle` is het omgekeerde: elke categorie, zonder filter en zonder
  gok naar de hoofdcategorie — alles wat Marktplaats vindt, net als zoeken op
  de site zonder categorie. Voor een zoekopdracht die zijn eigen filter is.
  "giant defy" is dominant in racefietsen, maar op 29-09-2026 waren 23 van de
  165 resultaten Defy's die een verkoper onder
  *heren-sportfietsen-en-toerfietsen*, *dames-omafietsen* en dergelijke had
  gezet, en de gok liet ze allemaal vallen. De prijs: losse onderdelen en een
  enkele vage treffer komen mee (in het eigen rapport van die zoekopdracht).
  `alle` gaat niet samen met andere categorieën.

## Alles in een categorie — `--split`

Marktplaats bladert door ~5000 resultaten per zoekopdracht en niet verder,
ook met 100 per pagina; de categorie racefietsen heeft er ~13-14k. Met
`--split` (`"split": true` in `schedule.json`) draait een volledige crawl
(`--pages 0`) met een `--category` die meer heeft in delen: per staat (Nieuw,
Zo goed als nieuw, Gebruikt — een staat met meer dan ~4800 ook oudste eerst)
en per prijsband (€0-150, 150-300, ... voor de advertenties zonder staat), elk
door Marktplaats zelf gefilterd (nagekeken 30-09-2026). Advertenties zonder
bedrag ("bieden") zijn niet op prijs op te vragen, en sorteren op prijs laat
ze weg; daarom gaat de staat eerst.

Hij is alleen volledig als de delen samen elke advertentie zagen die
Marktplaats telt; anders wordt er niets als verdwenen gemarkeerd. Hij draait
met opzet langzamer dan een gewone crawl: op 30-09-2026 antwoordde Marktplaats
met 403 na ~120 snelle verzoeken van 100 advertenties, en was een paar minuten
later weer goed. Dus: minstens 4 s tussen verzoeken, elke 40 een minuut pauze,
en na een 403 wacht hij 5 minuten en probeert het nog één keer voor hij stopt
met wat hij heeft.

## Resultaten buiten het onderwerp

Voorbij een bepaalde diepte (ongeveer pagina 50+ voor "racefiets") wordt de
zoekfunctie van Marktplaats losser: van echte treffers naar vage woordtreffers
— oude PS2/Game Boy-racespellen omdat er "racer" in de titel staat. Het script
leest de "dominante categorie" die Marktplaats voor de zoekopdracht geeft (de
categorie waar het volgens Marktplaats echt over gaat) en laat advertenties
daarbuiten vallen; het print hoeveel. Dit vangt niet de enkele advertentie die
een verkoper zelf verkeerd indeelde (fietsschoenen onder "Racefietsen") — een
`--exclude` daarvoor bestaat nog niet (vraag erom als je hem wilt). Markeert
Marktplaats meer dan één categorie als dominant, dan houdt het script de
grootste en noemt de andere in zijn uitvoer; `--category` kiest in plaats
daarvan, en `--category alle` zet dit filter uit.

**Gezocht-advertenties** — iemand die wil kopen, in dezelfde categorie — vallen
ook weg, en worden geteld. Niets in de gegevens markeert ze, dus dit gaat op de
titel: "gezocht" aan het begin, aan het eind of tussen haakjes ("Gezocht:
racefiets", "Garmin Edge 530 gezocht", "(Gezocht)"), maar niet "veel gezocht
model".

## Watchlists — `--watchlist`

Een watchlist is een zoekopdracht met een naam en eigen filters, bewaard in
`koopjes.db` (tabel `watchlist`) — om naast de fietszoekopdracht op een los
onderdeel te jagen, zoals een powermeter of een nieuwere fietscomputer, zonder
dat de twee elkaar in de weg zitten. De rondes zetten de zoekopdrachten uit
`schedule.json` er zelf in. Met de hand, één keer opslaan:

```bash
python racefiets_jev.py --watchlist-add powermeter --query powermeter \
    --min-price 100 --max-price 500 --reference-file reference_bike_accessories.csv
python racefiets_jev.py --watchlist-list
```

`--watchlist-add` bewaart `--query` plus wat van deze afwijkt van de
standaard: `--min-price`, `--max-price`, `--min-frame-height`,
`--max-frame-height`, `--strict-frame-height`, `--bargain-ratio`,
`--reference-file`, `--category`, `--bids-only` en `--min-score`. Een
referentiebestand dat niet bestaat geeft een waarschuwing, bij opslaan en bij
draaien — een relatief pad wordt gezocht vanuit de map waar het script start.
Opslaan onder een bestaande naam vervangt hem; `all` en namen met een komma
zijn gereserveerd. Daarna draaien, alleen of naast een gewone zoekopdracht:

```bash
python racefiets_jev.py --watchlist powermeter
python racefiets_jev.py --query racefiets --max-frame-height 58 --watchlist powermeter
python racefiets_jev.py --watchlist all      # elke actieve watchlist
```

De twee kanten delen geen filters. Een watchlist begint bij de standaarden en
past alleen de zijne toe — in het tweede voorbeeld geldt `--max-frame-height
58` alleen voor `racefiets` (anders zou het elke powermeter laten vallen, want
die heeft geen framemaat), en de prijsgrenzen van de watchlist raken de
fietszoekopdracht ook niet. Alles wat gaat over *hoe* de run gaat in plaats van
*wat* hij zoekt — `--pages`, `--sort`, `--bid-lookup`, `--delay`, `--db`, de
geschiedenis-, log- en prijshistoriebestanden, `--open-browser` — komt van de
commandoregel, zodat een geplande ondiepe run ondiep blijft en niet meer
verzoeken doet dan je vroeg. Elke watchlist krijgt een eigen rapport, naar hem
genoemd (`racefiets_report_powermeter.html`, en `<output>_powermeter.csv` met
`--output`); een watchlist met een komma-gescheiden zoekopdracht krijgt er een
per term. Zonder `--query` draaien alleen de watchlists; een onbekende naam
stopt de run voor er iets opgehaald is.

Het `--reference-file` van een watchlist is ook wat in `model` wordt ingelezen
en in `listing_model` gekoppeld voor zijn advertenties: zo komen de
accessoires met `reference_bike_accessories.csv` gekoppeld in de database.

## Biedadvertenties (FAST_BID / MIN_BID)

Sommige advertenties ("Bieden") hebben geen vaste prijs. De zoekresultaten
melden voor deze altijd €0 (`FAST_BID`), terwijl de advertentie zelf een echt
minimumbod heeft, of een echt hoogste bod zodra er geboden is. Standaard haalt
het script de pagina van elke `FAST_BID` op voor dat echte getal (`B` in de
tabel, "bod" in het rapport) en gebruikt het overal — prijsfilters, de
koopjesvergelijking, de dealscore — in plaats van hem als prijsloos te
behandelen. `MIN_BID`-advertenties melden al een getal in de zoekresultaten,
dus daar is geen extra verzoek voor nodig, maar ze krijgen ook een `B`: het
blijft een bod, geen vaste vraagprijs.

Dat is één extra verzoek per `FAST_BID`, dus een run met veel daarvan duurt
langer. `--bid-lookup none` (of `--no-bid-lookup`) slaat het over en behandelt
ze weer als prijsloos. Je filters draaien vóór het opvragen, dus een advertentie
die `--min-price`, `--max-price` of de maatfilters al uitsluiten, kost nooit een
verzoek. Een `FAST_BID` heeft op dat moment geen prijs om op te filteren; die
worden eerst opgevraagd en daarna aan de prijsgrenzen getoetst zoals de rest.

**Wat een `MIN_BID`-prijs echt is.** Het getal in de zoekresultaten is wat de
verkoper vraagt; het minimumbod dat Marktplaats echt accepteert staat op de
advertentiepagina en ligt er vaak flink onder — een advertentie van €200 nam
biedingen vanaf €120, een van €47,50 vanaf €35. `--bid-lookup all` haalt die
pagina's ook op (één extra verzoek per `MIN_BID`) en vult het echte minimumbod
en het aantal biedingen in. De vraagprijs blijft de prijs voor filters en
score, omdat die eerlijk te vergelijken is met advertenties met een vaste prijs
— het minimumbod staat apart, in een eigen kolom `Bod`, als wat het kost om het
bieden te openen. Tenzij iemand al meer bood dan de vraagprijs: dan is dat bod
de prijs, want daaronder is de advertentie niet meer te krijgen.

**Nog vrij te bieden.** Biedadvertenties waarop nog niemand bood, krijgen een
label `VRIJ TE BIEDEN` en een eigen filtertab in het rapport. Elke run print
ook een `BIED-OVERZICHT`: alle biedadvertenties, gesorteerd op speelruimte
(`RUIMTE`, zie onder), met het minimumbod, welk percentage van de mediaan dat
minimum is, en het referentiemodel als er een paste. Dat percentage staat er
alleen zolang niemand bood: is er een bod, dan koopt het minimum de
advertentie niet meer, dus blijft het een gewoon getal zonder als goedkope
instap gepresenteerd te worden.

Een advertentie telt alleen als "nog vrij te bieden" als het aantal biedingen
echt opgevraagd is en nul was — een `MIN_BID` zonder `--bid-lookup all` heeft
een onbekend aantal, en dat is niet hetzelfde als nul. Voor een volledig
beeld van wat te bieden is:

```bash
python racefiets_jev.py --query luidsprekers --pages 5 --bid-lookup all --bids-only
```

**`RUIMTE` — hoeveel lucht er in een bod zit.** Geschatte waarde min wat het
kost om binnen te komen: het minimumbod zolang niemand bood, het staande bod
zodra iemand bood, en de vraagprijs als het bod nooit opgevraagd is. Dat laatste
geval geldt met opzet *niet* als €0 of als het minimumbod — een niet-opgevraagd
bod is onbekend, niet gratis, en de kolom print een streepje als er niets te
zeggen valt. De geschatte waarde komt uit de beste maatstaf die er voor die
advertentie is, in deze volgorde:

1. het waargenomen 2e-hands gemiddelde van zijn referentiemodel, vanaf twee
   waarnemingen;
2. de mediane vraagprijs van **vergelijkbare fietsen** in dezelfde set
   advertenties — zelfde framemateriaal en groepsetniveau, versmald tot
   hetzelfde remtype (velg of schijf, het dichtst bij een leeftijd wat een
   advertentie meestal geeft) als dat bekend is en genoeg fietsen heeft.
   Minstens 5, de advertentie zelf niet meegeteld, lopende biedingen niet;
3. de mediaan van de hele zoekopdracht — **grof** (`grof`). Er staat niets van
   de fiets zelf achter: het is wat een zadel of een paar schoenen in de
   categorie racefietsen ook krijgt. De console print voor deze geen
   `RUIMTE`, en in het rapport staan ze onder elke echte schatting.

Alle drie zijn vraagprijzen, gecorrigeerd naar een realistische verkoopprijs
met dezelfde factor als `valuation.py`. Ook de mediaan van vergelijkbare
fietsen mengt nog modeljaren (een Ultegra-fiets van 2009 en een van 2024
kunnen een segment delen als geen van beide het remtype noemt), dus lees een
grote speelruimte bij een oude fiets als reden om te kijken, niet als winst.
Advertenties met onbekende (of grove) speelruimte houden de oude volgorde (die
waarop niemand bood eerst, elke groep op dealscore) en staan onder die met een
getal.

`--bids-only` beperkt het rapport tot biedadvertenties. De kolom `% v.
mediaan` en de mediaan onder de tabel (en in het rapport) worden allebei nog
gemeten tegen alles wat eerst gevonden is, niet alleen wat na
`--bids-only`/`--min-score` overblijft — zodat de vergelijking tegen de hele
markt blijft, en kolom en voettekst het nooit oneens zijn over welke mediaan ze
bedoelen.

Onthoud dat de prijs van een biedadvertentie is waar het bieden nu staat, niet
waarvoor hij weggaat, dus zijn dealscore is een bovengrens — de uitsplitsing
van de score zegt dat bij die advertenties.

## Groepsetherkenning (fietsen)

De consoletabel en het rapport tonen een herkende groepset (Shimano
Claris/Sora/Tiagra/105/Ultegra/Dura-Ace, SRAM Apex/Rival/Force/Red,
Campagnolo Veloce/Centaur/Chorus/Record/Super Record, plus het label
"(elektronisch)" voor Di2/eTap/AXS) als die in de titel of omschrijving
genoemd wordt. Dit is zoeken op woorden in vrije tekst, geen gestructureerd
veld van Marktplaats, dus het kan een groepset missen die ongewoon is
opgeschreven of alleen op een foto staat. Niveaunamen van SRAM en Campagnolo
("Force", "Record") tellen alleen als ook de merknaam ergens in de tekst staat,
om niet op het gewone woord te matchen — of, voor SRAM, als eTap of AXS in
dezelfde zinsnede staat ("Force AXS", "Red eTap"), zoals de meeste verkopers
het schrijven.

Het label "(elektronisch)" vereist dat de aanduiding bij de groepset zelf
hoort: Di2 telt alleen bij een Shimano-groepset en eTap/AXS alleen bij een
SRAM, en het woord moet in dezelfde zinsnede staan als de groepsetnaam
("Shimano Ultegra R8050 Di2"). Een vermelding verderop gaat meestal over iets
wat de fiets niet heeft — "Shimano 105, Di2-upgrade mogelijk" is een
mechanische 105 — dus die krijgt geen label, ten koste van een advertentie die
groepset en Di2 in losse zinnen noemt. De code: `crawl.detect_groupset()`.

## Als Marktplaats verandert

Dit leest de openbare zoekpagina's van Marktplaats rechtstreeks (geen API-sleutel
of dienst van derden). Marktplaats kan zijn paginastructuur op elk moment
veranderen, en dan kan het lezen breken — het script geeft dan een duidelijke
fout in plaats van stil door te gaan.
