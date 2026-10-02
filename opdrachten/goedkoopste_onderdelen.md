# Opdracht: goedkoopste onderdelen zoeken + "link plakken met prijs" op /flips

> **Stand (02-10-2026): deel B is gebouwd** (tabel `flip_offer` werd migratie
> 21, niet 18: die was al bezet; met een extra kolom `source`, zodat een
> geschatte AliExpress-prijs na "kies deze" geen "gecontroleerd" wordt). Zie
> README → Flips. Deel A: zie `opdrachten/weekend.md`.

Voor een agent die hier los op gaat. Lees eerst `CLAUDE.md` en werk vanaf een
verse `main`. Twee delen: **A** is onderzoek (prijzen zoeken), **B** is een
kleine uitbreiding van `/flips`. Ze staan los van elkaar; doe A eerst, want
B maakt het resultaat van A bruikbaar op de pagina.

## De harde eis: elke prijs met een URL

**Zonder URL telt een prijs niet.** Voor elk aanbod dat je noemt, zet je
erbij:

- de **directe link naar de productpagina**, zodat de eigenaar hem kan
  openen en zelf kan zien wat het is. Geen zoekpagina, geen categoriepagina
  en geen verkorte of affiliate-link. Haal trackingcodes weg (`?_gl=`,
  `?spm=`, `utm_...`), maar houd wat nodig is om de juiste variant te openen,
  of noem de variant erbij. Voor AliExpress geldt iets anders: zie
  hieronder;
- de **exacte productnaam** zoals de winkel hem noemt, met de variant (maat,
  aantal tanden, speed);
- de **prijs inclusief btw**, de **verzendkosten** naar Nederland en de grens
  voor gratis verzending, de **levertijd**, en of het **op voorraad** is;
- de **datum** waarop je het bekeek.

Kon je een pagina niet openen? Zeg dat dan, en zet het bedrag als
**schatting** en niet als gecontroleerd. Verzin geen prijs (zie "Verzin geen
marktfeiten" in `CLAUDE.md`).

### Uitzondering: AliExpress

**AliExpress is voor een agent niet te openen** (het blokkeert
geautomatiseerde bezoekers en laadt prijzen pas met JavaScript), en de
eigenaar kan uit de app geen nette link kopiëren. Daarom geldt voor
AliExpress:

- **Geen AliExpress-prijs als gecontroleerd.** Wat je via een zoekmachine of
  een vergelijkingssite vindt, noteer je als **schatting**, met de bron waar
  je het las.
- **Geef wat de eigenaar nodig heeft om het zelf te vinden:**
  - de naam van de winkel, bijvoorbeeld "KMC Official Store";
  - de exacte zoekterm;
  - als je hem vindt, het **itemnummer**. Dat is het lange getal in
    `aliexpress.com/item/<nummer>.html`; zo'n link opent de eigenaar zelf
    wel.
- **De eigenaar vult daarna zelf de echte prijs in** met de knop uit deel B.
  Daar is die knop juist voor.
- Vergelijk AliExpress wel met de rest. Rekenen doe je met de schatting, en
  je zegt erbij dat de eigenaar hem moet bevestigen.

## Achtergrond

- De eigenaar knapt een **Cube Peloton Pro, maat 62** op om te verkopen
  (doel €400–450): Shimano 105 **5701** (10-speed), velremmen en Mavic
  Aksium-wielen. Hij staat op `/flips` in `python dashboard.py --serve`.
  De lijst zelf staat in `flips_import/cube_peloton_pro.json`.
- Een regel op de klussenlijst is een rij in `flip_task` (`flips.py`,
  migratie 17). De velden die er al zijn: `shop`, `url`, `est_eur`
  (schatting), `price_eur` (echte prijs, dus gekocht) en `price_source`
  (`gecontroleerd` / `schatting`). Het veld `url` bestaat al, maar er is nog
  geen invulveld voor op de pagina (zie B).
- **De eigenaar heeft al:** wax lube, een multitool met kettingpons, een
  missing-link-tang, een kettingzweep en een opzetstuk voor de
  cassette-afnemer, een pomp, een reserve-quicklink en een Cyclon
  cleaning-set. Zoek daar niet naar.
- Het is een flip, dus goedkoop gaat voor. Maar niet ten koste van iets dat
  een koper bij een proefrit merkt: slecht schakelen, piepende remmen of een
  ketting die rekt.

## A. Onderzoek: waar is elk onderdeel het goedkoopst?

### De onderdelen

Dit zijn de huidige bedragen uit de lijst van 29-09-2026. "Gecontroleerd" wil
zeggen dat de prijs die dag op de site is bekeken, maar er staat nog geen URL
bij.

| Onderdeel | Nu | Bron |
| --- | --- | --- |
| Shimano Tiagra CS-HG500 cassette 11-32T (10-speed) | FuturumShop €29,95 | gecontroleerd |
| Shimano derailleurwieltjes 5700 (set) | FuturumShop €11,95 | gecontroleerd |
| 2× Continental Ultra Sport III 700×25C vouwband | FuturumShop €41,90 | gecontroleerd; Velondo €14,78/st, verzending onbekend |
| Shimano R55C4 remblokken (inserts, achter) | FuturumShop €10,95 | gecontroleerd |
| Ketting KMC X10 (10-speed) | AliExpress ±€13 | schatting; in NL €31–41 |
| Voorblad 50T 110BCD, road 2×, met pinnen | AliExpress ±€12 | schatting — zie hieronder |
| Stuurlint | AliExpress ±€5 | schatting |
| Titanium boutjes M5 (stuurpen + bidonhouder) | AliExpress ±€8 | schatting, optioneel |
| Framebescherming (chainstay protector) | AliExpress ±€2 | schatting |
| 2× binnenband 700×23/32 presta | Decathlon €7,98 | gecontroleerd, gratis ophalen |
| Magic sponzen, wit lakstiftje, nagellak/modelverf rood+blauw | Action ±€1/€5/€3 | schatting |
| *Investering:* kettingslijtagemeter, blauwe schroefborg | AliExpress ±€2/€2 | schatting |
| *Investering:* wasbenzine, isopropylalcohol, autowas, microvezeldoeken, krasverwijderaar | Action ±€2/€3/€4/€2/€5 | schatting |

### Waar zoeken

Zoek minstens bij FuturumShop, bike-components.de, Bike24, Mantel, Bol,
Decathlon, Amazon.nl, Velondo, AliExpress (bij merkonderdelen alleen de
officiële merkwinkel), Action, Kruidvat, Praxis/Gamma/Hornbach (voor
wasbenzine, IPA en schroefborg) en 2e-hands op Marktplaats voor nieuwe of
ongebruikte onderdelen.

**Op Marktplaats alleen kijken.** Niet reageren en niet bieden (harde regel).
Houd je aan het tempo van `--delay`: geen parallelle verzoeken en geen
massale crawl.

### Het hele mandje, niet alleen de laagste losse prijs

De goedkoopste losse prijs is niet altijd het goedkoopste mandje. Maak **twee
of drie mandjes**:

- het goedkoopste;
- het snelste (alles binnen een paar dagen in huis);
- één met zo min mogelijk bestellingen.

Reken elk mandje door met de verzendkosten en de grenzen voor gratis
verzending. Noem per mandje het totaal en wat het scheelt ten opzichte van
de lijst hierboven (±€190 in totaal).

### AliExpress: is het echt een deal?

De eigenaar twijfelt hieraan. Beantwoord het per onderdeel, met bronnen:

- **Btw en douane:** klopt het dat AliExpress bij een bestelling naar NL
  onder de €150 de btw al in de prijs rekent (IOSS), zodat er geen douane- of
  inklaringskosten bij komen? Controleer dit op een actuele bron en zet die
  erbij. Een bestaande regel onthouden is niet genoeg.
- **Levertijd:** vaak 1–3 weken. Zeg per onderdeel of dat de verkoop van de
  fiets ophoudt.
- **Namaak en kwaliteit:** hoe zeker is het dat een "KMC X10" uit de
  officiële KMC-winkel op AliExpress echt is? Hoe groot is het verschil met
  NL (±€18)? Een ketting die slecht schakelt of snel rekt, merkt een koper.
- **Terugsturen:** hoe werkt dat, en wat kost het als het niet past?

### Het kettingblad: de GOLDIX die de eigenaar vond

De eigenaar vond op AliExpress een **"GOLDIX 110BCD kettingblad dubbel
50-34T, 7075, 9/10/11-speed, 5 armen, 3 mm"**. De verkoper is "Stone's Store"
en ook "Ali Cycling Store". Een link is er niet (zie *Uitzondering:
AliExpress*). Beoordeel het op de tekst van de advertentie die hij plakte.
Die staat hieronder, en de prijs vraag je aan de eigenaar.

> GOLDIX 110BCD Fietskettingblad Dubbele Disc 50-34T voor Racefiets Crankstel
> Compatibel 9/10/11Speed. Artikel: Power dubbele elliptische
> kettingbladgroep. Voor 700C racefiets kettingbladset. Merk: GOLDIX.
> Materiaal: 7075. Kleur: Zwart. Vorm: Rond. Nettogewicht: ongeveer 122g
> (kleine plaat-30g; grote plaat-93g). Dikte: 3MM. Komt overeen met de
> maximale snelheid: 9-11 versnellingen. Pak voor Pawl: 5 poten crank. Pak
> voor Crank Merk: SRAM, FSA, enz. Verwerking: Volledig CNC-geïntegreerd
> gieten. Geanodiseerd oppervlak polijsten. Vragen van kopers, zonder
> antwoord: "Wat is de afstand van schroef tot schroef?", "Het is voor
> Ultegra 11-speed.", "SUPER RECORD CAMPAGNE?". Verkocht door Stone's Store,
> verkoper volgens de conformiteitsinformatie Ali Cycling Store. Tekst
> automatisch vertaald (disclaimer op de pagina).

Een paar dingen die opvallen in die advertentie. Controleer ze, trek geen
conclusie op gevoel:

- **Rond of ovaal?** De tekst zegt eerst "dubbele elliptische
  kettingbladgroep" en daarna "Vorm: Rond". Welke van de twee is het? Een
  ovaal blad schakelt anders en een koper merkt dat.
- **Past het op deze crank?** Het is een **set van twee** bladen (50 en 34).
  Op de lijst staat alleen een 50T-blad. Zoek uit:
  - welke crank er op deze Cube zit (FC-5700 of FC-5750, of een andere) en
    welke **BCD** die heeft (110 of 130). Zoek dat op bij Shimano, met bron.
    Laat de eigenaar het ook nameten: de afstand tussen twee naast elkaar
    liggende boutgaten × 1,701 geeft de BCD bij 5 armen;
  - of het kleine blad ook versleten is. Zo niet, is alleen een 50T dan
    goedkoper?
- **Schakelen:** een no-name blad heeft vaak minder goede schakelhulpen
  (pinnen en ramps) dan een Shimano-blad. Hoe verhoudt het zich tot een
  origineel Shimano 105-blad of een merk als Stronglight of TA? Zoek die ook,
  met prijs en URL.
- **Is vervangen wel nodig?** Is het blad echt versleten (haaienvinnen,
  scheve tanden), of is het oude blad met een nieuwe ketting goed genoeg?
  Beschrijf wat de eigenaar kan controleren.

Zet het resultaat als tabel naast elkaar: GOLDIX-set, alleen een 50T van een
merk, een origineel Shimano-blad, en niets vervangen. Per optie: prijs met
verzending, URL, levertijd, risico, en je advies voor een flip.

### Wat je oplevert voor A

1. **`flips_import/cube_prijsonderzoek.md`**:
   - per onderdeel een tabel met de aanbiedingen (winkel, productnaam, prijs,
     verzending, levertijd, voorraad, datum en **URL**);
   - de mandjes met hun totaal;
   - het AliExpress-oordeel met bronnen;
   - de kettingbladvergelijking.
2. De beste keuze per onderdeel in een vorm die `/flips` kan inlezen. Dat kan
   op een van twee manieren:
   - een **nieuw** JSON-bestand in het formaat van
     `flips_import/cube_peloton_pro.json` met `winkel`, `url`, `geschat` en
     `bron`;
   - of, als B klaar is, als aanbiedingen (zie B).

   Let op: `flips.py import` slaat een flip over die er al is. Bestaande
   regels bijwerken moet dus via een nieuwe functie of op de pagina, niet
   door nog eens in te lezen. Overleg dit met de eigenaar als het onduidelijk
   is.

## B. Op /flips: een link plakken met een prijs erbij

De eigenaar wil zelf gevonden aanbiedingen kunnen vastleggen: **een URL
plakken en er een prijs bij zetten**, en bij een onderdeel **meerdere
aanbiedingen naast elkaar** zien.

### Voorstel

Leg dit eerst aan de eigenaar voor en pas het aan waar hij iets anders wil.

- Een nieuwe tabel **`flip_offer`** (migratie 18) met:
  - `id`;
  - `task_id`, naar `flip_task`;
  - `url` (verplicht). Neem ook een deellink uit de AliExpress-app aan
    (`a.aliexpress.com/_...`, `s.click.aliexpress.com/...`): die kopieert de
    eigenaar uit de app, en hij opent ook. Een lange AliExpress-link maak je
    kort tot `https://www.aliexpress.com/item/<nummer>.html`; de rest is
    tracking. Heeft de eigenaar echt geen link, dan mag het veld leeg zijn als
    er een notitie staat (winkel + zoekterm), met een grijs label *geen link*;
  - `shop`: uit het domein, maar aan te passen;
  - `price_eur` (verplicht);
  - `shipping_eur`;
  - `note`;
  - `checked_at`, `added_at`, `deleted_at`.

  Voeg de tabel toe aan `db.FLIP_TABLES` (tests rollen migraties terug met
  die lijst).
- Per klussenregel op `/flips` een klapblok **"Aanbiedingen (n)"** met:
  - een invulveld **"Link plakken"** en een veld **"prijs €"**, met optioneel
    verzending en notitie, plus de knop **toevoegen**. Een URL moet met
    `http(s)://` beginnen; haal trackingparameters weg zoals `flip_action_new`
    in `dashboard.py` dat doet;
  - de aanbiedingen, goedkoopste eerst (prijs + verzending), met een
    klikbare link (`target=_blank rel=noopener`) en het domein erbij;
  - per aanbieding de knop **"kies deze"**. Die zet `shop`, `url` en
    `est_eur` van de regel en `price_source` op `gecontroleerd`, zodat de
    geplande kosten en het winkelmandje meteen kloppen. Plus een knop
    **weg**.
- Aanbiedingen bij de losse investeringen werken hetzelfde.
- **Haal niet zelf de prijs van de pagina op.** De eigenaar tikt hem in. Een
  winkelpagina uitlezen is scrapen van een externe site en breekt bij elke
  wijziging. Als je het toch wilt, stel het dan apart voor en vraag het eerst.
- Alles zonder herladen, net als de rest van `/flips`: een actie in
  `FLIP_ACTIONS` die met `flips_update()` de kaart teruggeeft.
- Neem de aanbiedingen mee naar de Google Sheet (`flips_sheets.py`), als
  alleen-lezen tabblad **Aanbiedingen** met de URL als klikbare link. Of zeg
  waarom niet.
- De velden `url` en `shop` van een regel zelf moeten ook op de pagina aan te
  passen zijn. Ze zijn nu alleen via de import en de Sheet te zetten.

### Voorwaarden

- Tests in `tests/test_flips.py`, in dezelfde stijl:
  - toevoegen, kiezen en weghalen van een aanbieding;
  - een verkeerde URL wordt geweigerd;
  - trackingcodes worden weggehaald, en een lange AliExpress-link wordt
    `/item/<nummer>.html`;
  - de migratie;
  - dat de kaart na "kies deze" de nieuwe geplande kosten toont.
- Het aantal tests in `CLAUDE.md` bijwerken, en de README (sectie *Flips*)
  en de bestandstabel in `CLAUDE.md` aanvullen.
- Geen nieuwe dependencies. Nederlandse teksten, Engelse identifiers.
- Eindig op `main`, en zeg naar welke branch je pushte.

## Samengevat voor de eigenaar

Aan het eind wil de eigenaar per onderdeel zien:

- waar het het goedkoopst is;
- de link, zodat hij het zelf kan zien;
- wat hij bespaart ten opzichte van nu;
- of AliExpress per onderdeel echt voordeliger is, levertijd en risico
  meegerekend;
- wat het beste kettingblad is, of dat hij het oude kan houden.
