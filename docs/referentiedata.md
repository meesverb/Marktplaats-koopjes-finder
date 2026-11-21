# Referentiedata — de eigen prijs- en modellendatabase

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

```bash
python racefiets_jev.py --query "giant defy" --reference-file reference_bikes.csv
python check_reference_overlaps.py --file reference_bikes.csv   # overschaduwt een patroon een ander?
python reference_overview.py                                    # de luidsprekerreferentie als doorzoekbare pagina
python check_hifi_brand.py "Mission"                            # welke luidsprekers een merk heeft
```

De CSV-bestanden waartegen advertenties herkend en vergeleken worden, en de
hulpscripts om ze bij te houden. Elk staat in git met `git add -f` (de
`.gitignore` sluit `*.csv` uit), elke rij heeft een bron, en een nieuwprijs
staat er alleen als een bron hem in euro's gaf (CLAUDE.md: geen verzonnen
marktfeiten). De catalogi van fietscomputers en sporthorloges staan bij hun
markt: [fietscomputers.md](fietscomputers.md) en [horloges.md](horloges.md).

| Bestand | Wat | Gebruikt door |
| --- | --- | --- |
| `reference_prices.csv` | 43 luidsprekers, met nieuwprijs en een Denon SC-N10 als basislijn | `--reference-file` (de standaard) |
| `reference_bikes.csv` | fietsmodellen: de Defy-familie, upgradedoelen en modelfamilies | `--reference-file`, herkenning op `/racefietsen`, de taxatie |
| `reference_bike_accessories.csv` | fietscomputers en powermeters | `--reference-file` voor die zoekopdrachten |
| `reference_bike_catalog.csv` | één rij per merk/model/modeljaar met specs en nieuwprijs | merken (slapers, ongeherkende lijst), modelnamen op `/racefietsen` |
| `reference_price_history.csv` | je eigen waargenomen vraagprijzen (niet in git) | "2e-hands gem." in de dealscore |

## Vergelijken met nieuwprijzen — `--reference-file`

Er is geen gratis database van "elk model met zijn nieuwprijs en een score",
voor fietsen of iets anders. In plaats daarvan houd je met `--reference-file`
je eigen bij — een gewone CSV die meegroeit, zonder kosten of API-sleutel:

```csv
pattern,label,original_price_eur,specs,score,better_than_baseline
Canyon Ultimate CF SLX 8,Canyon Ultimate CF SLX 8 (2021),4000,"11.7 kg, Ultegra Di2",8.5/10,1
```

- `pattern`: regex (hoofdletterongevoelig), gematcht tegen titel en
  omschrijving samen. Zet specifiekere patronen eerder in het bestand — de
  eerste match wint.
- `label`: wat er getoond wordt bij een match.
- `original_price_eur`: wat hij nieuw kostte (optioneel — leeg als onbekend).
- `specs`: de objectieve specs die het vergelijken waard zijn (vermogen,
  gevoeligheid, gewicht, wat ertoe doet voor die categorie) — optioneel, vrije
  tekst.
- `score`: een beoordeling die je wilt tonen (optioneel, vrije tekst).
- `better_than_baseline`: `1` als dit model beter is dan waar je tegen
  vergelijkt (bijv. de rij van je eigen spullen) — voor de filtertab "Beter
  dan referentie" in het rapport. Anders `0`/leeg.

Bij een match toont het rapport het label, de nieuwprijs en welk percentage
daarvan nu gevraagd wordt, de specs en de score — in eigen kolommen
(Referentie / Nieuwprijs / Specs), plus een paars label "BETER" als
`better_than_baseline` gezet is. Zie `reference_prices.example.csv` voor het
precieze formaat (de waarden daarin zijn plaatsvullers, geen echte prijzen).
De nieuwprijs van een model opzoeken gaat betrouwbaarder één model tegelijk dan
in bulk gegokt.

## Fietsen hebben hun eigen referentiebestanden

`reference_prices.csv` gaat over luidsprekers; een fietspatroon daarin zou
tegen luidsprekertitels gematcht worden. Wijs voor fietszoekopdrachten
`--reference-file` naar een van deze:

```bash
python racefiets_jev.py --query "giant defy" --reference-file reference_bikes.csv
python racefiets_jev.py --query "garmin edge" --reference-file reference_bike_accessories.csv
```

- `reference_bikes.csv` — de Giant Defy-familie (de eigen fiets is de rij met
  "Baseline") plus veelvoorkomende upgradedoelen (Canyon Endurace, Specialized
  Roubaix, Trek Domane), gevolgd door één rij per modelfamilie die vaak
  ongeherkend in `lijsten/zonder_referentie.txt` stond (Giant TCR, Trek
  Madone, Cube Attain, Koga-Miyata, ...). Die familierijen noemen geen
  nieuwprijs — een familie spant uitvoeringen en jaren — en vullen
  `frame_material` alleen waar de naam het zelf beslist (Advanced, ALR, CAAD,
  GTC, C:62, "Carbon"); hun bron is een representatieve rij uit
  `reference_bike_catalog.csv`, met de aantallen per materiaal in `specs`.
  Daaronder 226 rijen, één per modellijn uit die catalogus die geen rij
  hierboven herkent (merk + eerste woord van de modelnaam: BH Quartz, Felt
  F75, Cervélo R5, Trek Silque, Scott Contessa, ...), plus "Giant Defy
  (overig)" voor een Defy die de onderzochte rijen niet kunnen plaatsen. Die
  zijn alleen voor herkenning: het merk moet vóór de lijn in de titel staan
  ("Terra" en "Supreme" zijn fietsen van meerdere merken), en ze noemen geen
  nieuwprijs en geen `frame_material`. Catalogewoorden die gewoon Nederlands of
  een getal in een titel zijn (Pinarello "MAAT", Cannondale "700", Bianchi
  "1885") en tikfouten in de catalogus van een lijn die al een rij heeft,
  kregen geen rij.
- `reference_bike_accessories.csv` — fietscomputers (Wahoo, Garmin) en
  powermeters. Die staan er met opzet **niet** in het fietsbestand: de eerste
  passende rij levert de nieuwprijs waar de dealscore tegen vergelijkt, dus een
  rij "Garmin Edge 530" daar zou een fiets van €900 die zijn computer noemt
  laten lijken op 300% van een nieuwprijs van €299,99.

Beide bestanden hebben na de gewone zes drie optionele kolommen: `kind`
(`bike`, `computer`, `powermeter`, ...), `brand` en `source_url`. Het script
negeert ze; de SQLite-import (`--db`) bewaart ze in de tabel `model`. Elke rij
heeft een bron, en `original_price_eur` staat er alleen waar een bron een
europrijs geeft — een modeljaar of uitvoering waarvan de prijs niet te vinden
was blijft leeg in plaats van omgerekend uit dollars of gegokt.

`reference_bikes.csv` heeft nog een kolom, `frame_material` (`carbon`,
`aluminium`, `staal`, `titanium` of leeg), alleen gevuld waar de eigen
onderbouwde specs van de rij het materiaal noemen. De taxatie gebruikt hem:
een advertentie die op de aluminium rij "Giant Defy 0-5" past is geen
vergelijking voor een carbon Defy Composite, ook als de tekst nooit "alu" zegt.

## De fietscatalogus — `reference_bike_catalog.csv`

Een derde fietsbestand, en een ander soort: geen regex-patronen om titels
tegen te matchen, maar één rij per merk / model / modeljaar met de specs en de
nieuwprijs. De patroonbestanden kunnen dat niet houden — elke "Defy Advanced 2"
van 2016 tot 2025 zou één patroon delen, en met eerste-match-wint zou alleen de
eerste rij ooit gebruikt worden — en daarom kan hij ook niet aan
`--reference-file` (de run waarschuwt en herkent niets). Alleen de kolom
`brand` wordt vanzelf gelezen: `sleepers.py` sluit er advertenties mee uit die
een merk noemen, en de lijst ongeherkende advertenties van `koopjes.py`
groepeert erop; `bike_identity.py` haalt er de modelnamen per merk uit. De rest
— specs en nieuwprijzen per modeljaar — is naslag om met de hand op te zoeken;
de taxatie leest het (nog) niet.

Kolommen: `brand`, `model`, `model_year`, `seen_date`, `category`,
`frame_material`, `groupset`, `electronic`, `speeds`, `brake_type`,
`weight_kg`, `new_price`, `currency`, `market`, `price_basis`, `specs` (de
volledige specslijst zoals de bron hem geeft), `source_url`,
`spec_source_url`.

Waar het vandaan komt, per merk:

| Merk | Specs en modeljaar | Prijs |
| --- | --- | --- |
| Giant | giant-bicycles.com/nl — gearchiveerde modelpagina's (Wayback Machine) en Giants eigen archief "Oudere modellen" | de NL-prijs op de gearchiveerde pagina, de vroegste opname van dat modeljaar |
| Trek | trekbikes.com/nl — Treks fietsarchief (2011-2026) | NL-prijs van gearchiveerde overzichts-/productpagina's; de prijs van vandaag voor fietsen die nog te koop zijn |
| Sensa | sensabikes.com — gearchiveerde modelpagina's | de prijs op de pagina. **Geen modeljaar**: de pagina's noemen er geen, dus `model_year` blijft leeg en `seen_date` heeft de opnamedatum |
| Cube (het aanbod van nu) | cube.eu/nl-nl — geen modeljaar op de pagina, dus `seen_date` | de NL-prijs die nu getoond wordt |
| Cube (tot 2024) en 26 andere merken | de catalogus van bikezona.com: Specialized, Cannondale, Scott, Canyon, BMC, Bianchi, Merida, Orbea, Ridley, Cervélo, Pinarello, Focus, Lapierre, Rose, Stevens, KTM, Felt, Wilier, Colnago, De Rosa, Kuota, Time, BH, Fuji, GT, Btwin | de prijs van bikezona, `market` = `ES` |

Om op te letten:

- **`market` doet ertoe.** `NL` is de eigen Nederlandse prijs van het merk;
  `ES` de Spaanse catalogusprijs van bikezona.com — een echte europrijs, maar
  niet de Nederlandse. Een ES-rij staat er alleen waar de eigen Nederlandse
  pagina van het merk voor dat modeljaar geen prijs gaf.
- **Een prijs is wat de bron toonde, op de datum in `price_basis`.** Bij een
  gearchiveerde pagina is dat meestal de lanceringsprijs; een opname laat in
  het seizoen kan al een korting tonen. Voor fietsen die nu te koop zijn telt
  de webshopkorting van Giant niet (de "Reguliere prijs" telt), de `wasPrice`
  van Trek evenmin.
- **Afgeleide kolommen komen uit de eigen specstekst van de rij** en blijven
  leeg als die het niet zegt — `brake_type` vooral is vaak leeg bij oudere
  fietsen waarvan de specslijst het remmodel noemt zonder "rim" of "disc".
  "Disc" in de modelnaam telt.
- Framesets, e-bikes, fitnessfietsen met plat stuur en kinderfietsen zijn
  weggelaten.

Opnieuw opbouwen duurt lang (uren: elk verzoek met pauze, en de Wayback
Machine is vaak traag of even weg). Het gereedschap staat in `catalog_tools/`;
draai het vanuit een lege map, want het schrijft een paginacache en
tussen-JSON in de werkmap:

```bash
mkdir /tmp/catalog && cd /tmp/catalog
sh /pad/naar/repo/catalog_tools/run_all.sh
```

`tests/test_bike_catalog.py` controleert dat elke rij een bron heeft, elke prijs
een markt en een basis, en dat er geen modeljaar staat dat de bron niet
noemde.

## Je eigen marktprijsgeschiedenis — `--price-history-file`

Elke keer dat een advertentie die op een referentiemodel past voor het eerst
gezien wordt, komt zijn prijs in `reference_price_history.csv` (vanzelf
aangemaakt). Vanaf de tweede keer dat een model voorbijkomt, toont het rapport
ook "2e-hands gem. €X (n=Y)" — de gemiddelde 2e-handsvraagprijs die je zelf
voor dat model zag, op Y eerdere waarnemingen. Daar is geen onderzoek of
nieuwprijs voor nodig, het groeit vanzelf, en het zegt vaak meer over een
vraagprijs dan een nieuwprijs van jaren geleden. Uit met
`--no-price-history`.

## De hulpscripts

**`check_hifi_brand.py`** — voor het aanvullen van `reference_prices.csv`
(luidsprekers): welke modellen een merk echt heeft op hifidatabase.com, met
aantallen weergaven/stemmen, in één verzoek — veel goedkoper dan een volledige
zoektocht per model, en het aantal stemmen zegt vooraf of een model het
uitzoeken waard is. Staat los van `racefiets_jev.py`. De site heeft
botbescherming die na een paar snelle verzoeken ingrijpt, dus één merk
tegelijk, niet in een lus.

```bash
python check_hifi_brand.py "Mission"
python check_hifi_brand.py "Wharfedale" --min-votes 5
```

**`check_reference_overlaps.py`** — naarmate een referentiebestand groeit, kan
een patroon breder worden dan bedoeld en advertenties pakken die voor een
andere rij bedoeld waren (de eerste match in bestandsvolgorde wint, dus de
bredere rij steelt ze stil). Dit toetst het patroon van elke rij aan het label
van elke andere rij en meldt elke onverwachte match — zonder netwerk.

```bash
python check_reference_overlaps.py
python check_reference_overlaps.py --file reference_bikes.csv
python check_reference_overlaps.py --file reference_bike_accessories.csv
```

**`reference_overview.py`** — zet `reference_prices.csv` (plus
`reference_price_history.csv` als die er is) om in een losse, doorzoekbare,
sorteerbare HTML-pagina, om je hele referentiedatabase te bekijken zonder de
CSV te openen.

```bash
python reference_overview.py
```

Lokale wijzigingen aan een referentiebestand komen niet vanzelf in git (de
`.gitignore` sluit `*.csv` uit); `git add -f reference_prices.csv` als je ze
wilt committen. De bronnen van de luidsprekers staan in de git-geschiedenis.
