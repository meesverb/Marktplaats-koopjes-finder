# /flips koppelen aan een Google Sheet

Eenmalig, ongeveer tien minuten. Daarna houdt `/flips` (in
`python dashboard.py --serve`) de Sheet bij, en neemt het over wat je in de
Sheet wijzigt.

## Hoe het werkt

Sheets kan niet bij je laptop, dus je laptop gaat naar de Sheet. In de Sheet
draait een klein script (`flips_sheets.gs`) dat als webapp online staat en
alleen antwoordt op wie de geheime sleutel meestuurt. Een ronde:

1. ophalen wat er in de Sheet staat;
2. overnemen wat je daar sinds de vorige ronde wijzigde. Het script zet bij
   elke wijziging de verborgen kolom `bijgewerkt` van die rij op nu. Een
   nieuwe rij zonder id wordt een nieuwe regel, en een verwijderde rij wordt
   ook verwijderd. Is dezelfde regel op de pagina én in de Sheet gewijzigd,
   dan **wint de laatste wijziging**, en de melding zegt wat er overschreven
   is;
3. de tabbladen **Flips**, **Klussen**, **Investeringen** en **Totalen**
   opnieuw schrijven.

Een ronde gebeurt vanzelf bij het openen van `/flips`, met de knop **Nu
synchroniseren** onderaan de pagina, of met `python flips_sheets.py`.

## Instellen

1. Maak een nieuwe Google Sheet (bijvoorbeeld via sheets.new) en noem hem
   "Flips".
2. Kies in de Sheet **Extensies → Apps Script**. Vervang alles in `Code.gs`
   door de inhoud van `flips_sheets.gs` uit deze map, en sla op.
3. Maak een sleutel: `python flips_sheets.py sleutel` drukt er een af.
4. Ga in Apps Script naar **Projectinstellingen** (het tandwiel), en dan naar
   **Scripteigenschappen → Scripteigenschap toevoegen**. Vul als eigenschap
   `SECRET` in en als waarde de sleutel.
5. Kies **Implementeren → Nieuwe implementatie**, met als type **Webapp**:
   - Uitvoeren als: **Ik**
   - Wie heeft toegang: **Iedereen**. Zonder de sleutel doet het script
     niets.

   Klik op Implementeren, geef toegang (Google waarschuwt omdat het je eigen,
   niet-geverifieerde script is: Geavanceerd → toch doorgaan), en kopieer de
   **webapp-URL** (die eindigt op `/exec`).
6. Zet naast `dashboard.py` een bestand `sheets.json` neer:

   ```json
   {
     "url": "https://script.google.com/macros/s/…/exec",
     "secret": "de sleutel van stap 3",
     "sheet_url": "https://docs.google.com/spreadsheets/d/…",
     "auto": true
   }
   ```

   `sheet_url` is optioneel; dan staat er een link naar de Sheet op de
   pagina. Met `"auto": false` synchroniseert hij alleen als je op de knop
   klikt. `sheets.json` staat in `.gitignore`, want de sleutel hoort niet in
   git.
7. Start `python dashboard.py --serve`, open `/flips` en klik op **Nu
   synchroniseren**. De vier tabbladen verschijnen.

Heb je `flips_sheets.gs` later aangepast? Kies dan **Implementeren →
Implementaties beheren → bewerken (potlood) → Versie: nieuwe versie**. Anders
blijft de oude versie draaien.

## Wat je in de Sheet kunt wijzigen

De grijze kolommen zijn uitkomst en worden elke ronde overschreven.

- **Klussen**: titel, winkel, geschat, prijs (de echte prijs), bron,
  investering (ja/nee), tarief en korting (bij een reis), gedaan (ja/nee) en
  notitie. Een nieuwe klus: een rij onderaan met in de kolom `flip` het
  nummer van de flip (kolom `id` van het tabblad Flips; maak die kolom
  zichtbaar via rechtsklik → kolommen zichtbaar maken).
- **Investeringen**: net zo, maar zonder flip.
- **Flips**: fase (niet *verkocht*: dat doe je op de pagina, met een prijs),
  doel_laag, doel_hoog, uren, zoekwoorden, verkooplink en notitie.

## Eigen formules en grafieken

Zet ze op een **eigen tabblad**, want de vier tabbladen hierboven worden elke
ronde leeggemaakt en opnieuw geschreven. Verwijs vanaf je eigen tabblad naar
de kolommen, bijvoorbeeld:

- `=SUM(Flips!Q2:Q)` voor de winst van alles wat verkocht is;
- `=SUMIF(Klussen!J2:J;"nee";Klussen!M2:M)` voor wat je aan onderdelen en
  reizen uitgaf, zonder gereedschap;
- een grafiek op `Flips!B:B` (titel) tegen `Flips!Q:Q` (winst).

Verwijs naar kolommen, niet naar losse cellen: de rijen kunnen per ronde van
volgorde veranderen.
