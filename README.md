# Marktplaats koopjes finder

Zoekt op [Marktplaats](https://www.marktplaats.nl) naar advertenties, bewaart
alles wat het ziet in een eigen database en laat zien wat de moeite waard is:
racefietsen, fietscomputers en sporthorloges die onder hun marktprijs staan,
betere fietsen dan je eigen, en wat je eigen fiets waard is. Draait lokaal op
je eigen computer, voor één gebruiker, zonder server of account.

Het programma **kijkt en rekent; kopen doe je zelf.** Het biedt nooit en
reageert nooit op een advertentie.

## Wat je krijgt

| Pagina | Wat je er doet | Meer |
| --- | --- | --- |
| `/start` | beginpunt: de laatste ronde, wat je flips opleverden, je lopende biedingen, een knop per ronde | [dashboards](docs/dashboards.md) |
| `/racefietsen` | alle racefietsen als kaarten met foto's, een verkoopschatting, of het een upgrade is; beoordelen, wegzetten, bod vastleggen, dossier voor Claude | [racefietsen](docs/racefietsen.md) |
| `/` en `/horloges` | fietscomputers en sporthorloges: flips (onder de verwachte verkoopprijs), upgrades, favorieten, marktprijzen per model, patronen | [dashboards](docs/dashboards.md) |
| `/fiets` | welke advertenties meetellen in de taxatie van je eigen fiets | [eigen fiets](docs/eigen-fiets.md) |
| `/upgrade` | de upgradetest: jij zegt wat een upgrade is, de regel volgt jou | [eigen fiets](docs/eigen-fiets.md) |
| `/flips` | wat je kocht om door te verkopen: fase, klussen, onderdelen, foto's, opbrengst | [flips](docs/flips.md) |
| `overzicht.html` | na elke ronde: wat is nieuw, wat is gezakt, de slapers | [rondes](docs/rondes.md) |
| `racefiets_report*.html` | het rapport van één zoekopdracht, gesorteerd op dealscore | [rapport](docs/rapport.md) |

De pagina's met een `/` komen van de live server (`python dashboard.py
--serve`, alleen bereikbaar vanaf je eigen computer); de `.html`-bestanden
schrijft een ronde en kun je ook los openen.

## Beginnen

Nodig: Python 3.10 of nieuwer (ontwikkeld op 3.13) en één pakket.

```bash
pip install -r requirements.txt
```

Een proef, één pagina zoekresultaten, zonder dat er een browser opent:

```bash
python racefiets_jev.py --query luidsprekers --pages 1 --open-browser never
```

Daarna de echte opzet. Wat er gezocht wordt en wanneer staat in
`schedule.json`; `koopjes.py` draait één tijdslot:

```bash
python koopjes.py status
```

```bash
python koopjes.py run overdag
```

```bash
python dashboard.py --serve
```

De laatste opent `http://127.0.0.1:8765/start`. Stoppen met Ctrl+C.

## Vanzelf laten draaien

```bash
python koopjes.py schedule
```

Dat print de regels voor de Windows Taakplanner of `crontab`, met de paden al
ingevuld. Eén keer plakken en de rondes draaien vanzelf:

| Tijdslot | Wanneer | Wat |
| --- | --- | --- |
| `overdag` | 08:30, 13:30, 19:30 | de nieuwste racefietsen (8 pagina's) |
| `computers` | 10:00, 14:00, 18:00, 22:00 | de nieuwste fietscomputers en Garmin-horloges (2 pagina's) |
| `nacht` | 03:00 | alles volledig: Giant Defy, Ultegra 6700, powermeters, fietscomputers, alle sporthorloges; daarna de taxatie |
| `week` | zondag 05:00 | elke racefiets op Marktplaats, in delen |
| `defy`, `horloges` | met de hand (`python koopjes.py run defy`) | hetzelfde als 's nachts voor één onderwerp, als je het nu wilt weten |

Een ronde die begint terwijl een andere nog loopt wordt overgeslagen, dus
Marktplaats krijgt nooit twee crawls tegelijk. Alles over de rondes, de
tijden en de budgetten per ronde: [docs/rondes.md](docs/rondes.md).

## Hoe je ermee werkt

1. Open `/start` en kijk of de rondes gedraaid hebben.
2. Werk op `/racefietsen` (of bij de computers en horloges) de weergave
   **Te beoordelen** af: ★ favoriet, weg met een reden, of een notitie. Wat
   je wegzet komt pas terug als de prijs zakt.
3. Twijfel je over een fiets: **controleer** haalt de advertentie opnieuw op
   (gereserveerd? biedingen? prijs?), **dossier** zet alles op een rij om aan
   Claude te geven.
4. Geboden op Marktplaats? Leg het vast met **ik heb geboden**. Zet je het
   bod op *geaccepteerd*, dan staat de aankoop meteen op `/flips`.
5. Op `/flips` houd je bij wat er nog aan moet gebeuren en wat het opbracht.

## De getallen in het kort

Er zijn vier verschillende scores. Ze meten elk iets anders en worden nergens
opgeteld:

| Score | Vraag | Waar |
| --- | --- | --- |
| **Dealscore** (0-100) | is deze *prijs* goed, vergeleken met de mediaan, de eigen prijshistorie en de nieuwprijs? | rapport — [rapport.md](docs/rapport.md) |
| **Slaper** (vanaf 70 punten) | zegt de tekst zo weinig dat niemand hem vindt? Kijk naar de foto's | rapport, overzicht — [rapport.md](docs/rapport.md) |
| **Kwaliteitsscore** (0-100) | hoe goed is deze *fiets*, los van de prijs? | `/racefietsen`, `/upgrade` — [eigen-fiets.md](docs/eigen-fiets.md) |
| **Waardescore** | geschatte waarde ÷ gevraagde prijs | rapport, `/racefietsen` — [rapport.md](docs/rapport.md) |

Een **flip** is geen score maar een bedrag: de verwachte verkoopprijs van
hetzelfde model min wat het kost. Een schatting rust op vraagprijzen van
vergelijkbare advertenties; een advertentie die verdween is niet bewezen
verkocht. Elke schatting zegt daarom op hoeveel advertenties hij rust.

## Spiekbrief

| Commando | Wat |
| --- | --- |
| `python koopjes.py status` | klopt `schedule.json`, wanneer draaide wat, de laatste 3 rondes |
| `python koopjes.py run <tijdslot>` | één ronde, precies zoals de planner hem start |
| `python koopjes.py schedule` | de regels voor Taakplanner / cron |
| `python koopjes.py dashboard` | de dashboards opnieuw bouwen zonder ronde |
| `python koopjes.py lists` | `lijsten/beste_koopjes.txt` en `lijsten/zonder_referentie.txt` |
| `python dashboard.py --serve` | alles live op `http://127.0.0.1:8765/start` |
| `python racefiets_jev.py --query ... --pages N` | één zoekopdracht met de hand — [zoeken.md](docs/zoeken.md) |
| `python valuation.py --db koopjes.db` | wat is mijn fiets waard |
| `python upgrade.py --db koopjes.db` | welke betere fiets kan ik daarvoor kopen |
| `python dossier.py <id> --ophalen --uit dossier.md` | alles over één racefiets als tekst |
| `python computers.py` / `python watches.py` | score en markt per model, in de console |
| `python vinted.py import <export.csv>` | een Vinted-export naast Marktplaats zetten |
| `python flips.py import <lijst.json>` | een lijst flips en klussen inlezen |
| `python -m unittest discover -s tests -t tests` | de tests |

## Wat er op je schijf komt

Alles wat het programma schrijft blijft lokaal en staat in `.gitignore`:

| Bestand | Inhoud |
| --- | --- |
| `koopjes.db` (+ `-wal`, `-shm`) | de database: elke advertentie, prijsverloop, je markeringen, biedingen, flips — [database.md](docs/database.md) |
| `overzicht.html`, `racefiets_report*.html`, `dashboard.html`, `dashboard_horloges.html` | wat een ronde bouwt |
| `lijsten/`, `logs/` | tekstlijsten om in een gesprek te plakken; het logboek van de rondes |
| `seen_listings.json`, `bargains_log.csv`, `reference_price_history.csv` | de oude bestanden van vóór de database; worden nog bijgehouden |
| `flip_fotos/`, `sheets.json` | je foto's op `/flips`; de sleutel van de Google Sheet |

Wél in git staan de onderzochte referentiebestanden (`reference_*.csv`,
met een bron per rij) en de documenten over je eigen fiets: `mijn_fiets.md`
(het intakebestand dat het programma leest) en de rest in `fiets/`.

## Spelregels

- **Nooit automatisch bieden of reageren.** Er is geld en een andere partij
  mee gemoeid; dat doe je zelf.
- **Beleefd tegen Marktplaats.** Eén verzoek tegelijk, een pauze ertussen
  (`--delay`), nooit twee rondes tegelijk, en niet vaker crawlen dan in
  `schedule.json` staat.
- **Geen verzonnen marktfeiten.** Een nieuwprijs of modeljaar staat er met
  bron, of staat er niet.

## Verder lezen

| Document | Voor wie |
| --- | --- |
| [docs/](docs/README.md) | naslag per onderwerp: alle vlaggen, tabbladen, berekeningen en de metingen erachter |
| [docs/architectuur.md](docs/architectuur.md) | welk bestand doet wat |
| [CLAUDE.md](CLAUDE.md) | werkafspraken voor wie (of wat) aan de code werkt |
| [VERBETERPLAN.md](VERBETERPLAN.md) | wat er aan de code en de documentatie verbeterd kan worden, in kleine stappen |
| [LOGBOEK.md](LOGBOEK.md), [PLAN_FIETSWAARDE.md](PLAN_FIETSWAARDE.md) | hoe het gegroeid is, met datums en metingen |
| [NEXT_STEPS.md](NEXT_STEPS.md) | welke ideeën er nog liggen, en wat we over Marktplaats leerden |
| [MARKTONDERZOEK.md](MARKTONDERZOEK.md) | welke Marktplaats-categorieën als volgende markt passen |

Marktplaats kan zijn pagina's op elk moment veranderen. Breekt het lezen
daarvan, dan geeft het programma een duidelijke foutmelding in plaats van stil
door te gaan.
