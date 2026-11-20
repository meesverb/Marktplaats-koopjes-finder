# Sporthorloges — `dashboard_horloges.html` (`markets.py`, `watches.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
python koopjes.py run horloges            # alle sporthorloges nu (15-20 minuten); opent bij een nieuwe flip
python dashboard.py --markt sporthorloges # dashboard_horloges.html opnieuw uit koopjes.db
python watches.py                         # per model en de flips, in de console
```

Live op `http://127.0.0.1:8765/horloges` met `python dashboard.py --serve`,
met dezelfde knoppen als bij de fietscomputers (zie [live.md](live.md)).

Een tweede markt naast de fietscomputers, op dezelfde manier gebouwd: elk
Garmin-, Polar-, Suunto- en Coros-horloge op Marktplaats, het model herkend
uit de titel, de flips berekend tegen de vraagprijzen van hetzelfde model, en
een eigen dashboard. Smartwatches (Apple, Samsung, Fitbit, Huawei) zijn een
andere markt en worden (nog) niet gevolgd; pikt een zoekopdracht er een op,
dan staat hij in Uitgefilterd als "ander merk".

## Zoekopdrachten en dashboard

- **De zoekopdracht** `sporthorloges` in `schedule.json`: "garmin" in de
  categorieën `sporthorloges`, `smartwatches` en `activity-trackers` — daar
  staan de horloges; bandjes en kabels staan vooral in telefoon- en
  wearablecategorieën, en `activity-trackers` heeft ook Fenixen en
  Forerunners die verkopers daar zetten. 1707 advertenties op 28-09-2026, 58
  pagina's. In het nachtslot (volledig, zodat verdwenen advertenties voor
  Patronen gemarkeerd worden) en overdag in het slot `computers` (2
  pagina's). Een eigen `"bid_lookup": "fast"`, dag en nacht: ongeveer 300 van
  die advertenties zijn "bieden" zonder prijs, en biedingen tellen hier, dus
  elke wordt opgevraagd (~300 extra verzoeken per nacht; overdag alleen die op
  de 2 nieuwste pagina's). De prijs leest dan "3 biedingen · min. €100 ·
  opgehaald dd-mm-yyyy HH:MM" of "nog geen bod", en blijft staan tot de
  volgende opvraging (migratie 11: `listing.bid_count`, `bid_minimum`,
  `bids_checked_at`).
- **De zoekopdrachten** `polar`, `suunto` en `coros`: dezelfde drie
  categorieën, alleen in het nachtslot, ook met biedopvragingen. 214, 84 en
  36 advertenties op 28-09-2026 (samen 13 pagina's); met ~5 nieuwe per dag zou
  een dagronde steeds dezelfde advertenties en biedingen ophalen. De
  duikcomputers van Suunto staan meestal in de categorie `duiken` en blijven
  buiten.
- **De modellen** in `reference_sport_watches.csv` (zie onder): 81
  Garmin-modellen, van de Forerunner 30 en Venu Sq tot de Fenix 9 Pro en MARQ,
  plus 18 Polar-, 19 Suunto- en 13 Coros-modellen. Op de volledige
  Garmin-crawl noemen 1263 van 1707 titels er een; de rest zijn vooral
  bandjes, kabels en andere merken. Van de 327 advertenties uit `polar`,
  `suunto` en `coros` (28-09-2026) noemen er 192 een Polar-, Suunto- of
  Coros-model (4 meer een Garmin); de meeste andere zijn oudere modellen
  zonder bron (Polar M400, V800, M600, Loop; Suunto Core, Traverse), die als
  "horloge, model onbekend" staan.
- **Het dashboard** `dashboard_horloges.html`: dezelfde pagina als die van de
  fietscomputers — Flips, Te beoordelen, Favorieten, Mijn biedingen, Mijn
  flips, Alle horloges, Weggezet, Marktprijzen, Patronen en Uitgefilterd —
  zonder Upgrades (er is geen eigen horloge om mee te vergelijken), Vinted en
  de functiescore. `koopjes.py` schrijft hem na elke ronde. Een aankoop
  onthoudt zijn markt (migratie 10, `trade.market`), zodat de Mijn flips van
  elk dashboard de zijne toont. Aankopen van daarvoor hebben geen markt en
  horen bij de fietscomputers, tenzij hun model een horloge is.
- **De berekening** is die van de fietscomputers
  (`computers.apply_computer_signals()`, zie
  [fietscomputers.md](fietscomputers.md)) met de horlogecatalogus en dezelfde
  `computer_scoring.json` — dezelfde aangenomen 0,875 en €3 kosten — met
  vergelijkingsmateriaal uit alleen de drie horlogecategorieën. `watches.py`
  houdt wat eigen is aan horloges: de categorieën, en wat een titel zonder
  bekend model is (`classify_unknown()`). Een Garmin-, Polar-, Suunto- of
  Coros-horloge met onbekend model blijft zichtbaar in Alle horloges ("Te koop
  Garmin horloge" kan een slaper zijn, en "Suunto Traverse GPS-horloge +
  hartslagband" is een horloge met een band); bandjes, laders, andere merken
  zoals Apple, en producten die geen horloge zijn zoals de Garmin Index-weegschaal
  of een Polar-fietscomputer gaan naar Uitgefilterd, elk met de reden.
  `markets.py` zet de twee markten naast elkaar: categorieën, catalogus,
  bestand, welke tabs.

## De flips met zorg lezen

Uitvoeringen delen een rij (5/5S, Solar, Sapphire, Music, 43/47/51 mm); een
flip vergelijkt met dezelfde uitvoering als er minstens 3 zijn (zie "Per
uitvoering eerst" in [fietscomputers.md](fietscomputers.md)), maar een titel
die zijn uitvoering niet noemt, geldt als de gewone, en met te weinig van
dezelfde uitvoering mengt de mediaan van het hele model ze nog — de band onder
elke winst laat zien hoe breed de spreiding is, en de regel onder de
verkoopprijs welke mediaan het is. De 0,875 is voor horloges niet gemeten;
Patronen meet hem zodra er 20 snel verdwenen advertenties van de markt zijn
(een paar weken nachtrondes).

Wat de eerste crawl zei, één momentopname, zelfde methode en dag voor beide
("garmin,wahoo" in de categorie fietscomputers ter vergelijking):

| | Bekend model | Flips > €0 | Nog winst bij de lage schatting | … waarvan > €25 |
| --- | --- | --- | --- | --- |
| fietscomputers | 216 | 14 | 10 (4,6 per 100) | 6 |
| sporthorloges (alleen Fenix/Forerunner/Epix) | 605 | 96 | 46 (7,6 per 100) | 15 |

## De catalogus — `reference_sport_watches.csv`

Eén rij per model, dezelfde vorm als `reference_bike_computers.csv` — een
regex `pattern`, en de volgorde in het bestand is de matchvolgorde, dus
"Fenix 7 Pro" komt vóór "Fenix 7" — en hij laadt met
`computers.load_catalog(pad)`.

Kolommen: `merk`, `model`, `pattern`, `introductiejaar`, `nieuwprijs_eur`,
`prijs_bron`, `nieuwprijs_usd`, `kaarten_op_horloge` (`ja`/`nee`/leeg),
`extra_opmerkingen`, `bron_url`.

- **Een europrijs alleen waar een bron euro's geeft**: de Benelux-persberichten
  van Garmin (garmin.prezly.com, "adviesprijs"; alle ~110 gelezen via de
  sitemap), een vergelijkingstabel van DC Rainmaker die EUR noemt, of voor de
  Fenix E het lanceringsartikel van Android Planet. `nieuwprijs_usd` is de
  Amerikaanse prijs van DC Rainmaker en wordt nooit omgerekend. DC Rainmaker
  werkt zijn tabellen bij in de loop van de tijd (de Vivoactive 3 staat er op
  $129), dus een tabelprijs telt alleen waar een andere bron het eens is;
  anders noemt de opmerking het en blijft het veld leeg.
- **Geen bron, geen rij.** Tactix, Quatix, Approach S12/S42/S70 en Descent
  Mk3/G1 hadden geen bron met jaar of prijs; ze staan als "horloge, model
  onbekend". Hetzelfde voor oudere Polar (M400, V800, M600, A360, RC3), Suunto
  (Core, Traverse, Ambit 1/2) en de Coros Apex Pro. De Polar Loop ontbreekt
  bewust: verkopers noemen zowel de Loop van 2025 als de Loop 2 van 2015 "Loop
  gen 2".
- **Polar, Suunto en Coros komen uit de reviews van DC Rainmaker**: het jaar
  uit de review (gepubliceerd bij de lancering), de prijs alleen zoals de
  reviewtekst hem noemt — "$229/229EUR" geeft beide, "$449USD" alleen de
  dollarprijs. Patronen eisen het merk ervoor ("Polar Vantage V2", "Suunto
  Race", "Coros Pace 3"), omdat "Race", "Pace" en "Vantage" alleen te weinig
  zeggen.
- **`kaarten_op_horloge` alleen waar de bron het zegt.** Het is niet de kolom
  `kaarten` uit het fietscomputerbestand (`routeerbaar`, `basiskaart`, ...);
  dat vocabulaire zegt iets wat de bronnen voor horloges niet zeggen.
- **Uitvoeringen delen een rij** waar het prijsniveau gelijk is (5/5S,
  265/265S, Music-edities, Solar/Sapphire); de flip scheidt ze waar het kan op
  de titel (`title_variant()`). Waar het niveau verschilt, hebben ze een eigen
  rij (Fenix 5X, Fenix 6 Pro, Fenix 7 Pro, Epix Pro, MARQ Gen 2). Een "Fenix 6S
  Sapphire" zonder "Pro" landt op Fenix 6; of elke Sapphire-editie een Pro was,
  is niet nagegaan.
- **Forerunners van twee cijfers hebben de naam nodig**: "Forerunner 55" of
  "FR55", nooit "Garmin 55" — te makkelijk een maat in mm.

`tests/test_sport_watches.py` controleert bronnen, vaste woorden,
overschaduwing en een set echte titels; `tests/test_watches.py` de
flipberekening, het dashboard, de live versie en Mijn flips per markt.
