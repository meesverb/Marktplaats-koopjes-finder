# Racefietsen — `/racefietsen` (`racebikes.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

Start `python dashboard.py --serve` en open `/racefietsen`. Werk de weergave
**Te beoordelen** af: per fiets favoriet (**f**), weg met een reden (**w**,
**1**-**6**), een bod vastleggen (**b**) of een notitie (**n**). Twijfel je:
**c** controleert de advertentie opnieuw, **d** maakt een dossier om aan
Claude te geven. Klopt het model niet, dan kies je een ander (**m**).

Alle racefietsen uit `koopjes.db` staan op één live pagina (categorie
racefietsen, welke zoekopdracht ze ook vond: `racefietsen`, `giant-defy`,
`ultegra-6700`). Het rapport per ronde (`racefiets_report.html`) blijft zoals
het is: zonder knoppen, alleen die ene ronde.

**Actief** betekent hier: niet verdwenen en gezien binnen 8 dagen van de
nieuwste racefiets — ruimer dan de 3 dagen van de computers, omdat overdag
alleen de nieuwste pagina's langskomen en een oudere fiets pas door de
zondagronde (`week`) weer gezien wordt.

## De kaart

Per fiets drie foto's (alles wat de zoekresultaten geven), prijs en soort
prijs, afstand, de specs op één regel (maat, materiaal, groepset, remmen,
jaar, wielen, gewicht, staat), de tekst van de verkoper (*beschrijving*; de
volledige tekst waar `--detail-lookup` hem ophaalde) en twee oordelen naast
elkaar:

- **flip** — de verwachte verkoopprijs min wat hij je kost, uit de andere
  advertenties van **hetzelfde fietsmodel** (`bike_identity.py`): elke
  racefiets van de laatste 180 dagen, verdwenen meegerekend. Zie
  *Fietsmodellen* hieronder voor wat een model is en hoe de vergelijking een
  trede grover gaat als er te weinig zijn.
  - Binnen de gekozen trede: zijn er minstens 3 **snel verkocht** — verdwenen
    binnen 7 dagen na de eerste keer gezien, of gereserveerd en daarna
    verdwenen — dan is de schatting de mediaan van hun laatste prijs, zonder
    afdingfactor (ongeveer wat betaald is; de echte prijs is niet bekend, de
    kaart zegt dat). Anders de mediaan van alle vraagprijzen × 0,875, met
    "(nog geen snelle verkopen)".
  - Verdwenen staat pas vast na een volledige crawl (de zondagronde `week`,
    zie "Everything in a category" in [zoeken.md](zoeken.md)), dus de eerste
    weken zijn er weinig snelle verkopen.
  - De kaart zegt waar de fiets aan hangt en hoe hij zich verhoudt, bijv.
    *Trek Domane SL6 · 6 snel verkocht (≤7 d), mediaan €620 · 14 te koop,
    mediaan €690 — deze €480 (−23% t.o.v. de schatting)*; *vergeleken met N
    fietsen* toont de snelle verkopen en de goedkoopste andere, met links.
  - Geen model, geen schatting ("model niet herkend", "te weinig
    vergelijkbare fietsen") — nooit een mediaan van alle racefietsen (de
    eigenaar, 30-09-2026: een carbon fiets van 2024 is niet te vergelijken
    met een van 2014). Er gaan geen kosten af: onderdelen en reizen reken je
    per fiets uit op `/flips`.
- **upgrade** — `upgrade.find_upgrades()` tegen je eigen fiets in
  `mijn_fiets.md`, precies als de tab Upgrade van het rapport: beter dan de
  jouwe met meer dan de marge, binnen budget, maat niet fout. Een fiets
  zonder bekend bouwjaar is nooit een groene upgrade: de score heeft dan geen
  leeftijd om af te trekken, en een oude fiets met goede onderdelen leek nieuw
  ("bouwjaar onbekend — vraag het jaar na"). Zonder leesbare `mijn_fiets.md`
  zegt de pagina waarom er geen oordeel is.

Plus de **waardescore** (geschatte waarde / prijs). Niet de dealscore: die
hoort bij het rapport.

## Dossier voor Claude — `dossier.py`

De kaart toont een deel van wat er over een fiets bekend is. De knop
**dossier** naast *controleer* (toets **d**) zet alles op een rij als één
Markdown-tekst om in een gesprek met Claude te plakken, met de vragen
bovenaan: is het een goede deal (als flip en als upgrade), wat moet er
vervangen worden en wat kost dat ongeveer (met bronnen, geen verzonnen
prijzen), een analyse van de vergelijkingsfietsen, en wat je de verkoper
vraagt.

**Ophalen.** Net als controleer haalt hij eerst de advertentiepagina op — één
verzoek per klik, dezelfde regels (`recheck.py`) — en bewaart hij wat
controleer bewaart, plus wat een ronde bewaart bij een opgehaalde pagina: de
volledige omschrijving (`details_fetched_at`, net als het opzoeken van het
bouwjaar), de framehoogte uit de *Kenmerken* als de zoekresultaten er geen
hadden, en materiaal en remmen uit de *Kenmerken* waar de zoekresultaten
niets zeiden (`spec`, bron `marktplaats`). Zonder dat zou een ronde een
opgehaalde pagina nooit opnieuw ophalen, en bleef een fiets zonder maat in
de zoekresultaten "maat onbekend". De schatting en het upgradeoordeel in het
dossier (en daarna op de kaart) gebruiken ze dus al.

De pagina geeft ook elke foto (de zoekresultaten geven er drie; hier de
grootste maat die de pagina noemt), de rest van de *Kenmerken*, particulier
of niet en hoe lang op Marktplaats, of verzenden kan, en de biedingen met hun
datum; die gaan alleen in het dossier, niet in de database. Namen van
verkoper en bieders gaan er helemaal niet in. Lukt ophalen niet (geen
verbinding, verdwenen, paginastructuur veranderd), dan komt het dossier toch,
uit de database, en zegt dat bovenaan.

**Wat erin staat:**

- de advertentie: prijs met wat voor prijs het is, de vraagprijs alleen waar
  die zeker is (van de net opgehaalde pagina, of een prijs zonder bieden; een
  minimumbod of lopend bod heet nooit vraagprijs), biedingen, gereserveerd,
  plaats en afstand, staat, maat, dagen online, prijsverloop, weergaven en
  likes; tijden op je eigen klok;
- de *Kenmerken* en wat de koopjesfinder uit de tekst las, de omschrijving,
  de fotolinks;
- welke fiets het is (model en waar dat vandaan komt, jaar, materiaal,
  groepset, remmen);
- de schatting precies als op de kaart (verkoopprijs, trede, mediaan, snelle
  verkopen, flip, waardescore, afdingfactor), het upgradeoordeel met de
  kwaliteitsscore per onderdeel naast je eigen fiets;
- de tabel uit `mijn_fiets.md` met je maat en budget, je markering, notitie en
  biedingen, de onderdeelprijzen uit je eigen flips (`/flips`, soort
  *onderdeel*: wat je betaalde of schatte);
- de **vergelijkingsfietsen**: een samenvatting (spreiding, snel verkocht, nog
  te koop, per jaar; over allemaal) en een CSV met elke fiets van de trede
  van de schatting plus de rest van hetzelfde model en dezelfde modelfamilie
  (alle jaren, alle materialen; `in_schatting`, `relatie`), hooguit 300. Zijn
  het er meer, dan eerst elke snelle verkoop van de schatting, daarna de rest
  naar verhouding over de groepen verdeeld (elk minstens één waar er ruimte
  is), elke groep gelijkmatig over zijn prijzen (niet alleen de goedkoopste).
  Per fiets prijs, jaar, materiaal, groepset, versnellingen, remmen, maat,
  staat, eerst en laatst gezien, verdwenen, dagen online, gereserveerd, snel
  verkocht en link.

Het rekent niets nieuws; het zet alleen meer naast elkaar. De pagina zet het
op het klembord en toont het in een venster met *kopieer* en *bewaar als
.md*. Hetzelfde op de commandoregel:

```bash
python dossier.py m2449549680                 # uit de database, geen verzoek
python dossier.py m2449549680 --ophalen --uit dossier.md   # eerst de pagina ophalen, UTF-8-bestand schrijven
```

## Fietsmodellen

Elke fiets hangt aan een **model**: merk + model + *uitvoering*, bijv. "Trek
Domane SL6", "Giant Defy Advanced 2", "Canyon Aeroad CF SLX 8". Waar het
vandaan komt, de eerste die past:

1. **je eigen koppeling** (`bike_link`, migratie 19), gezet op de kaart;
2. een **regel** die je toepaste (zie *Regels* hieronder);
3. een **referentiemodel** uit `reference_bikes.csv` waarvan het patroon
   past — tenzij de titel meer zegt: sommige referentiemodellen dekken een
   hele lijn ("Trek Domane", "Giant Defy (overig)"), en dan is "Trek Domane
   SL6" uit de titel het model; een preciezer referentiemodel ("Giant Defy
   Composite 1") blijft;
4. merk + model + uitvoering uit de titel: het merk zoals de slapers het
   kennen, het modelwoord uit `reference_bike_catalog.csv` of het woord na het
   merk ("Koga Kinsei"), en als uitvoering de 1-3 woorden direct erna die er
   een lijken (`sl`, `slr`, `al`, `cf`, `slx`, `advanced`, `pro`, `comp`,
   `sport`, `elite`, `expert`, `disc`, `team`, `ltd`, een getal van een of
   twee cijfers, letters met een cijfer zoals `sl7`) — niet "105" (groepset),
   geen jaartal, en het stopt bij het eerste andere woord. Een getal met een
   eenheid erachter ("28 inch", "56 cm"), een decimaal vanaf 20 ("55.5") en
   een modeljaarcode ("MY16") zijn maten of jaren, geen uitvoering; "2.0"
   telt als "2", `disc` gaat altijd achteraan en telt niet mee in de drie
   woorden ("Advanced Disc 1" = "Advanced 1 Disc"), en "Tcr-team" is "TCR
   Team".

Modellen vergelijken zonder spaties en zonder wat tussen haakjes staat ("SL
6" = "SL6", "Trek Émonda (overig)" = "Trek Emonda"). Het jaar komt uit de
tekst of de titel, of uit je eigen koppeling, die voorgaat — ook voor het
upgradeoordeel, zodat de leeftijdskorting telt.

De vergelijking wil **minstens 5** advertenties per trede en gaat anders een
trede grover; de kaart zegt welke:

1. hetzelfde model + uitvoering, jaar ±2 (beide bekend) — *model, ±2 jaar*
2. hetzelfde model + uitvoering waar een van beide geen jaar heeft, plus die van 1 — *model*
3. hetzelfde merk + model (elke uitvoering), zelfde materiaal, jaar ±2 — *modelfamilie, ±2 jaar*
4. hetzelfde merk + model, zelfde materiaal, zelfde tijdperk als een jaar
   ontbreekt (schijf- of velgrem, elektronisch of niet, versnellingen als
   beide het zeggen) — *modelfamilie, zelfde tijdperk*
5. elk model, zelfde materiaal, groepsetniveau en remmen, jaar ±2 — *zelfde opbouw, ±2 jaar*
6. alleen als de fiets zelf jaar noch remmen noemt: hetzelfde merk + model
   van elk jaar — *onzeker*, met de spreiding, nooit groen.

Heeft geen trede er 5, dan loopt de ladder nog eens met 3 en krijgt de trede
*(weinig)*. De ±2 jaar is de generatie; er worden geen generatiejaren
opgezocht of verzonnen (CLAUDE.md).

**Corrigeren op de kaart**, onder *gekoppeld aan …*:

- **klopt** — het model klopt: het wordt een van je modellen (`bike_model`)
  en de koppeling is gecontroleerd (*✓ gecontroleerd*);
- **ander model** (toets **m**) — een zoekveld en een scrollende lijst van
  alle modellen met hoeveel advertenties eraan hangen; kies er een om te
  koppelen, of typ een nieuw ("merk model uitvoering", bijv. "Koga Kinsei
  Pro": 3-80 tekens, merk plus minstens één woord) om het te maken en te
  koppelen;
- **bouwjaar** — jouw jaar (1970 tot volgend jaar), leeg om het weg te halen;
- **ontkoppelen** — terug naar wat de advertentie zegt.

Een correctie rekent alleen die fiets opnieuw (ongeveer 0,1 s, ook met 14.000
fietsen); de vergelijking van de andere fietsen van het oude en nieuwe model
wordt na de volgende ronde bijgewerkt, de melding zegt dat.

**Regels.** Koppel je 3 advertenties die als hetzelfde model herkend werden
("Trek Domane") aan hetzelfde model van jou ("Trek Domane AL 2"), dan stelt de
weergave **Modellen** bovenaan een regel voor — "advertenties die als *Trek
Domane* herkend worden → *Trek Domane AL 2*?" — en zegt de knop *Modellen (1
voorstel)*. **toepassen** laat hem werken voor elke advertentie die zo herkend
wordt, verdwenen meegerekend (`bike_rule`, migratie 20; de kaart zegt *eigen
model via een regel*); **nee** wordt onthouden. Je eigen koppeling op één
advertentie gaat nog steeds voor een regel. Toegepaste regels staan onder de
voorstellen, elk met **weghalen**. *klopt* op het herkende model is geen
correctie en doet nooit een voorstel.

## Het bouwjaar van de waarschijnlijke koopjes

Het jaar staat zelden in de titel (ongeveer 6 op 100), en zonder blijft een
fiets op een grove trede. Na de zoekopdrachten halen de rondes `overdag` en
`nacht` (`"year_budget": 20` in `schedule.json`) de advertentiepagina op van
hooguit 20 racefietsen die actief zijn, een prijs hebben, niet gereserveerd
of weggezet zijn, geen bekend jaar hebben, goedkoop lijken — minstens 15%
onder de schatting van hun trede, of onder de mediaan op de trede *onzeker* —
en waarvan de pagina nooit eerder is opgehaald; goedkoopste eerst, met de
gewone 1,5 s tussen verzoeken, stoppen bij een 403.

De volledige omschrijving wordt bewaard (dezelfde kolom die `--detail-lookup`
vult), en `/racefietsen` en het upgradeoordeel lezen het jaar daaruit na de
volgende ronde. Net als bij een ronde ook de framehoogte uit de *Kenmerken*
als de zoekresultaten er geen hadden, en materiaal en remmen waar die niets
zeiden. Ook de weergaven en likes op de pagina worden bewaard (zie "Weergaven en
likes" in [live.md](live.md)). Met de hand: `python racebikes.py
plan 20` toont welke fietsen het zouden zijn, `python racebikes.py jaar 20`
haalt ze op (hooguit 20).

## Weergaven, filters en toetsen

- **Te beoordelen** — geen markering, geen bod, niet gekocht, niet
  gereserveerd; markeer een fiets en hij verdwijnt uit deze weergave, zo werk
  je de lijst af.
- **Favorieten**, **Mijn biedingen** (met biedingen op verdwenen fietsen
  eronder), **Mijn flips** (je eigen fietsen van `/flips`: fase, gekocht voor,
  wat erin zit, doelprijs, winst — verwacht op het midden van het doel voor
  een lopende; bewerken op `/flips`), **Alle** (zonder wat je wegzette),
  **Weggezet**.
- **Modellen** — de lijst van alle modellen: je eigen (ook zonder
  advertenties), de referentiemodellen en de herkende, met *te koop*,
  *gekoppeld* (180 dagen, verdwenen meegerekend), *snel verkocht*, de mediaan
  van de snelle verkopen, de mediaan vraagprijs en de laagste prijs te koop.
  Een zoekveld, klik op een kolom om te sorteren, 200 rijen tegelijk getekend
  terwijl je scrolt, en een veld om **een nieuw model toe te voegen**. Klik op
  een model om zijn fietsen te zien.
- **Onderdelen** — reserves voor je flips: losse onderdelen die de rondes
  toch al tegenkomen, per soort — cassettes, kettingen, zadels, pedalen,
  banden, binnenbanden, wielen, kettingbladen/cranks, derailleurs, shifters,
  remmen, groepsets, sturen/stuurpennen, zadelpennen, stuurlint,
  bidonhouders (`spares.KINDS`). Zet de soorten aan waar je reserves van wilt
  (bewaard in `koopjes.db`, tabel `setting`; eerst cassettes, kettingen,
  zadels en pedalen); per soort de goedkoopste die nu te koop zijn (hooguit
  40), met foto, prijs, plaats, afstand, en favoriet / wegzetten / je bod
  zoals bij de fietsen. Een soort telt als de titel hem noemt ("zadel", niet
  "zadelpen"); buiten de categorie fietsonderdelen telt een titel die een hele
  fiets is ("racefiets", "maat 56") niet, en evenmin een gezocht-advertentie,
  gereedschap direct na het onderdeel ("cassette sleutel", "kettingzweep";
  "cassette met afnemer" is nog een cassette), een houder ("houder voor
  stuur") of schoenen. **Er is geen zoekopdracht voor toegevoegd** (keuze van
  de eigenaar, 02-10-2026): de onderdelen komen uit wat de rondes toch vinden
  — tussen de racefietsen, de zoekopdrachten met `category: alle`
  (giant-defy) en powermeter — dus het zijn er weinig. Voor meer: zet een
  zoekopdracht in de categorie `fietsonderdelen` in `schedule.json` (een
  nachtslot met `pages: 2` is ~2 verzoeken per zoekopdracht per nacht); dat
  zijn meer verzoeken aan Marktplaats, dus eerst afwegen.
- **Patronen** — weergaven en likes van racefietsen (zie "Weergaven en likes" in
  [live.md](live.md)).

**Filters:** zoeken (titel, specs, plaats, je notitie), volgorde (nieuwste,
beste flip, beste waardescore, beste upgrade, dichtstbij, goedkoopste),
framemaat (standaard je maat ± 2 cm, met *maat onbekend* aan), maximumprijs,
maximumafstand, *gereserveerd*, *alleen nieuw*. De pagina onthoudt je weergave
en filters (per browser).

**Toetsen:** **j**/**↓** volgende, **k**/**↑** vorige, **f** favoriet, **w**
niet waard, **1**-**6** wegzetten met een reden, **u** terugzetten (de fiets
onder de cursor; heeft die geen markering — in Te beoordelen verdwijnt een
gemarkeerde fiets meteen — dan maakt hij je laatste markering ongedaan en zet
die fiets terug), **b** bod invullen, **n** notitie, **spatie** omschrijving,
**o** openen op Marktplaats, **c** controleer, **d** dossier voor Claude,
**m** ander model, **Esc** uit een veld.

De redenen om een fiets weg te zetten zijn *niet waard*, *gereserveerd*,
*niet doorverkoopbaar*, *te hoge vraagprijs*, *slechte staat* en *geen
racefiets* (`marks.BIKE_REASONS`), bewaard in `listing_mark` net als de
markeringen van de computers, zodat je later kunt terugzien welke fietsen je
afwees en waarom. Ook hier komt een weggezette fiets terug als zijn prijs
onder die van dat moment zakt — behalve *geen racefiets*: een frame of e-bike
wordt geen racefiets door goedkoper te worden.

## Snelheid

Met opzet snel: het zware deel (vergelijkingsfietsen, upgradescores) rekent
één keer per ronde en de server onthoudt het; de pagina krijgt de fietsen als
JSON en tekent er 40 tegelijk, meer terwijl je scrolt; een klik stuurt alleen
die ene fiets terug. Gemeten op een testdatabase met 2000 fietsen (Chromium):
de pagina laadt in ongeveer een halve seconde, een fiets wegzetten kost ~150
ms. Met modellen (01-10-2026): 2000 fietsen, pagina ~1,2 s bij de eerste keer
(de berekening, 0,8 s) en een modelcorrectie 80-110 ms; 14.000 fietsen, de
berekening ~5,6 s één keer per ronde en een correctie 110-150 ms.
