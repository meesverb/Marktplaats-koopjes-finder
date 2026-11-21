# Naslag

[← README](../README.md)

De [README](../README.md) zegt wat het project doet en hoe je het elke dag
gebruikt. Hier staat de rest: per onderwerp alles wat er over te weten valt,
met de metingen aan Marktplaats waar de keuzes op rusten.

| Pagina | Waarover |
| --- | --- |
| [rondes.md](rondes.md) | `koopjes.py` en `schedule.json`: tijdsloten, wat een ronde doet, het overzicht, de logboeken |
| [zoeken.md](zoeken.md) | `racefiets_jev.py`: alle vlaggen, categorieën, sortering, `--split`, watchlists, biedadvertenties, groepsetherkenning |
| [rapport.md](rapport.md) | het rapport per zoekopdracht: dealscore, slapers, prijsverlagingen, de tabs Biedpaneel / Upgrade / Mijn fiets |
| [live.md](live.md) | `python dashboard.py --serve`: `/start`, rondes starten, eigen aan- en verkopen, favoriet/weg en notities, controleer, afstand, eigen biedingen, weergaven en likes, waarom het snel is |
| [fietscomputers.md](fietscomputers.md) | `dashboard.html`: de tabs, hoe de winst berekend wordt, wat telt als computer, het referentiebestand, Vinted |
| [horloges.md](horloges.md) | `dashboard_horloges.html`: zoekopdrachten, de flips met zorg lezen, de catalogus `reference_sport_watches.csv` |
| [racefietsen.md](racefietsen.md) | `/racefietsen`: de kaarten, de schatting, het dossier voor Claude, fietsmodellen en regels |
| [eigen-fiets.md](eigen-fiets.md) | de eigen fiets: taxatie (`valuation.py`, `/fiets`), kwaliteitsscore (`scoring.py`), upgrade-finder (`upgrade.py`), de upgradetest (`/upgrade`) |
| [flips.md](flips.md) | `/flips`: fases, klussen, aanbiedingen, foto's, biedingen van kopers |
| [../SHEETS.md](../SHEETS.md) | `/flips` koppelen aan een Google Sheet |
| [referentiedata.md](referentiedata.md) | de referentie-CSV's (`--reference-file`), de fietscatalogus, de eigen prijshistorie en de hulpscripts |
| [database.md](database.md) | `koopjes.db`: WAL-modus, wat erin staat, verhouding tot de oude CSV/JSON-bestanden |
| [architectuur.md](architectuur.md) | welk bestand doet wat, met tabellen, migraties en ingangen — voor wie aan de code werkt |

**Herkomst.** Dit is de tekst van de oude, lange Engelse README, per
onderwerp uit elkaar gehaald (16-11-2026) en vertaald (21-11-2026). Elke
pagina begint met "Zo gebruik je het"; getallen, vlaggen en metingen zijn
ongewijzigd overgenomen.

**Bijhouden.** Verandert het gedrag van een vlag, een pagina of een
bestandsformaat, werk dan de pagina hier bij in dezelfde commit. Alles wat
hier staat moet blijven werken.
