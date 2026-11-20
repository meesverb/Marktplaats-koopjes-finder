# De live pagina's — `python dashboard.py --serve` (`server.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
python dashboard.py --serve              # opent http://127.0.0.1:8765/start; Ctrl+C stopt
python dashboard.py --serve --port 8800  # een andere poort
python dashboard.py --serve --no-browser # zonder de browser te openen
```

De geschreven `dashboard.html` leest alleen. `--serve` start een klein
programma op je eigen computer (alleen bereikbaar op `127.0.0.1`) dat
dezelfde pagina's live toont, met knoppen. Alles wat je invoert gaat in
`koopjes.db`.

## Eén adres voor alles

De browser opent op `/start`: de laatste ronde, wat je flips opleverden, je
lopende biedingen, links naar elke live pagina — racefietsen `/racefietsen`
([racefietsen.md](racefietsen.md)), fietscomputers `/`
([fietscomputers.md](fietscomputers.md)), sporthorloges `/horloges`
([horloges.md](horloges.md)), je eigen fiets `/fiets` en `/upgrade`
([eigen-fiets.md](eigen-fiets.md)), je flips `/flips` ([flips.md](flips.md))
— en naar de bestanden die de rondes schrijven: het overzicht, elk
`racefiets_report*.html`, de lijsten in `lijsten/`, de notities
`fiets/taxatie_*.md` en `logs/koopjes.log`, onder `/bestanden/` met een balk
terug naar de startpagina. Verder wordt niets uit de map geserveerd (niet
`koopjes.db`, niet `sheets.json`). Een link in het overzicht naar
`dashboard.html` of `dashboard_horloges.html` opent de live versie. Elke live
pagina heeft dezelfde balk bovenaan.

**Op een telefoon** (smaller dan 700 px; de server luistert alleen op
127.0.0.1, dus dit is de browser op de computer zelf of een smal venster):
de balk bovenaan klapt in tot één knop met de naam van de pagina (☰), rijen
tabs en weergaven scrollen opzij in plaats van over vier regels te lopen,
knoppen en velden zijn minstens 40 px hoog, en op `/racefietsen` staan de
filters achter **Filters ▾** naast het zoekveld (de sneltoetsen zijn
verborgen: geen toetsenbord). De vaste balk daar ging van meer dan de helft
van het scherm naar ongeveer 110 px.

**Rondes starten vanaf de startpagina.** Onder *Rondes* heeft elk slot uit
`schedule.json` een knop **starten**, met wat het zoekt, hoe diep en wanneer
het laatst draaide. Hij draait precies wat de taakplanner draait, `python
koopjes.py run <slot>`, als los achtergrondproces (het loopt door als je de
server stopt); de pagina toont het einde van `logs/koopjes.log` terwijl het
loopt en herlaadt als het klaar is. Nooit twee tegelijk (het slot van
`koopjes.py`), en om beleefd te blijven tegen Marktplaats kan een slot pas 30
minuten na zijn vorige ronde weer starten, 6 uur voor een slot dat alles
ophaalt (`pages: 0`) — geplande rondes tellen ook mee (`launcher.py`).

## Eigen aan- en verkopen

Elke advertentie op de dashboards heeft een knop **Gekocht** met de prijs al
ingevuld, en **Mijn flips** heeft per stuk op voorraad een formulier
**Verkocht** (verkoopprijs, verzending — €3 ingevuld —, datum,
Marktplaats/Vinted/anders), "terug naar voorraad", "verwijderen", en een
formulier voor aankopen elders (een Vinted-aankoop bijvoorbeeld). Alles gaat in
`koopjes.db`, tabel `trade` (migratie 7): wat je betaalde en kreeg, plus wat
het dashboard verwachtte toen je kocht, zodat je ziet hoe goed zijn
schattingen zijn. Je eigen aan- en verkopen zijn nooit vergelijkingsmateriaal
voor andere advertenties, en je eigen aankoop telt niet mee in de schatting
van wat hij opbrengt. Wat je kocht verdwijnt uit Flips en Upgrades en krijgt
een ✓ in Alle computers.

Elk formulier en elke knop stuurt een geheim mee dat bij het starten gekozen
wordt, en het programma controleert waar een verzoek vandaan komt, zodat een
andere website via je browser niet in je database kan schrijven.

## Favoriet, wegzetten en notities

Zodat je niet steeds dezelfde advertenties doorloopt, heeft elke advertentie
in de live versie **☆ favoriet** en **weg: niet waard / gereserveerd**.

- Een favoriet krijgt een ★ en een eigen tab, Favorieten.
- Een weggezette advertentie verdwijnt uit Flips, Upgrades en "Zonder prijs"
  (ook in `python watches.py`); Flips zegt hoeveel je wegzette. Hij blijft in
  Alle computers achter het filter **Toon**, waar **terugzetten** het ongedaan
  maakt. Wegzetten is niet voor altijd: de prijs van dat moment wordt bewaard,
  en ziet een ronde de advertentie goedkoper, dan staat hij weer op Flips met
  de regel "Weer terug: de prijs zakte van €90 naar €70" — zet hem opnieuw weg
  en de nieuwe prijs telt.
- Elke advertentie kan ook een eigen **notitie** dragen ("gevraagd of €120
  kan", "mail gestuurd, wacht op antwoord"), gemarkeerd of niet: klik
  "notitie toevoegen" eronder. De notitie staat onder de advertentie overal
  waar die verschijnt, ook onder een favoriet die offline ging; het zoekveld
  in Alle computers zoekt er ook in, en **Toon: met notitie** toont alle
  advertenties met een notitie. Een notitie hoort bij de advertentie, niet bij
  je markering: de markering weghalen laat hem staan. Eén regel, hooguit 500
  tekens; een lege notitie wist hem.

Favoriet, weg en de notitie werken **zonder de pagina te herladen**: de
labels en knoppen veranderen waar je klikte, een weggezette advertentie
verdwijnt uit Flips en Upgrades, en de aantallen op de tabs volgen (een
melding onderaan zegt wat er bewaard is). Alleen **terugzetten** van een flip
bouwt de tab Flips opnieuw, omdat die rij niet op de pagina stond. Gekocht en
controleer herladen nog wel, en komen terug op dezelfde tab, op dezelfde
plek, met dezelfde zoekopdracht.

Markeringen gaan in `koopjes.db`, tabel `listing_mark` (migratie 12,
`marks.py`), één per advertentie; notities in de tabel `listing_note`
(migratie 15, die de notities van migratie 13 bij de markeringen overzette).
Beide zijn jouw oordeel, geen marktwaarneming, dus een weggezette advertentie
telt nog als vergelijkingsmateriaal. De geschreven `dashboard.html` toont de
markeringen en notities maar heeft geen knoppen. Vinted-advertenties en de tab
Uitgefilterd hebben (nog) geen markeringen of notities.

## Controleer: een advertentie nu nakijken

Het dashboard toont wat de laatste ronde zag, en dat kan uren oud zijn:
overdag kijkt het slot `computers` alleen naar de nieuwste 2 pagina's, dus een
advertentie van vorige week komt pas in de nachtronde weer langs. Een
advertentie die om 11:00 gereserveerd werd, staat tot dan op Flips. En de
biedingen op een advertentie met vraagprijs (`MIN_BID`, "vraagprijs, bieden
kan") staan alleen op de advertentiepagina zelf, die de horlogezoekopdrachten
niet ophalen (`bid_lookup` `fast`): een Suunto voor €290 met al €350 erop
geboden telde als flip op €290.

Daarom heeft elke advertentie in de live versie een knop **controleer** naast
favoriet/weg. Hij haalt die ene advertentiepagina op bij Marktplaats — één
verzoek per klik, nooit twee tegelijk, en minstens 1,5 s ertussen zoals de
`--delay` van een ronde — en bewaart wat erop staat (`recheck.py`):

- gereserveerd of niet (een gereserveerde verdwijnt uit Flips; een die niet
  meer gereserveerd is komt terug);
- de biedingen (aantal, hoogste, minimum — dezelfde regels als de
  biedopvraging van een ronde, dus een bod boven de vraagprijs wordt de prijs
  en leest "huidig bod, loopt nog op");
- de huidige prijs;
- of de advertentie nog bestaat (Marktplaats antwoordt 410 voor een die weg
  is; die wordt dan als verdwenen gemarkeerd, zoals de nachtronde gedaan zou
  hebben).

De melding bovenaan zegt wat hij vond, bijv. "4 biedingen, hoogste €350, boven
de vraagprijs van €290; prijs €290 → €350", en de advertentie toont
"gecontroleerd dd-mm-yyyy HH:MM". Hij biedt nooit en reageert nooit. Kan de
pagina niet gelezen worden (geen verbinding, of Marktplaats veranderde zijn
paginastructuur), dan zegt de melding dat en wordt er niets bewaard. De
controle laat `last_seen` staan — dat blijft de laatste ronde, waar "laatste
ronde" en "nieuw" op gaan — en bewaart het hoogste bod en het tijdstip in
`listing.bid_high` en `listing.checked_at` (migratie 14). De biedopvraging van
een ronde vult `bid_high` ook, en een bod boven de vraagprijs telt tot de
volgende opvraging, ook als een ronde zonder opvragingen de vraagprijs weer
ziet.

## Afstand — `distance.py`

Elke live pagina (`/racefietsen`, `/`, `/horloges`) kan tonen hoe ver elke
advertentie van je postcode is, hemelsbreed, erop filteren (een schuifje,
5-250 km, met *ook zonder plek* voor advertenties zonder plaats) en erop
sorteren (de kolom **Afstand**, *Dichtstbij eerst* op `/racefietsen`). Vul de
postcode in op de pagina (`3511` of `3511AB`); hij wordt bewaard in
`koopjes.db` (tabel `setting`, migratie 18), niet in een bestand in git. Maak
het veld leeg om hem weg te halen. Afstand telt in geen enkele score.

Hoe, zonder dienst van buiten: de zoekresultaten geven van elke advertentie
breedte- en lengtegraad (ook zonder postcode in het verzoek; nagekeken
29-09-2026), vanaf de volgende ronde bewaard in `listing_place`. Marktplaats
zegt niet waar een postcode ligt, maar een zoekopdracht *met* postcode geeft
van elke advertentie de afstand ernaartoe in hele km; de postcode bewaren
stuurt één zoekverzoek en zoekt het punt waar die afstanden het over eens zijn
(op 29-09-2026: 3511AB binnen 0,3 km, een Groningse postcode binnen 0,5 km).
Een `distanceMeters` van 0 betekent daar onbekend (sommige winkels) en wordt
genegeerd. Daarna wordt alles lokaal gerekend, dus een nieuwe postcode geldt
meteen voor elke advertentie. Advertenties van vóór migratie 18 krijgen de
plaats van andere advertenties in dezelfde plaats tot een ronde ze weer ziet
(getoond als *ca.*); een verkoper die alleen het land gaf, heeft geen plaats.

## Eigen biedingen — `own_bids.py`

Bieden gebeurt op Marktplaats, door jou; het script biedt nooit. Wat je op
elke live pagina kunt doen is het vastleggen: **ik heb geboden** (onder elke
advertentie op de dashboards, de toets **b** op `/racefietsen`) met het
bedrag; de datum vult zichzelf in. Elk bod wordt bewaard (eerst €250, dan
€280), en de status van het laatste zegt waar je staat: *open*, *overboden*,
*afgewezen*, *geaccepteerd* of *ingetrokken*, elk één klik.

**Geaccepteerd** zet de advertentie meteen op `/flips`, fase *gekocht*, met je
bod als inkoopprijs en, voor een racefiets, de flipschatting als doelprijs
(een computer of horloge komt onder zijn eigen markt). Twee keer accepteren
maakt geen tweede flip; daarna een andere status kiezen laat de flip staan —
haal hem weg op `/flips` als de koop niet doorging. Zag de laatste
biedopvraging of controleer een hoger bod dan het jouwe, dan zegt de
advertentie *er staat al €… op*. Bewaard in `own_bid` (migratie 18); de
startpagina heeft een tegel met je lopende biedingen.

## Weergaven en likes — `views.py`

Hoeveel mensen een advertentie bekeken en bewaarden ("bewaard", het hartje)
staat alleen op de advertentiepagina zelf (`stats`: `viewCount`,
`favoritedCount`, en `since`, het moment van plaatsen), niet in de
zoekresultaten. Elke meting is dus één verzoek, en dat gebeurt zuinig:

- **gratis** waar een ronde of controleer de pagina toch ophaalt
  (biedopvragingen, `--detail-lookup`);
- **gericht**: je eigen advertenties op `/flips` die *te koop* staan met een
  Marktplaats-link, elke 6 uur; favorieten en advertenties met een lopend bod
  van jou, elke 12 uur;
- **een steekproef**: een vaste 1 op 10 van de nieuwe advertenties in de drie
  markten (racefietsen, fietscomputers, sporthorloges), gemeten op 1, 3 en 7
  dagen oud. Vast op het advertentienummer, zodat steeds dezelfde advertentie
  gemeten wordt en je ziet hoe hij groeit.

Nooit meer per ronde dan de `views_budget` van het slot, gericht eerst, met de
gewone pauze tussen verzoeken; drie mislukkingen achter elkaar stoppen het.
Met de hand: `python views.py plan 20` toont wat de volgende ronde zou meten,
`python views.py meet 10` meet er nu zoveel. Bewaard in `listing_stats` (één
rij per keer kijken, migratie 18); een verdwenen advertentie (410) wordt als
verdwenen gemarkeerd.

Waar je het ziet: onder elke advertentie (*158× bekeken · 4× bewaard (+2
bewaard sinds …)*), op `/flips` voor je eigen advertentie met de groei als
twee kleine lijnen, en op de tabs **Patronen**: de mediane weergaven en likes
naar leeftijd, likes per dag in de eerste dagen tegen het deel dat binnen 7
dagen weg was (weg is niet verkocht), en weergaven per dag naar promotie (een
*Dagtopper*, uit de zoekresultaten), prijs, dag en dagdeel van plaatsen, en
voor/na een prijsverlaging. Elke groep zegt zijn n; onder 10 staat er *te
weinig*. Dit is samenhang, geen oorzaak: een verkoper die voor een Dagtopper
betaalt, maakt misschien ook betere foto's.

## Waarom het snel is

De live server onthoudt het zware deel van elke pagina (vergelijkingsprijzen,
flips, patronen) tussen twee klikken (`LiveCache`), en rekent het pas opnieuw
als een ronde, controleer, een aan- of verkoop of een Vinted-import de
database veranderde. Hij rekent het ook vooruit: meteen na het starten, en
opnieuw zodra een ronde klaar is (de database bleef een minuut gelijk), zodat
het eerste bezoek na een ronde niet de paar seconden wacht die dat kost. En de
knoppen zijn gewone knoppen, geen formulier per advertentie: met ~2800
fietscomputers had de pagina ~8000 formulieren, en een browser deed daar
tientallen seconden over — bij elke klik, want elke klik herlaadde de pagina
(gemeten in Chromium op 29-09-2026 op een database van die grootte: 29 s voor
de fietscomputerpagina en 13 s voor de horlogepagina, nu 2,2 s en 1,4 s).

Sinds 30-09-2026 nog drie dingen (gemeten op een verzonnen database van twee
maanden rondes: ~36.000 advertenties, ~340.000 prijswaarnemingen):

- **Vergelijkingsprijzen één keer per opbouw.** De flips, de voorraad in Mijn
  flips en Marktprijzen gebruiken dezelfde vergelijkingsadvertenties; die
  werden apart gelezen en herkend, en Marktprijzen deed dat opnieuw bij elke
  paginaweergave. Eenmaal herkende titels, groepsets en specs worden onthouden
  (de uitkomst hangt alleen van de tekst af), dus na een ronde kijkt een
  opbouw alleen naar wat nieuw is. De fietscomputerpagina serveren ging van
  1,5 s naar 0,2 s, de eerste opbouw na een ronde van 5 s naar 1 s, en beide
  dashboards schrijven na een ronde (`koopjes.py`) van 7 s naar 1,8 s — met
  precies dezelfde pagina's als uitkomst.
- **Alle computers laadt als je hem opent.** Die tab is meer dan de helft van
  de pagina (met eigen knoppen op elke rij), en de browser las hem bij elke
  keer laden terwijl je meestal naar Flips kijkt. De live pagina haalt hem nu
  van de server de eerste keer dat je de tab aanklikt (het adres
  `/paneel?markt=...&naam=alle`); de geschreven `dashboard.html` heeft nog
  alles. De pagina laadt in ongeveer 1 s in plaats van 2,5-3,5 s (de
  horlogepagina: 1,3 s in plaats van 3,4 s). Een markering of notitie die je
  zet terwijl de tab laadt, komt erop zodra hij er is, en na controleer komt
  hij terug met dezelfde zoekopdracht en plek.
- **Typen in het zoekveld** filtert zodra je even stopt (0,15 s), in plaats
  van bij elke toets door elke rij te gaan.
