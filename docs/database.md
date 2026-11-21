# De database — `koopjes.db` (`db.py`, `db_schema.py`)

[← README](../README.md) · [alle naslag](README.md)

## Zo gebruik je het

Niets te doen: elke run van `racefiets_jev.py` (en dus elke ronde) schrijft
naar `koopjes.db` naast het script, en alle pagina's lezen eruit. Een andere
database kies je met `--db`; `--no-db` schrijft er niet naar. Kopieer de
database alleen als niets hem open heeft, en met `koopjes.db-wal` en
`koopjes.db-shm` erbij. Hij hoort niet in git (persoonlijke data).

## Wat erin komt

Elke run zet zijn advertenties in de database, náást — niet in plaats van —
de CSV/JSON-bestanden die de crawler schrijft: elk veld dat het script leest
(prijs, plaats, staat, framemaat, biedstatus, ...) wordt per advertentie
bijgewerkt, een rij in `crawl_run` legt de zoekopdracht en het aantal pagina's
vast, en `seen_listings.json`, `reference_prices.csv` en
`reference_price_history.csv` worden opnieuw ingelezen, zodat de database er
gelijk mee blijft. Daarnaast staat alles wat je zelf invoert in de database:
markeringen, notities, biedingen, aan- en verkopen, flips, keuzes op `/fiets`
en `/upgrade`, de postcode (zie [live.md](live.md)). `valuation.py` leest er
ook uit en schrijft zijn taxaties erin (zie [eigen-fiets.md](eigen-fiets.md)).

- De database onthoudt elke zoekopdracht die een advertentie vond (tabel
  `listing_query`), dus een Defy die het laatst door de dagronde "racefiets"
  gezien werd, telt nog mee voor de nachtelijke sweep van "giant defy".
- Hij onthoudt wanneer een crawl een advertentie voor het eerst als
  gereserveerd zag (`listing.reserved_at`, migratie 9; gewist als een crawl hem
  weer niet-gereserveerd ziet). Een gereserveerde advertentie die nog online
  staat telt niet als vergelijkingsprijs voor de fietscomputers, net als binnen
  een run; zodra hij verdwijnt, telt hij als elke andere verdwenen advertentie.
- Het schema staat in `db_schema.py`: één SQL-tekst per migratie, op volgorde.
  `db.connect()` brengt een database naar de laatste versie;
  `db.connect_readonly()` opent hem alleen-lezen en migreert niet.

## WAL-modus

De database draait in de write-ahead-modus van SQLite (sinds 02-10-2026): een
ronde of de live server die duizenden advertenties leest, laat een klik op de
live server niet meer mislukken met "database is locked", en een schrijfactie
wacht tot 30 s op een andere. Zolang hij open is, staan er twee bestanden
naast: `koopjes.db-wal` en `koopjes.db-shm`. Die horen bij de database (niet
los weggooien). Vindt een klik hem toch bezet, dan zegt de pagina dat en wordt
er niets bewaard.

## Wanneer een advertentie als verdwenen geldt

Alleen een volledige crawl (`--pages 0`) markeert eerder geziene advertenties
van die zoekopdracht als verdwenen als ze niet meer opduiken — een ondiepe run
met `--pages 3` keek maar naar een deel van de markt en trekt die conclusie
nooit. Ook een `--pages 0`-crawl die niet elk resultaat zag niet:
Marktplaats stopt met bladeren na ongeveer 5000 advertenties (167 pagina's;
"racefiets" heeft 26000+ resultaten), een pagina kan mislukken, en de
standaardvolgorde herhaalt advertenties over pagina's.

- Een pagina die mislukt krijgt na 60 seconden nog één kans (gezien
  28-09-2026: één 403 van Marktplaats tussen twee goede verzoeken); pas een
  tweede mislukking beëindigt de crawl als onvolledig. Met `--delay 0` is er
  geen wachttijd.
- De sweep draait alleen als het aantal verschillende geziene advertenties
  klopt met het totaal dat Marktplaats meldt, en zegt anders waarom hij
  oversloeg — gebruik een smallere zoekopdracht (bijv. "giant defy"),
  `--category` en `--sort newest` voor de volledige crawl waarvan je de
  verdwijningen wilt tellen, of `--split` voor een hele categorie (zie
  [zoeken.md](zoeken.md)).
- Eén uitzondering: een crawl die elke pagina laadde maar er maar een paar
  miste (hooguit 3, of 2% van het totaal). Dat gebeurt als een advertentie
  verkocht wordt *terwijl* de crawl door de resultaten bladert — alles erna
  schuift een plek op en één advertentie belandt op een pagina die al
  opgehaald is. Zo'n crawl noteert de gemiste advertenties (`missed_at`) zonder
  ze verdwenen te noemen; een advertentie die de volgende volledige crawl ook
  mist, wordt verdwenen per zijn eerste misser, en een die in welke crawl dan
  ook weer opduikt, wordt gewist. De console zegt dan `verdwijn-sweep
  voorlopig`.

Verdwenen is niet verkocht: een advertentie kan ook ingetrokken zijn. Wat de
pagina's "snel verkocht" noemen (binnen 7 dagen weg, of gereserveerd en weg)
is de beste benadering die de zoekresultaten toelaten.
