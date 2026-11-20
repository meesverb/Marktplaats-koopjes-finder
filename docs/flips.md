# Flips — `/flips` (`flips.py`, `flips_page.py`, `flips_sheets.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

Start `python dashboard.py --serve` en open `/flips`. Een geaccepteerd bod
(zie "Eigen biedingen" in [live.md](live.md)) of een **Gekocht** op een
dashboard zet een flip er vanzelf op; iets anders voeg je onderaan toe. Per
flip houd je bij wat erin zit, wat er nog moet gebeuren en wat hij opbracht.

```bash
python flips.py                                              # het overzicht in de console
python flips.py import flips_import/cube_peloton_pro.json    # een lijst flips en klussen inlezen
python flips.py bijwerken flips_import/cube_bike24.json      # bestaande regels bijwerken
python flips_sheets.py                                       # gelijk met de Google Sheet (zie SHEETS.md)
```

Alles wat je bezit op één pagina: fietsen, reserveonderdelen en de computers
en horloges die je van de dashboards kocht (de regels van Mijn flips, dezelfde
tabel `trade`). Bovenaan: wat je verdiende (gerealiseerde winst), **netto na
investeringen** (verdiend min gereedschap), wat er vastzit in lopende flips en
wat die zouden moeten opbrengen, de pot investeringen, en dagen tot verkoop /
winst per uur.

## De kaart per flip

- **fase**: op voorraad → gekocht → opknappen → te koop → verkocht, met hoeveel
  dagen hij al in die fase staat;
- **geld**: aankoop, tot nu toe uitgegeven, nog gepland (schattingen),
  verwachte kostprijs, je **doelprijs** (laag–hoog), een **marktcheck**
  (mediane vraagprijs van advertenties in `koopjes.db` met je zoekwoorden,
  laatste 180 dagen — vraagprijzen, geen verkoopprijzen), verwachte winst bij
  laag en hoog, hoogste bod, uren en winst per uur;
- **klussenlijst**: onderdelen (schatting → echte prijs = gekocht → ✓
  gemonteerd), klussen (✓ gedaan) en reizen (volle OV-prijs + *vol / 40%
  korting / gratis*; de pagina rekent uit wat je betaalde). Een onderdeel met
  alleen een schatting telt als gepland (grijs); vul je de echte prijs in, dan
  telt die. Markeer een regel als **gereedschap** om hem naar de pot
  investeringen te verplaatsen;
- **aanbiedingen** per onderdeel (*Aanbiedingen (n)* onder de regel, tabel
  `flip_offer`, migratie 21): plak een link met de prijs die je zag, plus
  verzending, winkel (uit de link als hij leeg is) en een notitie; goedkoopste
  (met verzending) eerst. Volgcodes gaan weg (`?utm_…`, `_gl`, `gclid`,
  AliExpress' `spm`/`algo_…`), een lange AliExpress-link wordt
  `aliexpress.com/item/<nummer>.html`, en een deellink uit de AliExpress-app
  (`a.aliexpress.com/_…`) blijft zoals hij is. Geen link mag, als de notitie
  zegt waar je hem vindt (winkel + zoekterm), met *geen link*. **kies deze**
  zet winkel, link en schatting van de regel (prijs + verzending: wat hij los
  gekocht kost) en de bron; **weg** haalt een aanbieding weg. De pagina haalt
  nooit zelf een prijs op bij een winkel: jij typt hem. Winkel en link van de
  regel zelf zijn daar ook te wijzigen;
- **winkelmandje** per winkel, met een waarschuwing onder gratis verzending
  (FuturumShop €49, AliExpress €10: `flips.FREE_SHIPPING_FROM`);
- **specs** en een **concept-advertentietekst**, alleen uit wat je invulde en
  de onderdelen die je monteerde (plaatsen doe je zelf), **foto's**
  (voor/na, bewaard in `flip_fotos/`, niet in git), de **biedingen** die
  kopers op je advertentie doen (je typt ze over), en de verkoop.

## Winst en voorraad

**Winst.** Uitgegeven = aankoop + aankoopkosten + wat onderdelen, klussen en
reizen van deze flip echt kostten. Verwachte winst = doel − uitgegeven − nog
gepland. Na de verkoop: verkoopprijs − verkoopkosten − uitgegeven (een
onderdeel dat je nooit kocht telt dan niet meer). Gereedschap en materiaal
dat je voor meerdere flips gebruikt zijn **investeringen**: niet in de winst
van één flip, wel afgetrokken in *netto na investeringen*.

**Voorraad.** Wat je bezit maar nog niet besloot te verkopen (fase *op
voorraad*) staat apart met **flippen** (→ te koop) en telt niet als lopend.

Fiets- en voorraadflips hebben `trade.market` = `fietsen`/`spullen`; ze staan
niet in Mijn flips van het computer- of horlogedashboard. Migratie 17 maakt de
tabellen `flip`, `trade_stage`, `flip_task`, `flip_bid` en `flip_photo`.

## Een lijst inlezen

`python flips.py import <json>` leest flips, hun klussenlijsten en losse
investeringen uit een JSON-bestand (Nederlandse sleutels, zie
`flips_import/cube_peloton_pro.json`). Twee keer inlezen voegt niets toe.

Een beter aanbod voor regels die er al staan — een andere winkel, een
productlink, een nieuwe schatting — gaat erin met `python flips.py bijwerken
<json>`: hij zoekt elke regel op zijn titel binnen de flip, laat regels die je
al kocht met rust, en zegt wat hij niet vond. Een regel in dat bestand kan ook
`"aanbiedingen"` hebben: `[{"url", "prijs", "verzending", "winkel",
"notitie", "bron", "bekeken"}]` (`bron`: `gecontroleerd` of `schatting`;
dezelfde link voor dezelfde prijs komt er niet twee keer in).

Het prijsonderzoek voor de Cube Peloton Pro (02-10-2026: aanbiedingen met
links per onderdeel, drie mandjes, AliExpress na de invoerheffing van €3 van 1
juli 2026, de kettingbladvraag) staat in
`flips_import/cube_prijsonderzoek.md`; de aanbiedingen gaan erin met `python
flips.py bijwerken flips_import/cube_aanbiedingen.json`.

## Google Sheets, in twee richtingen

Zie [SHEETS.md](../SHEETS.md): plak `flips_sheets.gs` als Apps Script-webapp
in je Sheet, en zet de URL en een geheim in `sheets.json` (niet in git). Elke
ronde (bij het openen van `/flips`, de knop, of `python flips_sheets.py`) neemt
over wat je sinds de vorige keer in de Sheet veranderde — nieuwe rijen zonder
id worden nieuwe regels, verwijderde rijen worden verwijderd, en veranderden
de pagina en de Sheet dezelfde regel, dan wint de laatste wijziging en zegt de
melding wat er overschreven is — en schrijft daarna de tabbladen Flips,
Klussen, Investeringen en Totalen opnieuw, met getallen als getallen, plus
een tabblad Aanbiedingen dat alleen gelezen wordt (sinds 02-10-2026: plak
`flips_sheets.gs` opnieuw, zie `SHEETS.md`). Eigen formules en grafieken maak
je op een eigen tabblad. Geen nieuwe dependency: het gebruikt `requests`.
